"""
Alerta Roblox - programa do PC
------------------------------
Le o texto de uma regiao da tela e, quando aparecer uma das frases
configuradas em MENSAGENS, manda alerta para o app Alerta Roblox no celular
(e para o canal do Discord escolhido) com a mensagem, o nome do jogador e o
codigo do servidor.

Pelo instalador (AlertaRoblox-Setup.exe) ele abre uma janela e fica com um
icone perto do relogio do Windows, sem janela preta. Tudo e feito pela janela:
conectar com o Discord, escolher a area da tela, escolher o canal do Discord,
enviar teste e editar as frases.

Rodando pelo Python (para desenvolvimento):
    pip install -r requirements.txt
    python monitor.py            -> abre a janela (igual ao instalador)
    python monitor.py debug      -> monitora no terminal mostrando o que le
    python monitor.py imagem foto.png -> testa a leitura em um print
    python monitor.py conectar   -> liga o PC com e-mail e senha (alternativa)
    python monitor.py autoteste  -> confere o leitor de texto (usado no build)

As configuracoes ficam em %APPDATA%\\AlertaRoblox (config.json e alerta.log).
"""
import ctypes
import getpass
import glob
import hashlib
import json
import os
import platform
import queue
import re
import shutil
import tempfile
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
import webbrowser
from collections import OrderedDict
from difflib import SequenceMatcher


import customtkinter as ctk
import cv2
import mss
import numpy as np

# ----------------------- CONFIGURACOES ------------------------------------
# Frases procuradas na tela. Maiusculas, espacos e pontuacao nao importam.
# Use um pedaco bem caracteristico da mensagem. Pode editar/adicionar.
MENSAGENS = {
    "1": "Something feels off",
    "2": "A strange energy is felt",
}
LIMIAR_TEXTO = 0.80      # 0 a 1. Menor = tolera mais erros de leitura (e mais falsos alarmes)
INTERVALO = 1.0          # segundos entre cada verificacao
COOLDOWN = 360           # segundos minimos entre dois alertas da mesma frase (6 minutos)
SUMIU_SEG = 15           # a mensagem so "sumiu" depois de tantos segundos sem aparecer
ZOOM_OCR = 2             # aumenta a imagem antes de ler (ajuda com letras pequenas)

ALERTA_TELA = False      # True = tambem pisca a tela do PC (F8 para parar)

# --- ROBLOX ---
NOME_JOGADOR = ""        # vazio = descobre sozinho pelo log do Roblox
LINK_SERVIDOR_PRIVADO = ""   # opcional: link do seu servidor privado (vai no alerta)
MAPA = "Normal"          # mapa escolhido na janela "Jogador e servidor" (Normal ou Jungle)
CODIGO_SERVIDOR = ""     # codigo (ou link) do servidor, digitado na janela "Jogador e servidor"
MAPAS = ("Normal", "Jungle")

ATUALIZAR_SOZINHO = True # baixa e instala versoes novas sozinho
MANTER_CHAT = False      # experimental: avisa o Roblox que o mouse esta no chat, para ele nao sumir

# --- NUVEM (preenchido por quem publica o app; nao precisa mexer) ---
SUPABASE_URL = "https://vtyxkowxnesclwtndbog.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_zvhYotnIF3LIm5FzzpkjZQ_GpNsp0Bz"
FUNCAO_ALERTA = "smooth-responder"   # Edge Function que recebe os alertas
FUNCAO_DISCORD = "discord-bot"       # Edge Function do login/painel do Discord
# ---------------------------------------------------------------------------

# True quando roda pelo .exe do instalador (Nuitka define __compiled__; PyInstaller, sys.frozen)
INSTALADO = bool(getattr(sys, "frozen", False) or "__compiled__" in globals())
if INSTALADO or os.environ.get("APPDATA"):
    PASTA = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "AlertaRoblox")
else:
    PASTA = os.path.dirname(os.path.abspath(__file__))
os.makedirs(PASTA, exist_ok=True)
CONFIG = os.path.join(PASTA, "config.json")
ARQUIVO_LOG = os.path.join(PASTA, "alerta.log")
VERSAO = "dev"           # o build do GitHub troca pelo numero da versao
CODIGO = 0               # numero do build (sempre aumenta); o build troca
URL_DOWNLOADS = "https://github.com/OctavioKonzen/Alerta/releases/download/ultima/"
URL_VERSAO_PC = URL_DOWNLOADS + "versao-pc.json"
USER_AGENT = f"AlertaRoblox-PC/{VERSAO}"

# Opcoes que o usuario pode mudar no config.json ("Editar frases e opcoes")
OPCOES = {
    "mensagens": "MENSAGENS",
    "limiar_texto": "LIMIAR_TEXTO",
    "intervalo": "INTERVALO",
    "cooldown": "COOLDOWN",
    "zoom_ocr": "ZOOM_OCR",
    "alerta_tela": "ALERTA_TELA",
    "nome_jogador": "NOME_JOGADOR",
    "link_servidor_privado": "LINK_SERVIDOR_PRIVADO",
    "mapa": "MAPA",
    "codigo_servidor": "CODIGO_SERVIDOR",
    "atualizar_sozinho": "ATUALIZAR_SOZINHO",
    "manter_chat": "MANTER_CHAT",
}

try:  # evita problemas de escala (DPI) no Windows
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

try:
    cv2.setNumThreads(1)   # OpenCV com 1 nucleo so (sobra processador para o Roblox)
except Exception:
    pass

try:  # prioridade "abaixo do normal": o Windows sempre da preferencia ao Roblox
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
except Exception:
    pass


# ----------------------------- registro (log) ------------------------------
_fila_log = None          # a janela coloca uma fila aqui para mostrar as mensagens
_trava_log = threading.Lock()


def log(*partes):
    """Mostra a mensagem na janela, no terminal (se houver) e grava em alerta.log."""
    texto = " ".join(str(p) for p in partes)
    linha = f"[{time.strftime('%H:%M:%S')}] {texto}"
    if sys.stdout:
        try:
            print(linha, flush=True)
        except Exception:
            pass
    with _trava_log:
        try:
            if os.path.exists(ARQUIVO_LOG) and os.path.getsize(ARQUIVO_LOG) > 500_000:
                os.replace(ARQUIVO_LOG, ARQUIVO_LOG + ".antigo")
            with open(ARQUIVO_LOG, "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d ") + linha + "\n")
        except Exception:
            pass
    if _fila_log is not None:
        _fila_log.put(linha)


# ----------------------------- config.json ---------------------------------
def ler_config():
    if not os.path.exists(CONFIG):
        return {}
    try:
        with open(CONFIG, encoding="utf-8") as f:
            dados = json.load(f)
    except Exception:
        return {}
    if "left" in dados:          # formato antigo: so a regiao
        dados = {"regiao": dados}
    return dados


def salvar_config(**novos):
    dados = ler_config()
    dados.update(novos)
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=2, ensure_ascii=False)


def carregar_opcoes():
    """Aplica as opcoes do config.json e grava as que faltam (com o valor padrao)."""
    dados = ler_config()
    opcoes = dados.get("opcoes") if isinstance(dados.get("opcoes"), dict) else {}
    mudou = False
    for chave, var in OPCOES.items():
        if chave in opcoes:
            padrao = globals()[var]
            valor = opcoes[chave]
            if isinstance(padrao, bool):
                ok = isinstance(valor, bool)
            elif isinstance(padrao, (int, float)):
                ok = isinstance(valor, (int, float)) and not isinstance(valor, bool) and valor > 0
            else:
                ok = isinstance(valor, type(padrao))
            if ok:
                globals()[var] = valor
            else:
                log(f"Aviso: valor invalido para '{chave}' no config.json, usando o padrao.")
        else:
            opcoes[chave] = globals()[var]
            mudou = True
    # Versao 3 das opcoes: o padrao do cooldown passou de 30 (e depois 120) para 360 s (6 min).
    if dados.get("opcoes_versao", 1) < 3:
        if opcoes.get("cooldown") in (30, 120):
            opcoes["cooldown"] = 360
            globals()["COOLDOWN"] = 360
        mudou = True
        salvar_config(opcoes_versao=3)
    if mudou:
        salvar_config(opcoes=opcoes)


def editar_config():
    """Abre o config.json no Bloco de Notas e espera fechar. Devolve erro ou None."""
    carregar_opcoes()
    try:
        subprocess.run(["notepad.exe", CONFIG])
    except Exception:
        try:
            os.startfile(CONFIG)
        except Exception:
            return "Abra o arquivo em um editor de texto: " + CONFIG
    try:
        with open(CONFIG, encoding="utf-8") as f:
            json.load(f)
    except ValueError as erro:
        return ("O arquivo ficou com erro de formato (confira virgulas e aspas, "
                f"ou apague o arquivo para voltar ao padrao): {erro}")
    carregar_opcoes()
    return None


# ----------------------------- HTTP ----------------------------------------
def http(url, dados=None, headers=None, metodo=None, timeout=15):
    """Retorna (status, resposta_json_ou_texto)."""
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    corpo = None
    if dados is not None:
        corpo = json.dumps(dados).encode("utf-8")
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    req = urllib.request.Request(url, data=corpo, headers=h, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, bruto = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, bruto = e.code, e.read()
    texto = bruto.decode("utf-8", errors="ignore")
    try:
        return status, json.loads(texto)
    except ValueError:
        return status, texto


def chamar_discord(acao, com_chave=True, **extra):
    """Chama a funcao do Discord na nuvem. Devolve o dict da resposta ou lanca erro."""
    headers = {"apikey": SUPABASE_ANON_KEY}
    chave = ler_config().get("chave_pc")
    if com_chave and chave:
        headers["x-chave-pc"] = chave
    status, r = http(f"{SUPABASE_URL}/functions/v1/{FUNCAO_DISCORD}",
                     dict(extra, acao=acao), headers)
    if not isinstance(r, dict):
        raise RuntimeError(f"resposta inesperada da nuvem ({status})")
    if r.get("erro"):
        raise RuntimeError(r["erro"])
    return r


# ----------------------------- frases (na nuvem) ---------------------------
def sincronizar_frases():
    """Busca as frases da conta na nuvem (editaveis no app, no site e aqui). True = mudaram."""
    global MENSAGENS
    if not ler_config().get("chave_pc"):
        return False
    r = chamar_discord("frases")
    novas = {str(i + 1): f["texto"] for i, f in enumerate(r.get("frases") or [])}
    if novas == MENSAGENS:
        return False
    MENSAGENS = novas
    dados = ler_config()
    opcoes = dados.get("opcoes") if isinstance(dados.get("opcoes"), dict) else {}
    opcoes["mensagens"] = novas          # copia local, para funcionar mesmo sem internet
    salvar_config(opcoes=opcoes)
    return True


# ----------------------------- conectar ------------------------------------
def conectar_discord(cancelar=None):
    """Liga este PC a conta pelo Discord (abre o navegador). Devolve (ok, mensagem)."""
    ja_tem = bool(ler_config().get("chave_pc"))
    try:
        r = chamar_discord("pc_iniciar", com_chave=ja_tem, nome_pc=platform.node() or "Meu PC")
    except Exception as erro:
        return False, f"Nao consegui falar com a nuvem: {erro}"
    log("Abrindo o Discord no navegador. Autorize e volte para ca.")
    webbrowser.open(r["url"])
    limite = time.time() + 10 * 60
    while time.time() < limite:
        if cancelar is not None and cancelar.is_set():
            return False, "Cancelado."
        time.sleep(2)
        try:
            res = chamar_discord("pc_resultado", com_chave=False, estado=r["estado"])
        except Exception as erro:
            return False, str(erro)
        if not res.get("pronto"):
            continue
        if res.get("erro"):
            return False, res["erro"]
        if res.get("chave"):
            salvar_config(chave_pc=res["chave"])
        return True, "Pronto! Este PC esta ligado a sua conta."
    return False, "Tempo esgotado. Tente de novo."


def conectar_email():
    """Alternativa pelo terminal: login com e-mail e senha do app."""
    print("Entre com a MESMA conta que voce usa no app Alerta Roblox.")
    email = input("E-mail: ").strip()
    senha = getpass.getpass("Senha (nao aparece ao digitar): ")
    status, r = http(f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
                     {"email": email, "password": senha},
                     {"apikey": SUPABASE_ANON_KEY})
    if status != 200 or not isinstance(r, dict) or "access_token" not in r:
        msg = (r.get("error_description") or r.get("msg")) if isinstance(r, dict) else r
        print("Nao consegui entrar:", msg or status)
        return
    padrao = platform.node() or "Meu PC"
    nome = input(f"Nome deste PC [{padrao}]: ").strip() or padrao
    status, chave = http(f"{SUPABASE_URL}/rest/v1/rpc/criar_chave_pc",
                         {"p_nome": nome},
                         {"apikey": SUPABASE_ANON_KEY,
                          "Authorization": f"Bearer {r['access_token']}"})
    if status != 200 or not isinstance(chave, str):
        msg = chave.get("message") if isinstance(chave, dict) else chave
        print("Nao consegui criar a chave:", msg or status)
        return
    salvar_config(chave_pc=chave)
    print(f"Pronto! Este PC ('{nome}') esta ligado a sua conta.")


# ----------------------------- Roblox --------------------------------------
_cache_nomes = {}


def pastas_log_roblox():
    local = os.environ.get("LOCALAPPDATA", "")
    pastas = [os.path.join(local, "Roblox", "logs")]
    pastas += glob.glob(os.path.join(local, "Packages", "ROBLOXCORPORATION.ROBLOX_*",
                                     "LocalState", "logs"))
    return [p for p in pastas if os.path.isdir(p)]


def nome_usuario(user_id):
    if user_id in _cache_nomes:
        return _cache_nomes[user_id]
    nome = None
    try:
        status, r = http(f"https://users.roblox.com/v1/users/{user_id}", timeout=8)
        if status == 200 and isinstance(r, dict):
            nome = r.get("name")
            if r.get("displayName") and r.get("displayName") != nome:
                nome = f"{r['displayName']} (@{nome})"
    except Exception:
        pass
    _cache_nomes[user_id] = nome
    return nome


def info_roblox():
    """Le o log mais recente do Roblox: servidor (Job ID), place e jogador."""
    info = {"job_id": None, "place_id": None, "jogador": NOME_JOGADOR or None,
            "em_jogo": False, "arquivo": None}
    logs = []
    for pasta in pastas_log_roblox():
        logs += glob.glob(os.path.join(pasta, "*.log"))
    if not logs:
        return info
    arquivo = max(logs, key=os.path.getmtime)
    info["arquivo"] = arquivo
    try:
        with open(arquivo, encoding="utf-8", errors="ignore") as f:
            texto = f.read()
    except Exception:
        return info

    entradas = list(re.finditer(r"Joining game '([0-9a-fA-F-]{36})' place (\d+)", texto))
    if entradas:
        ultima = entradas[-1]
        info["job_id"], info["place_id"] = ultima.group(1), ultima.group(2)
        saidas = [m.start() for m in re.finditer(
            r"Client:Disconnect|Disconnection Notification|leaveUGCGameInternal", texto)]
        info["em_jogo"] = not saidas or saidas[-1] < ultima.start()

    if not info["jogador"]:
        ids = re.findall(r"userid:(\d+)", texto, flags=re.IGNORECASE)
        if ids:
            info["jogador"] = nome_usuario(ids[-1]) or f"userId {ids[-1]}"
    return info


def link_roblox(texto):
    """Devolve o texto se ele for um link https do Roblox; senao None."""
    t = (texto or "").strip()
    return t if re.match(r"^https://([a-z0-9-]+\.)*roblox\.com/", t, re.IGNORECASE) else None


def link_servidor(info):
    if link_roblox(CODIGO_SERVIDOR):
        return link_roblox(CODIGO_SERVIDOR)
    if LINK_SERVIDOR_PRIVADO:
        return LINK_SERVIDOR_PRIVADO
    if info["job_id"] and info["place_id"]:
        return (f"https://www.roblox.com/games/start?placeId={info['place_id']}"
                f"&gameInstanceId={info['job_id']}")
    return None


def mostrar_servidor():
    info = info_roblox()
    if not info["arquivo"]:
        log("Nao achei os logs do Roblox. Abra o jogo e tente de novo.")
        return
    log("Jogador:", info["jogador"] or "(nao detectado - preencha nome_jogador nas opcoes)")
    log("Servidor:", info["job_id"] or "(nao detectado)",
        "| Place:", info["place_id"] or "?", "| Em jogo:", "sim" if info["em_jogo"] else "nao")


# ----------------------------- envio ---------------------------------------
def enviar_alerta(frase, mensagem, teste=False, esperar=False):
    """Manda o alerta para a nuvem, que avisa os celulares e o Discord da sua conta."""
    chave = ler_config().get("chave_pc")
    if not chave:
        log("Este PC ainda nao esta conectado. Clique em 'Conectar com Discord'.")
        return

    def _enviar():
        info = info_roblox()
        dados = {"frase": frase, "mensagem": mensagem, "jogador": info["jogador"],
                 "job_id": info["job_id"], "place_id": info["place_id"],
                 "link": link_servidor(info), "teste": teste,
                 "mapa": MAPA if MAPA in MAPAS else None,
                 "codigo_servidor": CODIGO_SERVIDOR.strip() or None}
        for _tentativa in range(3):
            try:
                status, r = http(f"{SUPABASE_URL}/functions/v1/{FUNCAO_ALERTA}", dados,
                                 {"x-chave-pc": chave, "apikey": SUPABASE_ANON_KEY})
            except Exception as erro:
                log("Falha de conexao:", erro)
                time.sleep(2)
                continue
            if status == 200 and isinstance(r, dict) and r.get("repetido"):
                log("Alerta repetido (ja avisado ha menos de 6 min): a nuvem ignorou a copia.")
            elif status == 200:
                env = r.get("enviados", 0) if isinstance(r, dict) else 0
                aviso = r.get("aviso", "") if isinstance(r, dict) else ""
                disc = r.get("discord", 0) if isinstance(r, dict) else 0
                extra = f", {disc} canal(is) do Discord" if disc else ""
                log(f"Alerta enviado ({env} celular(es){extra}). {aviso}".strip())
            elif status == 401:
                log("Chave do PC invalida (PC removido no app?). Conecte de novo.")
            elif status == 429:
                log("Muitos alertas seguidos; a nuvem pediu para esperar.")
            else:
                log("Erro ao enviar:", status, r)
                time.sleep(2)
                continue
            return

    t = threading.Thread(target=_enviar, daemon=True)
    t.start()
    if esperar:
        t.join()


# ----------------------------- tela / OCR ----------------------------------
def capturar(sct, regiao):
    img = np.array(sct.grab(regiao))
    return np.ascontiguousarray(img[:, :, :3])  # BGRA -> BGR


def selecionar_area(pai, ao_terminar):
    """Tela escura por cima de tudo: arraste um retangulo. Chama ao_terminar(regiao|None)."""
    janela = tk.Toplevel(pai)
    janela.attributes("-fullscreen", True)
    janela.attributes("-topmost", True)
    janela.attributes("-alpha", 0.30)
    janela.configure(bg="black", cursor="crosshair")
    canvas = tk.Canvas(janela, bg="black", highlightthickness=0, cursor="crosshair")
    canvas.pack(fill="both", expand=True)
    canvas.create_text(
        janela.winfo_screenwidth() // 2, 40, fill="white", font=("Arial", 22, "bold"),
        text="Arraste o mouse sobre a area das mensagens  (ESC cancela)")
    estado = {"x0": 0, "y0": 0, "ret": None, "fim": False}

    def terminar(regiao):
        if estado["fim"]:
            return
        estado["fim"] = True
        janela.destroy()
        ao_terminar(regiao)

    def apertou(e):
        estado["x0"], estado["y0"] = e.x_root, e.y_root
        estado["cx0"], estado["cy0"] = e.x, e.y
        if estado["ret"]:
            canvas.delete(estado["ret"])
        estado["ret"] = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="red", width=3)

    def arrastou(e):
        if estado["ret"]:
            canvas.coords(estado["ret"], estado["cx0"], estado["cy0"], e.x, e.y)

    def soltou(e):
        x0, y0, x1, y1 = estado["x0"], estado["y0"], e.x_root, e.y_root
        w, h = abs(x1 - x0), abs(y1 - y0)
        terminar({"left": min(x0, x1), "top": min(y0, y1), "width": w, "height": h}
                 if w > 5 and h > 5 else None)

    canvas.bind("<ButtonPress-1>", apertou)
    canvas.bind("<B1-Motion>", arrastou)
    canvas.bind("<ButtonRelease-1>", soltou)
    janela.bind("<Escape>", lambda e: terminar(None))
    janela.deiconify()
    janela.lift()
    janela.focus_force()
    try:
        janela.grab_set()      # todos os cliques vao para a selecao
    except Exception:
        pass


_leitor = None
_trava_leitor = threading.Lock()

LIMITE_TEXTO = 150   # pixel mais claro que isso conta como "letra" (o fundo do chat e escuro)


def mascara_texto(gray):
    """So as letras (pixels claros); o cenario escuro atras do chat some."""
    return (gray > LIMITE_TEXTO).astype(np.uint8)


class LeitorComMemoria:
    """Acha as linhas de texto e so le (reconhece) as que ainda nao conhece."""

    def __init__(self, motor, tamanho=600):
        self.motor = motor
        self.memoria = OrderedDict()
        self.tamanho = tamanho

    @staticmethod
    def assinatura(recorte_gray):
        """Impressao digital da linha: so as letras, recortadas e reduzidas (tolera 1-2 px de diferenca)."""
        m = mascara_texto(recorte_gray)
        ys, xs = np.nonzero(m)
        if len(xs) < 8:
            return None
        m = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        h, w = m.shape
        alvo_h = 10
        alvo_w = max(4, min(400, round(w * alvo_h / max(h, 1))))
        peq = cv2.resize(m * 255, (alvo_w, alvo_h), interpolation=cv2.INTER_AREA) > 96
        return hashlib.blake2b(np.packbits(peq).tobytes() + bytes([alvo_w % 256, alvo_w // 256]),
                               digest_size=12).digest()

    def ler(self, gray):
        img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        caixas = self.motor(img, use_cls=False, use_rec=False)[0] or []
        caixas = sorted(caixas, key=lambda c: (min(p[1] for p in c), min(p[0] for p in c)))
        linhas = []
        H, W = gray.shape
        for c in caixas:
            pts = np.array(c)
            x0, y0 = np.floor(pts.min(axis=0)).astype(int)
            x1, y1 = np.ceil(pts.max(axis=0)).astype(int)
            x0, y0 = max(0, x0 - 2), max(0, y0 - 2)
            x1, y1 = min(W, x1 + 2), min(H, y1 + 2)
            if x1 - x0 < 6 or y1 - y0 < 6:
                continue
            chave = self.assinatura(gray[y0:y1, x0:x1])
            if chave is not None and chave in self.memoria:
                self.memoria.move_to_end(chave)
                linhas.append(self.memoria[chave])
                continue
            res = self.motor(img[y0:y1, x0:x1], use_det=False, use_cls=False)[0] or []
            texto = " ".join(str(r[0]) for r in res if r and r[0]).strip()
            if chave is not None:
                self.memoria[chave] = texto
                if len(self.memoria) > self.tamanho:
                    self.memoria.popitem(last=False)
            if texto:
                linhas.append(texto)
        return "\n".join(linhas)


def criar_leitor():
    """Escolhe o leitor de texto disponivel: RapidOCR ou Tesseract (so cria uma vez)."""
    with _trava_leitor:
        return _criar_leitor()


def _criar_leitor():
    global _leitor
    if _leitor:
        return _leitor
    for modulo in ("rapidocr_onnxruntime", "rapidocr"):
        try:
            # 1 nucleo so: o padrao usa todos e deixa o Roblox lento
            motor = __import__(modulo).RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
        except Exception:
            try:
                motor = __import__(modulo).RapidOCR()
            except Exception:
                continue

        def ler_inteiro(gray, motor=motor):
            img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            try:
                res = motor(img, use_cls=False)   # chat e texto reto: sem detector de inclinacao
            except TypeError:
                res = motor(img)
            if isinstance(res, tuple):            # versao antiga: (lista, tempo)
                itens = res[0] or []
                return "\n".join(str(item[1]) for item in itens)
            txts = getattr(res, "txts", None)     # versao nova
            return "\n".join(txts) if txts else ""

        rapido = LeitorComMemoria(motor)

        def ler_rapid(gray):
            # Le linha por linha e lembra das linhas ja lidas: quando o chat rola,
            # so a linha nova e lida (o resto vem da memoria). Se der erro, le tudo.
            try:
                return rapido.ler(gray)
            except Exception:
                return ler_inteiro(gray)

        _leitor = ("RapidOCR", ler_rapid)
        return _leitor

    exe = shutil.which("tesseract")
    if not exe:
        for p in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                  r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
            if os.path.exists(p):
                exe = p
                break
    if exe:
        flags = 0x08000000 if os.name == "nt" else 0   # nao abrir janela preta

        def ler_tess(gray):
            ok, png = cv2.imencode(".png", gray)
            r = subprocess.run([exe, "stdin", "stdout", "--psm", "6"],
                               input=png.tobytes(), capture_output=True,
                               creationflags=flags)
            return r.stdout.decode("utf-8", errors="ignore")

        _leitor = ("Tesseract", ler_tess)
        return _leitor
    return None, None


def preparar(frame):
    """Brilho maximo dos canais (realca texto colorido) + zoom."""
    gray = frame.max(axis=2)
    return cv2.resize(gray, None, fx=ZOOM_OCR, fy=ZOOM_OCR,
                      interpolation=cv2.INTER_CUBIC)


def normalizar(texto):
    return re.sub(r"[^a-z0-9]", "", texto.lower())


def similaridade(chave, texto):
    """0 a 1: o quanto a frase aparece (mesmo com erros de leitura) no texto."""
    if not chave or not texto:
        return 0.0
    if chave in texto:
        return 1.0
    n = len(chave)
    if len(texto) < n:
        return SequenceMatcher(None, chave, texto).ratio()
    melhor = 0.0
    for i in range(len(texto) - n + 1):
        r = SequenceMatcher(None, chave, texto[i:i + n]).ratio()
        if r > melhor:
            melhor = r
    return melhor


def linha_da_mensagem(texto, chave):
    """Devolve a linha lida que contem a frase (o texto que apareceu no jogo)."""
    melhor, nota_melhor = None, 0.0
    for linha in texto.splitlines():
        nota = similaridade(chave, normalizar(linha))
        if nota > nota_melhor:
            melhor, nota_melhor = linha.strip(), nota
    if melhor and nota_melhor >= LIMIAR_TEXTO:
        return melhor
    return " ".join(texto.split())[:300]


# ----------------------------- alerta na tela ------------------------------
def som(parar):
    try:
        import winsound
        while not parar.is_set():
            winsound.Beep(1200, 250)
            winsound.Beep(800, 250)
    except ImportError:
        pass


def f8_apertado():
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(0x77) & 0x8000)
    except Exception:
        return False


def alerta_tela(pai, nome):
    """Pisca a tela inteira ate voce apertar F8."""
    parar = threading.Event()
    threading.Thread(target=som, args=(parar,), daemon=True).start()
    janela = tk.Toplevel(pai)
    janela.attributes("-fullscreen", True)
    janela.attributes("-topmost", True)
    janela.attributes("-alpha", 0.45)
    janela.configure(bg="red")
    label = tk.Label(janela, text=f"ALERTA!\nMensagem {nome}\n\nAperte F8 para parar",
                     font=("Arial", 44, "bold"), fg="white", bg="red")
    label.pack(expand=True)
    estado = {"vermelho": True, "fechado": False}

    try:  # deixa os cliques passarem para o jogo (Windows)
        janela.update()
        hwnd = ctypes.windll.user32.GetParent(janela.winfo_id())
        estilo = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
        ctypes.windll.user32.SetWindowLongW(hwnd, -20, estilo | 0x80000 | 0x20)
    except Exception:
        pass

    def fechar(e=None):
        if estado["fechado"]:
            return
        estado["fechado"] = True
        parar.set()
        janela.destroy()

    def piscar():
        if estado["fechado"]:
            return
        estado["vermelho"] = not estado["vermelho"]
        cor = "red" if estado["vermelho"] else "yellow"
        janela.configure(bg=cor)
        label.configure(bg=cor, fg="white" if estado["vermelho"] else "black")
        janela.after(250, piscar)

    def verificar_f8():
        if estado["fechado"]:
            return
        if f8_apertado():
            fechar()
            return
        janela.after(30, verificar_f8)

    janela.bind("<F8>", fechar)
    piscar()
    verificar_f8()


# ----------------------------- monitor -------------------------------------
class _PONTO(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _ULTIMA_ENTRADA(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


_meu_ultimo_toque = {"tick": 0}


def manter_chat_aberto(regiao):
    """Experimental: o Roblox so mantem o chat visivel com o MOUSE DE VERDADE em cima dele.
    Quando voce esta parado (15 s sem mexer no mouse/teclado) e o Roblox esta na frente,
    leva o cursor ate o chat, da um mexidinho e devolve para onde estava (menos de 0,1 s)."""
    try:
        u = ctypes.windll.user32
        k = ctypes.windll.kernel32
    except Exception:
        return False
    try:
        hwnd = u.FindWindowW(None, "Roblox")
        if not hwnd or u.IsIconic(hwnd) or u.GetForegroundWindow() != hwnd:
            return False                      # so com o Roblox na frente
        ult = _ULTIMA_ENTRADA(ctypes.sizeof(_ULTIMA_ENTRADA), 0)
        if not u.GetLastInputInfo(ctypes.byref(ult)):
            return False
        agora = k.GetTickCount() & 0xFFFFFFFF
        # a ultima "entrada" pode ter sido o nosso proprio toque: isso nao conta como voce mexendo
        ultima_sua = ult.dwTime if ult.dwTime > _meu_ultimo_toque["tick"] + 500 else 0
        if ultima_sua and (agora - ultima_sua) & 0xFFFFFFFF < 15000:
            return False                      # voce esta jogando: nao mexe
        real = _PONTO()
        u.GetCursorPos(ctypes.byref(real))
        cx = regiao["left"] + regiao["width"] // 2
        cy = regiao["top"] + regiao["height"] // 2
        u.SetCursorPos(int(cx), int(cy))
        time.sleep(0.03)
        u.SetCursorPos(int(cx) + 3, int(cy))
        time.sleep(0.03)
        u.SetCursorPos(int(cx), int(cy))
        time.sleep(0.02)
        u.SetCursorPos(real.x, real.y)        # volta para onde estava
        _meu_ultimo_toque["tick"] = k.GetTickCount() & 0xFFFFFFFF
        return True
    except Exception:
        return False


def roblox_aberto():
    """True se a janela do Roblox existe e nao esta minimizada (fora do Windows: sempre True)."""
    try:
        u = ctypes.windll.user32
    except Exception:
        return True
    try:
        hwnd = u.FindWindowW(None, "Roblox")
        return bool(hwnd) and not u.IsIconic(hwnd)
    except Exception:
        return True


def prioridade_baixa_nesta_thread():
    try:
        k = ctypes.windll.kernel32
        k.SetThreadPriority(k.GetCurrentThread(), -2)   # THREAD_PRIORITY_LOWEST
    except Exception:
        pass


# Quando cada frase foi avisada pela ultima vez (sobrevive aos reinicios do monitor).
_ultimos_alertas = {}

class Monitor:
    """Le a tela em segundo plano e manda os alertas."""

    def __init__(self, ao_detectar=None):
        self.ao_detectar = ao_detectar   # chamado com o nome da mensagem (alerta na tela)
        self.debug = False
        self.status = "Iniciando..."
        self._parar = threading.Event()
        self._thread = None

    def iniciar(self):
        self._parar = threading.Event()
        self._thread = threading.Thread(target=self._rodar, args=(self._parar,), daemon=True)
        self._thread.start()

    def parar(self):
        self._parar.set()

    def reiniciar(self):
        self.parar()
        self.iniciar()

    def _esperar_requisitos(self, parar):
        """Espera ter chave, area e leitor. Devolve (regiao, ler) ou None se parou."""
        while not parar.is_set():
            cfg = ler_config()
            if not cfg.get("chave_pc"):
                self.status = "Parado: conecte com o Discord"
            elif not cfg.get("regiao"):
                self.status = "Parado: escolha a área da tela"
            elif not MENSAGENS:
                self.status = "Parado: nenhuma frase cadastrada"
            else:
                self.status = "Preparando o leitor de texto..."
                nome_leitor, ler = criar_leitor()
                if ler is None:
                    self.status = "Erro: leitor de texto não encontrado"
                    log("Nenhum leitor de texto encontrado. Reinstale o Alerta Roblox.")
                    return None
                log("Leitor de texto:", nome_leitor)
                return cfg["regiao"], ler
            parar.wait(2)
        return None

    def _rodar(self, parar):
        prontos = self._esperar_requisitos(parar)
        if not prontos:
            return
        regiao, ler = prontos
        info = info_roblox()
        log("Jogador:", info["jogador"] or "?", "| Servidor:", info["job_id"] or "?")

        chaves = {n: normalizar(t) for n, t in MENSAGENS.items()}
        agora0 = time.time()
        # Se ja avisou desta frase ha pouco (mesmo antes de reiniciar), conta como "ja visivel".
        visivel = {n: agora0 - _ultimos_alertas.get(c, 0.0) < COOLDOWN for n, c in chaves.items()}
        visto_em = {n: agora0 for n in chaves}   # ultima vez que a frase apareceu na tela
        self.status = "Monitorando"
        log("Monitorando a area escolhida.")

        prioridade_baixa_nesta_thread()
        ultimo_toque_chat = 0.0
        anterior, texto_anterior, pulos = None, "", 0
        notas_cache, texto_cache = {}, None
        espera = INTERVALO
        pausado = False
        with mss.mss() as sct:
            while not parar.is_set():
                # Sem Roblox aberto (ou minimizado) nao ha o que ler: nao gasta nada.
                if not roblox_aberto():
                    if not pausado:
                        pausado = True
                        self.status = "Esperando o Roblox abrir"
                        log("Roblox fechado ou minimizado: monitoramento em pausa.")
                    anterior = None
                    parar.wait(3)
                    continue
                if pausado:
                    pausado = False
                    self.status = "Monitorando"
                    log("Roblox aberto: monitorando de novo.")
                espera = INTERVALO
                try:
                    quadro = capturar(sct, regiao)
                    # Miniatura para comparar: se a tela nao mudou, nao precisa ler de novo
                    # (o leitor de texto e a parte pesada; o chat fica parado quase sempre).
                    # So as letras contam: o cenario do jogo se mexendo atras do chat nao dispara leitura.
                    mini = cv2.resize(mascara_texto(quadro.max(axis=2)) * 255, None, fx=0.25, fy=0.25,
                                      interpolation=cv2.INTER_AREA).astype(np.int16)
                    igual = (anterior is not None and anterior.shape == mini.shape
                             and float(np.abs(mini - anterior).mean()) < 2.0 and pulos < 30)
                    if igual:
                        texto, pulos = texto_anterior, pulos + 1
                    else:
                        inicio = time.perf_counter()
                        texto = ler(preparar(quadro))
                        gasto = time.perf_counter() - inicio
                        anterior, texto_anterior, pulos = mini, texto, 0
                        # Limite de uso: o leitor ocupa no maximo ~1/3 do tempo de um nucleo.
                        espera = max(INTERVALO, gasto * 2)
                except Exception as erro:          # falha passageira: tenta de novo
                    log("Erro na leitura (tentando de novo):", erro)
                    parar.wait(INTERVALO)
                    continue
                if parar.is_set():
                    break
                if self.debug and texto is not texto_cache:
                    log("leu:", texto.replace("\n", " | ")[:300] or "(nada)")
                if texto is not texto_cache:     # so recalcula as notas quando o texto mudou
                    norm = normalizar(texto)
                    notas_cache = {n: similaridade(c, norm) for n, c in chaves.items()}
                    texto_cache = texto
                agora = time.time()
                for nome, chave in chaves.items():
                    nota = notas_cache[nome]
                    if self.debug and nota > 0.3:
                        log(f"  mensagem {nome}: nota {nota:.2f}")
                    if nota >= LIMIAR_TEXTO:
                        visto_em[nome] = agora
                        if not visivel[nome] and agora - _ultimos_alertas.get(chave, 0.0) > COOLDOWN:
                            visivel[nome] = True
                            _ultimos_alertas[chave] = agora
                            linha = linha_da_mensagem(texto, chave)
                            log(f"Detectado: {linha} ({nota:.2f})")
                            enviar_alerta(MENSAGENS[nome], linha)
                            if ALERTA_TELA and self.ao_detectar:
                                self.ao_detectar(nome)
                    elif agora - visto_em[nome] >= SUMIU_SEG:
                        visivel[nome] = False   # sumiu de vez: pode alertar de novo (depois do cooldown)
                if MANTER_CHAT and time.time() - ultimo_toque_chat >= 8:
                    ultimo_toque_chat = time.time()
                    manter_chat_aberto(regiao)
                parar.wait(espera)


# ----------------------------- atualizacao automatica ----------------------
def procurar_atualizacao():
    """Devolve as informacoes da versao nova (dict) ou None."""
    if VERSAO == "dev" or CODIGO <= 0:
        return None
    status, r = http(f"{URL_VERSAO_PC}?t={int(time.time())}", timeout=10)
    if status != 200 or not isinstance(r, dict):
        return None
    url = str(r.get("url", ""))
    if not url.startswith(URL_DOWNLOADS):
        return None
    try:
        if int(r.get("codigo", 0)) <= CODIGO:
            return None
    except (TypeError, ValueError):
        return None
    return r


def baixar_instalador(info):
    """Baixa o instalador novo para a pasta temporaria. Devolve o caminho."""
    destino = os.path.join(tempfile.gettempdir(), f"AlertaRoblox-Setup-{info['versao']}.exe")
    parcial = destino + ".parcial"
    req = urllib.request.Request(info["url"], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp, open(parcial, "wb") as f:
        shutil.copyfileobj(resp, f, 1024 * 1024)
    if os.path.getsize(parcial) < 5 * 1024 * 1024:
        os.remove(parcial)
        raise RuntimeError("arquivo baixado muito pequeno")
    os.replace(parcial, destino)
    return destino


# ----------------------------- janela --------------------------------------
# Interface moderna (CustomTkinter), com as cores do app do celular.
COR = {
    "fundo": "#0f1115", "cartao": "#1a1d24", "borda": "#2a2f3a", "texto": "#f2f4f8",
    "fraco": "#8b93a3", "destaque": "#E53935", "destaque2": "#c62828",
    "ok": "#43A047", "atencao": "#F9A825", "sec": "#262a33", "sec2": "#323743",
}
FONTE = "Segoe UI"


def caminho_recurso(nome):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    for p in (os.path.join(base, nome), os.path.join(base, "instalador", nome)):
        if os.path.exists(p):
            return p
    return None


def imagem_icone():
    from PIL import Image, ImageDraw
    ico = caminho_recurso("icone.ico")
    if ico:
        try:
            return Image.open(ico)
        except Exception:
            pass
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=(229, 57, 53, 255))
    d.rectangle((28, 14, 36, 40), fill="white")
    d.rectangle((28, 46, 36, 52), fill="white")
    return img


def fonte(tamanho=13, peso="normal"):
    return ctk.CTkFont(family=FONTE, size=tamanho, weight=peso)


def botao(pai, texto, comando, tipo="sec", **kw):
    cores = {
        "pri": (COR["destaque"], COR["destaque2"], "#ffffff"),
        "sec": (COR["sec"], COR["sec2"], COR["texto"]),
        "perigo": (COR["sec"], "#3a2226", "#ff6b6b"),
    }[tipo]
    return ctk.CTkButton(pai, text=texto, command=comando, fg_color=cores[0], hover_color=cores[1],
                         text_color=cores[2], corner_radius=10, height=kw.pop("height", 38),
                         font=fonte(13, "bold"), **kw)


def cartao(pai, **kw):
    return ctk.CTkFrame(pai, fg_color=COR["cartao"], corner_radius=14,
                        border_width=1, border_color=COR["borda"], **kw)


def trazer_para_frente(janela):
    """CTkToplevel as vezes abre atras da janela principal no Windows."""
    def _f():
        try:
            janela.deiconify()
            janela.lift()
            janela.focus_force()
            janela.attributes("-topmost", True)
            janela.after(300, lambda: janela.attributes("-topmost", False))
        except Exception:
            pass
    janela.after(150, _f)


def dialogo(pai, titulo, texto, botoes=("OK",), tipo="info"):
    """Janelinha de aviso no mesmo estilo. Devolve o texto do botao clicado (ou None)."""
    win = ctk.CTkToplevel(pai)
    win.title(titulo)
    win.configure(fg_color=COR["fundo"])
    win.resizable(False, False)
    resultado = {"v": None}
    cor = {"info": COR["ok"], "aviso": COR["atencao"], "erro": COR["destaque"]}[tipo]
    simbolo = {"info": "✓", "aviso": "!", "erro": "✕"}[tipo]
    linha = ctk.CTkFrame(win, fg_color="transparent")
    linha.pack(padx=22, pady=(22, 10), fill="x")
    ctk.CTkLabel(linha, text=simbolo, width=36, height=36, corner_radius=18, fg_color=cor,
                 text_color="#ffffff", font=fonte(16, "bold")).pack(side="left", anchor="n")
    ctk.CTkLabel(linha, text=texto, wraplength=330, justify="left", text_color=COR["texto"],
                 font=fonte(13)).pack(side="left", padx=(14, 0))
    fila = ctk.CTkFrame(win, fg_color="transparent")
    fila.pack(padx=22, pady=(6, 20), fill="x")
    for i, b in enumerate(reversed(botoes)):
        def clicar(b=b):
            resultado["v"] = b
            win.destroy()
        botao(fila, b, clicar, "pri" if i == 0 else "sec", width=110).pack(side="right", padx=(8, 0))
    win.transient(pai)
    trazer_para_frente(win)
    win.after(200, win.grab_set)
    pai.wait_window(win)
    return resultado["v"]


class App:
    def __init__(self):
        global _fila_log
        _fila_log = queue.Queue()
        self.acoes = queue.Queue()      # funcoes para rodar na janela (vindas de outras threads)
        ctk.set_appearance_mode("dark")
        self.root = ctk.CTk(fg_color=COR["fundo"])
        self.root.title("Alerta Roblox")
        self.root.geometry("760x620")
        self.root.minsize(640, 560)
        ico = caminho_recurso("icone.ico")
        if ico:
            try:
                self.root.iconbitmap(ico)
            except Exception:
                pass
        self.icone_bandeja = None
        self.root.report_callback_exception = self._erro_na_janela
        self.monitor = Monitor(ao_detectar=lambda nome: self.na_janela(alerta_tela, self.root, nome))
        self.ocupado = False
        self._montar()
        self.root.protocol("WM_DELETE_WINDOW", self.esconder)
        self._iniciar_bandeja()
        self.monitor.iniciar()
        self.root.after(200, self._processar_filas)
        self.root.after(300, self._atualizar_status)
        self.root.after(15_000, self._verificar_atualizacao)
        self.root.after(2_000, self._sincronizar_periodico)
        log("Alerta Roblox aberto.")

    # --- montagem da janela ---
    def _montar(self):
        r = self.root
        r.grid_columnconfigure(0, weight=1)
        r.grid_rowconfigure(3, weight=1)

        # Cabecalho: nome + situacao
        topo = ctk.CTkFrame(r, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew", padx=22, pady=(20, 6))
        topo.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(topo, text="●", text_color=COR["destaque"], font=fonte(26, "bold")).grid(row=0, column=0, rowspan=2, padx=(0, 10))
        ctk.CTkLabel(topo, text="Alerta Roblox", text_color=COR["texto"], font=fonte(22, "bold")).grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(topo, text="Avisa no celular e no Discord quando a mensagem aparecer no jogo",
                     text_color=COR["fraco"], font=fonte(12)).grid(row=1, column=1, sticky="w")
        self.pilula = ctk.CTkLabel(topo, text="", corner_radius=12, height=28, font=fonte(12, "bold"),
                                   text_color="#ffffff", fg_color=COR["sec"])
        self.pilula.grid(row=0, column=2, rowspan=2, sticky="e", ipadx=10)

        # Tres passos
        passos = ctk.CTkFrame(r, fg_color="transparent")
        passos.grid(row=1, column=0, sticky="ew", padx=16, pady=(10, 4))
        for i in range(3):
            passos.grid_columnconfigure(i, weight=1, uniform="p")
        self.passo_conta = self._passo(passos, 0, "1", "Conta", "Conectar com Discord", self.conectar)
        self.passo_area = self._passo(passos, 1, "2", "Área da tela", "Escolher área", self.escolher_area)
        self.passo_discord = self._passo(passos, 2, "3", "Canal do Discord", "Abrir painel", self.abrir_painel_discord)

        # Acoes rapidas
        acoes = ctk.CTkFrame(r, fg_color="transparent")
        acoes.grid(row=2, column=0, sticky="ew", padx=22, pady=(8, 4))
        botao(acoes, "Enviar teste", self.enviar_teste, "pri", width=140).pack(side="left")
        botao(acoes, "Frases", self.abrir_frases, width=110).pack(side="left", padx=8)
        botao(acoes, "Jogador e servidor", self.abrir_jogador, width=160).pack(side="left")
        self.chave_debug = ctk.CTkSwitch(acoes, text="Ver leitura", font=fonte(12), text_color=COR["fraco"],
                                         progress_color=COR["destaque"], command=self._trocar_debug)
        self.chave_debug.pack(side="right")
        # dentro do cartao "Area da tela": segura o chat do Roblox aberto (experimental)
        self.chave_chat = ctk.CTkSwitch(self.passo_area["cartao"], text="Manter o chat aberto", font=fonte(12),
                                        text_color=COR["fraco"], progress_color=COR["destaque"],
                                        command=self._trocar_manter_chat)
        if MANTER_CHAT:
            self.chave_chat.select()
        self.chave_chat.pack(anchor="w", padx=14, pady=(0, 12))

        # Registro
        caixa = cartao(r)
        caixa.grid(row=3, column=0, sticky="nsew", padx=22, pady=(10, 6))
        caixa.grid_columnconfigure(0, weight=1)
        caixa.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(caixa, text="Atividade", text_color=COR["fraco"], font=fonte(12, "bold")).grid(
            row=0, column=0, sticky="w", padx=14, pady=(10, 0))
        self.txt = ctk.CTkTextbox(caixa, fg_color=COR["fundo"], text_color=COR["texto"], corner_radius=10,
                                  font=ctk.CTkFont(family="Consolas", size=12), wrap="word",
                                  border_width=0)
        self.txt.grid(row=1, column=0, sticky="nsew", padx=10, pady=(6, 10))
        self.txt.configure(state="disabled")

        rodape = ctk.CTkFrame(r, fg_color="transparent")
        rodape.grid(row=4, column=0, sticky="ew", padx=24, pady=(0, 14))
        rodape.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(rodape, text="Fechar a janela não para o alerta: ele continua no ícone perto do relógio. "
                                  "Para sair, clique com o botão direito no ícone › Sair.",
                     text_color=COR["fraco"], font=fonte(11), wraplength=560, justify="left").grid(
            row=0, column=0, sticky="w")
        self.lbl_versao = ctk.CTkLabel(rodape, text=f"Versão {VERSAO}", text_color=COR["fraco"], font=fonte(11))
        self.lbl_versao.grid(row=0, column=1, padx=(10, 8))
        self.btn_atualizar = botao(rodape, "Atualizar", lambda: self.verificar_atualizacao(manual=True),
                                   width=90, height=28)
        self.btn_atualizar.grid(row=0, column=2)

    def _passo(self, pai, col, numero, titulo, texto_botao, comando):
        c = cartao(pai)
        c.grid(row=0, column=col, sticky="nsew", padx=6)
        topo = ctk.CTkFrame(c, fg_color="transparent")
        topo.pack(fill="x", padx=14, pady=(14, 2))
        num = ctk.CTkLabel(topo, text=numero, width=26, height=26, corner_radius=13, fg_color=COR["sec2"],
                           text_color=COR["texto"], font=fonte(12, "bold"))
        num.pack(side="left")
        ctk.CTkLabel(topo, text=titulo, text_color=COR["texto"], font=fonte(14, "bold")).pack(side="left", padx=8)
        estado = ctk.CTkLabel(c, text="...", text_color=COR["fraco"], font=fonte(12), anchor="w")
        estado.pack(fill="x", padx=14, pady=(2, 10))
        b = botao(c, texto_botao, comando, height=34)
        b.pack(fill="x", padx=14, pady=(0, 14))
        return {"num": num, "numero": numero, "estado": estado, "botao": b, "cartao": c}

    def _erro_na_janela(self, tipo, valor, tb):
        """Qualquer erro dentro da janela aparece no quadro Atividade (e no alerta.log)."""
        import traceback
        detalhe = "".join(traceback.format_exception(tipo, valor, tb))
        log("ERRO na janela:", detalhe.strip().splitlines()[-1])
        log(detalhe[-1500:].replace("\n", " | "))
        try:
            self.mostrar()
        except Exception:
            pass

    def _mudar(self, widget, chave, **opcoes):
        """So reconfigura o widget se algo mudou (evita redesenhar a cada segundo)."""
        cache = self.__dict__.setdefault("_cache_widgets", {})
        if cache.get(chave) != opcoes:
            cache[chave] = opcoes
            widget.configure(**opcoes)

    def _marcar(self, passo, feito, texto):
        chave = id(passo)
        if self.__dict__.setdefault("_cache_passos", {}).get(chave) == (feito, texto):
            return
        self._cache_passos[chave] = (feito, texto)
        passo["num"].configure(text="✓" if feito else passo["numero"],
                               fg_color=COR["ok"] if feito else COR["sec2"])
        passo["estado"].configure(text=texto, text_color=COR["ok"] if feito else COR["fraco"])

    def _trocar_manter_chat(self):
        global MANTER_CHAT
        MANTER_CHAT = bool(self.chave_chat.get())
        dados = ler_config()
        opcoes = dados.get("opcoes") if isinstance(dados.get("opcoes"), dict) else {}
        opcoes["manter_chat"] = MANTER_CHAT
        salvar_config(opcoes=opcoes)
        log("Manter o chat aberto:", "ligado (quando voce fica 15 s parado com o Roblox na frente, "
            "o mouse vai ate o chat e volta a cada 8 s)" if MANTER_CHAT else "desligado")

    def _trocar_debug(self):
        self.monitor.debug = bool(self.chave_debug.get())

    # --- utilidades ---
    def na_janela(self, funcao, *args):
        """Pede para rodar funcao(*args) na thread da janela."""
        self.acoes.put(lambda: funcao(*args))

    def em_segundo_plano(self, funcao, ao_terminar=None):
        """Roda funcao() numa thread; ao_terminar(resultado, erro) roda na janela."""
        def rodar():
            try:
                res, erro = funcao(), None
            except Exception as e:
                res, erro = None, e
            if ao_terminar:
                self.na_janela(ao_terminar, res, erro)
        threading.Thread(target=rodar, daemon=True).start()

    def _processar_filas(self):
        linhas = []
        while not _fila_log.empty():
            linhas.append(_fila_log.get_nowait())
        if linhas:
            self.txt.configure(state="normal")
            self.txt.insert("end", "\n".join(linhas) + "\n")
            if int(self.txt.index("end-1c").split(".")[0]) > 500:
                self.txt.delete("1.0", "100.0")
            self.txt.see("end")
            self.txt.configure(state="disabled")
        while not self.acoes.empty():
            try:
                self.acoes.get_nowait()()
            except Exception as erro:
                log("Erro:", erro)
        self.root.after(200, self._processar_filas)

    def _atualizar_status(self):
        try:
            mtime = os.path.getmtime(CONFIG)
        except OSError:
            mtime = None
        if mtime != getattr(self, "_cfg_mtime", -1):
            self._cfg_mtime, self._cfg = mtime, ler_config()
        cfg = self._cfg
        conectado = bool(cfg.get("chave_pc"))
        self._marcar(self.passo_conta, conectado, "Conectada" if conectado else "Não conectada")
        if not self.ocupado:
            self._mudar(self.passo_conta["botao"], "b_conta",
                        text="Conectar de novo" if conectado else "Conectar com Discord")
        tem_area = bool(cfg.get("regiao"))
        self._marcar(self.passo_area, tem_area, "Escolhida" if tem_area else "Não escolhida")
        self._mudar(self.passo_area["botao"], "b_area", text="Trocar área" if tem_area else "Escolher área")
        canal = cfg.get("canal_discord")
        self._marcar(self.passo_discord, bool(canal), canal or "Opcional")
        st = self.monitor.status
        cor = COR["ok"] if st == "Monitorando" else (COR["destaque"] if st.startswith("Erro") else COR["atencao"])
        self._mudar(self.pilula, "pilula", text=("● " + st) if st == "Monitorando" else st, fg_color=cor)
        if self.icone_bandeja is not None:
            try:
                self.icone_bandeja.title = "Alerta Roblox - " + st
            except Exception:
                pass
        self.root.after(1000, self._atualizar_status)

    # --- bandeja (icone perto do relogio) ---
    def _iniciar_bandeja(self):
        try:
            import pystray
        except Exception:
            self.root.protocol("WM_DELETE_WINDOW", self.sair)
            return
        menu = pystray.Menu(
            pystray.MenuItem("Abrir", lambda: self.na_janela(self.mostrar), default=True),
            pystray.MenuItem("Enviar teste", lambda: self.na_janela(self.enviar_teste)),
            pystray.MenuItem("Escolher area da tela", lambda: self.na_janela(self.escolher_area)),
            pystray.MenuItem("Frases", lambda: self.na_janela(self.abrir_frases)),
            pystray.MenuItem("Opcoes avancadas", lambda: self.na_janela(self.editar_opcoes)),
            pystray.MenuItem("Procurar atualizacao", lambda: self.na_janela(lambda: self.verificar_atualizacao(manual=True))),
            pystray.MenuItem("Sair", lambda: self.na_janela(self.sair)),
        )
        self.icone_bandeja = pystray.Icon("AlertaRoblox", imagem_icone(), "Alerta Roblox", menu)
        threading.Thread(target=self.icone_bandeja.run, daemon=True).start()

    # --- frases ---
    def _sincronizar_periodico(self):
        self.root.after(60_000, self._sincronizar_periodico)   # de novo em 1 minuto
        self.sincronizar_frases()

    def sincronizar_frases(self, depois=None):
        def fim(mudou, erro):
            if mudou:
                log("Frases atualizadas:", " | ".join(MENSAGENS.values()) or "(nenhuma)")
                self.monitor.reiniciar()
            if depois:
                depois()
        self.em_segundo_plano(sincronizar_frases, fim)

    def abrir_jogador(self):
        if getattr(self, "janela_jogador", None) and self.janela_jogador.win.winfo_exists():
            trazer_para_frente(self.janela_jogador.win)
            return
        log("Abrindo Jogador e servidor...")
        try:
            self.janela_jogador = JanelaJogador(self)
        except Exception as erro:
            log("Nao consegui abrir a janela:", repr(erro))
            dialogo(self.root, "Jogador e servidor", f"Não consegui abrir a janela:\n{erro}", tipo="erro")

    def abrir_frases(self):
        if not ler_config().get("chave_pc"):
            dialogo(self.root, "Alerta Roblox", "Primeiro conecte com o Discord (passo 1).", tipo="aviso")
            return
        if getattr(self, "janela_frases", None) and self.janela_frases.win.winfo_exists():
            trazer_para_frente(self.janela_frases.win)
            return
        self.janela_frases = JanelaFrases(self)

    # --- atualizacao automatica ---
    def _verificar_atualizacao(self):
        self.root.after(30 * 60 * 1000, self._verificar_atualizacao)   # de novo em 30 minutos
        if ATUALIZAR_SOZINHO:
            self.verificar_atualizacao()

    def verificar_atualizacao(self, manual=False):
        if getattr(self, "atualizando", False) or getattr(self, "procurando", False):
            return
        if manual and VERSAO == "dev":
            dialogo(self.root, "Atualizar", "Esta cópia roda pelo Python (versão de desenvolvimento): "
                                            "não se atualiza sozinha.", tipo="aviso")
            return
        self.procurando = True
        self.btn_atualizar.configure(state="disabled", text="Procurando...")
        if manual:
            log("Procurando versao nova...")

        def procurar_e_baixar():
            info = procurar_atualizacao()
            if not info:
                return None
            log(f"Versao nova {info['versao']} encontrada. Baixando...")
            return info, baixar_instalador(info)

        def fim(res, erro):
            self.procurando = False
            self.btn_atualizar.configure(state="normal", text="Atualizar")
            if erro:
                log("Nao consegui atualizar agora (tento mais tarde):", erro)
                if manual:
                    dialogo(self.root, "Atualizar", f"Não consegui atualizar agora:\n{erro}", tipo="erro")
            elif res:
                self.instalar_atualizacao(*res)
            elif manual:
                log(f"Voce ja esta na versao mais nova ({VERSAO}).")
                dialogo(self.root, "Atualizar", f"Você já está na versão mais nova ({VERSAO}).")
        self.em_segundo_plano(procurar_e_baixar, fim)

    def instalar_atualizacao(self, info, caminho):
        """Roda o instalador em modo silencioso e fecha; o instalador reabre o programa."""
        self.atualizando = True
        log(f"Instalando a versao {info['versao']}. O Alerta Roblox reabre sozinho em instantes.")
        try:
            subprocess.Popen([caminho, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                             close_fds=True, creationflags=0x00000008 if os.name == "nt" else 0)
        except Exception as erro:
            self.atualizando = False
            log("Falha ao abrir o instalador:", erro)
            return
        self.monitor.parar()
        if self.icone_bandeja is not None:
            try:
                self.icone_bandeja.stop()
            except Exception:
                pass
        self.root.after(500, lambda: os._exit(0))

    def mostrar(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def esconder(self):
        self.root.withdraw()
        if self.icone_bandeja is not None and not getattr(self, "_avisou", False):
            self._avisou = True
            try:
                self.icone_bandeja.notify("O Alerta Roblox continua rodando aqui.", "Alerta Roblox")
            except Exception:
                pass

    def sair(self):
        self.mostrar()
        if dialogo(self.root, "Alerta Roblox", "Parar o Alerta Roblox?\nOs alertas deixam de ser enviados.",
                   ("Cancelar", "Parar"), "aviso") != "Parar":
            return
        self.monitor.parar()
        if self.icone_bandeja is not None:
            try:
                self.icone_bandeja.stop()
            except Exception:
                pass
        self.root.destroy()

    # --- acoes dos botoes ---
    def conectar(self):
        if self.ocupado:
            return
        self.ocupado = True
        self.passo_conta["botao"].configure(state="disabled", text="Aguardando o Discord...")
        log("Conectando com o Discord...")

        def fim(res, erro):
            self.ocupado = False
            self.passo_conta["botao"].configure(state="normal")
            ok, msg = res if res else (False, str(erro))
            log(msg)
            self.mostrar()
            if ok:
                dialogo(self.root, "Conectado", msg + "\n\nAgora escolha a área da tela e o canal do Discord.")
                self.monitor.reiniciar()
                self.sincronizar_frases()
            else:
                dialogo(self.root, "Não conectou", msg, tipo="aviso")
        self.em_segundo_plano(conectar_discord, fim)

    def escolher_area(self):
        log("Deixe o jogo visivel. Em 3 segundos a tela escurece: arraste sobre a area das mensagens.")
        self.root.withdraw()

        def pronto(regiao):
            if regiao:
                salvar_config(regiao=regiao)
                log("Área salva:", regiao)
                self.monitor.reiniciar()
            else:
                log("Escolha da área cancelada.")
            self.mostrar()
        def abrir():
            try:
                selecionar_area(self.root, pronto)
                log("Tela de selecao aberta.")
            except Exception as erro:
                log("Nao consegui abrir a tela de selecao:", repr(erro))
                self.mostrar()
                dialogo(self.root, "Área da tela", f"Não consegui abrir a seleção da área:\n{erro}", tipo="erro")
        self.root.after(3000, abrir)

    def enviar_teste(self):
        if not ler_config().get("chave_pc"):
            dialogo(self.root, "Alerta Roblox", "Primeiro conecte com o Discord (passo 1).", tipo="aviso")
            return
        log("Enviando alerta de teste...")
        enviar_alerta("Teste", "Se voce recebeu isto, esta tudo funcionando!", teste=True)

    def editar_opcoes(self):
        log("Abrindo as opções no Bloco de Notas. Salve e feche para valer.")

        def fim(erro_cfg, erro):
            msg = erro_cfg or (str(erro) if erro else None)
            if msg:
                log(msg)
                dialogo(self.root, "Opções", msg, tipo="erro")
            else:
                log("Opções atualizadas.")
                self.monitor.reiniciar()
        self.em_segundo_plano(editar_config, fim)

    def abrir_painel_discord(self):
        if not ler_config().get("chave_pc"):
            dialogo(self.root, "Alerta Roblox", "Primeiro conecte com o Discord (passo 1).", tipo="aviso")
            return
        if getattr(self, "painel", None) and self.painel.win.winfo_exists():
            trazer_para_frente(self.painel.win)
            return
        log("Abrindo o painel do Discord...")
        try:
            self.painel = PainelDiscord(self)
        except Exception as erro:
            log("Nao consegui abrir o painel:", repr(erro))
            dialogo(self.root, "Discord", f"Não consegui abrir o painel:\n{erro}", tipo="erro")


class JanelaJogador:
    """Nome do jogador, mapa (Normal/Jungle) e codigo do servidor: vao junto com cada alerta."""

    def __init__(self, app):
        self.app = app
        self.win = ctk.CTkToplevel(app.root)
        self.win.title("Jogador e servidor")
        self.win.geometry("480x540")
        self.win.configure(fg_color=COR["fundo"])
        self.win.transient(app.root)
        corpo = ctk.CTkFrame(self.win, fg_color="transparent")
        corpo.pack(fill="both", expand=True, padx=20, pady=16)
        ctk.CTkLabel(corpo, text="Jogador e servidor", text_color=COR["texto"], font=fonte(20, "bold")).pack(anchor="w")
        ctk.CTkLabel(corpo, text="Isto vai junto com cada alerta, no celular e no Discord.",
                     text_color=COR["fraco"], font=fonte(12)).pack(anchor="w", pady=(2, 14))

        self.detectado = ctk.CTkLabel(corpo, text="Lendo o Roblox...", text_color=COR["fraco"], font=fonte(12),
                                      justify="left", anchor="w", wraplength=430)

        self.nome = self._campo(corpo, "Nome do jogador", "Vazio = descobre sozinho pelo Roblox", NOME_JOGADOR)

        ctk.CTkLabel(corpo, text="Mapa", text_color=COR["texto"], font=fonte(13, "bold")).pack(anchor="w", pady=(12, 4))
        self.mapa = ctk.CTkSegmentedButton(corpo, values=list(MAPAS), height=36, font=fonte(13, "bold"),
                                           selected_color=COR["destaque"], selected_hover_color=COR["destaque2"],
                                           unselected_color=COR["sec"], unselected_hover_color=COR["sec2"],
                                           fg_color=COR["sec"], text_color="#ffffff")
        self.mapa.set(MAPA if MAPA in MAPAS else MAPAS[0])
        self.mapa.pack(fill="x")

        self.codigo = self._campo(corpo, "Código do servidor", "Código ou link do servidor", CODIGO_SERVIDOR)

        self.detectado.pack(fill="x", pady=(14, 0))
        linha = ctk.CTkFrame(corpo, fg_color="transparent")
        linha.pack(fill="x", side="bottom", pady=(10, 0))
        botao(linha, "Salvar", self.salvar, "pri", width=120).pack(side="right")
        botao(linha, "Cancelar", self.win.destroy, width=110).pack(side="right", padx=8)
        trazer_para_frente(self.win)
        app.em_segundo_plano(info_roblox, self._mostrar_detectado)

    def _campo(self, pai, titulo, dica, valor):
        ctk.CTkLabel(pai, text=titulo, text_color=COR["texto"], font=fonte(13, "bold")).pack(anchor="w", pady=(12, 4))
        e = ctk.CTkEntry(pai, placeholder_text=dica, height=38, corner_radius=10, fg_color=COR["cartao"],
                         border_color=COR["borda"], text_color=COR["texto"], font=fonte(13))
        if valor:
            e.insert(0, valor)
        e.pack(fill="x")
        return e

    def _mostrar_detectado(self, info, erro):
        if not self.win.winfo_exists():
            return
        if erro or not info or not info.get("arquivo"):
            self.detectado.configure(text="Não achei o Roblox aberto. Com o jogo aberto, o nome e o "
                                          "servidor (Job ID) são detectados sozinhos.")
            return
        self.detectado.configure(text=f"Detectado no Roblox: jogador {info.get('jogador') or '?'}  ·  "
                                      f"servidor (Job ID) {info.get('job_id') or '?'}")

    def salvar(self):
        global NOME_JOGADOR, MAPA, CODIGO_SERVIDOR
        NOME_JOGADOR = self.nome.get().strip()[:60]
        MAPA = self.mapa.get() if self.mapa.get() in MAPAS else MAPAS[0]
        CODIGO_SERVIDOR = self.codigo.get().strip()[:200]
        dados = ler_config()
        opcoes = dados.get("opcoes") if isinstance(dados.get("opcoes"), dict) else {}
        opcoes.update(nome_jogador=NOME_JOGADOR, mapa=MAPA, codigo_servidor=CODIGO_SERVIDOR)
        salvar_config(opcoes=opcoes)
        log(f"Salvo: jogador {NOME_JOGADOR or '(automatico)'} | mapa {MAPA} | servidor {CODIGO_SERVIDOR or '-'}")
        self.win.destroy()


class JanelaFrases:
    """Adicionar e remover as frases procuradas (ficam na conta, valem para todos os PCs)."""

    def __init__(self, app):
        self.app = app
        self.win = ctk.CTkToplevel(app.root)
        self.win.title("Frases procuradas")
        self.win.geometry("480x520")
        self.win.configure(fg_color=COR["fundo"])
        self.win.transient(app.root)
        ctk.CTkLabel(self.win, text="Frases procuradas", text_color=COR["texto"], font=fonte(20, "bold")).pack(
            anchor="w", padx=20, pady=(18, 0))
        ctk.CTkLabel(self.win, text="Quando uma destas aparecer no chat do jogo, você recebe o alerta. "
                                    "Ficam na sua conta: também dá para mudar no app e no site.",
                     text_color=COR["fraco"], font=fonte(12), wraplength=440, justify="left").pack(
            anchor="w", padx=20, pady=(4, 12))
        linha = ctk.CTkFrame(self.win, fg_color="transparent")
        linha.pack(fill="x", padx=20)
        self.entrada = ctk.CTkEntry(linha, placeholder_text="Ex.: Something feels off", height=38,
                                    corner_radius=10, fg_color=COR["cartao"], border_color=COR["borda"],
                                    text_color=COR["texto"], font=fonte(13))
        self.entrada.pack(side="left", fill="x", expand=True)
        self.entrada.bind("<Return>", lambda e: self.adicionar())
        self.btn_add = botao(linha, "+ Adicionar", self.adicionar, "pri", width=120)
        self.btn_add.pack(side="left", padx=(8, 0))
        self.aviso = ctk.CTkLabel(self.win, text="", text_color="#ff6b6b", font=fonte(12), anchor="w")
        self.aviso.pack(fill="x", padx=20, pady=(4, 0))
        self.lista = ctk.CTkScrollableFrame(self.win, fg_color="transparent")
        self.lista.pack(fill="both", expand=True, padx=14, pady=(4, 16))
        trazer_para_frente(self.win)
        self.carregar()

    def carregar(self):
        self.app.em_segundo_plano(lambda: chamar_discord("frases"), self.mostrar)

    def mostrar(self, r, erro):
        if not self.win.winfo_exists():
            return
        for w in self.lista.winfo_children():
            w.destroy()
        if erro:
            self.aviso.configure(text=f"Erro: {erro}")
            return
        frases = r.get("frases") or []
        if not frases:
            ctk.CTkLabel(self.lista, text="Nenhuma frase. Adicione uma acima.", text_color=COR["fraco"],
                         font=fonte(13)).pack(pady=20)
        for f in frases:
            c = cartao(self.lista)
            c.pack(fill="x", pady=4, padx=4)
            ctk.CTkLabel(c, text=f["texto"], text_color=COR["texto"], font=fonte(13), anchor="w",
                         wraplength=300, justify="left").pack(side="left", fill="x", expand=True, padx=14, pady=12)
            botao(c, "Remover", lambda f=f: self.remover(f), "perigo", width=90, height=32).pack(side="right", padx=10)

    def depois_de_mudar(self, r, erro):
        self.btn_add.configure(state="normal")
        if erro:
            self.aviso.configure(text=str(erro))
            return
        self.aviso.configure(text="")
        self.carregar()
        self.app.sincronizar_frases()

    def adicionar(self):
        texto = self.entrada.get().strip()
        if len(texto) < 3:
            self.aviso.configure(text="A frase precisa ter pelo menos 3 letras.")
            return
        self.entrada.delete(0, "end")
        self.btn_add.configure(state="disabled")
        self.app.em_segundo_plano(lambda: chamar_discord("frase_add", texto=texto), self.depois_de_mudar)

    def remover(self, f):
        if dialogo(self.win, "Frases", f"Parar de procurar \"{f['texto']}\"?", ("Cancelar", "Remover"),
                   "aviso") != "Remover":
            return
        self.app.em_segundo_plano(lambda: chamar_discord("frase_del", id=f["id"]), self.depois_de_mudar)


def baixar_imagem(url, tamanho=40):
    """Baixa o icone do servidor e deixa redondo."""
    from PIL import Image, ImageDraw
    import io
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=8) as r:
        img = Image.open(io.BytesIO(r.read())).convert("RGBA").resize((tamanho * 2, tamanho * 2))
    mascara = Image.new("L", img.size, 0)
    ImageDraw.Draw(mascara).ellipse((0, 0) + img.size, fill=255)
    img.putalpha(mascara)
    return img


class PainelDiscord:
    """Janela com os servidores onde voce e o bot estao; admin escolhe o canal."""

    def __init__(self, app):
        self.app = app
        self.win = ctk.CTkToplevel(app.root)
        self.win.title("Canal do Discord")
        self.win.geometry("560x560")
        self.win.configure(fg_color=COR["fundo"])
        self.win.transient(app.root)
        self.imagens = []
        self.corpo = ctk.CTkFrame(self.win, fg_color="transparent")
        self.corpo.pack(fill="both", expand=True, padx=18, pady=16)
        trazer_para_frente(self.win)
        self.carregar()

    def limpar(self):
        for w in self.corpo.winfo_children():
            w.destroy()

    def texto(self, msg, cor=None):
        ctk.CTkLabel(self.corpo, text=msg, text_color=cor or COR["fraco"], font=fonte(13),
                     wraplength=500, justify="left").pack(anchor="w", pady=6)

    def carregar(self):
        self.limpar()
        self.texto("Carregando seus servidores...")
        self.app.em_segundo_plano(lambda: chamar_discord("painel"), self.mostrar)

    def mostrar(self, r, erro):
        if not self.win.winfo_exists():
            return
        self.limpar()
        c = self.corpo
        if erro:
            self.texto(f"Erro: {erro}", "#ff6b6b")
            botao(c, "Tentar de novo", self.carregar, width=150).pack(anchor="w", pady=6)
            return
        if not r.get("conectado"):
            self.texto("O login do Discord expirou. Na janela principal, clique em "
                       "\"Conectar de novo\" e depois abra este painel outra vez.")
            return

        topo = ctk.CTkFrame(c, fg_color="transparent")
        topo.pack(fill="x")
        ctk.CTkLabel(topo, text="Servidores", text_color=COR["texto"], font=fonte(20, "bold")).pack(side="left")
        botao(topo, "↻", self.carregar, width=38).pack(side="right")
        botao(topo, "+ Adicionar bot", lambda: webbrowser.open(r["convite"]), "pri", width=140).pack(side="right", padx=8)
        ctk.CTkLabel(c, text=f"Conectado como {r.get('nome')}  ·  aparecem os servidores onde você e o bot estão",
                     text_color=COR["fraco"], font=fonte(12), anchor="w").pack(fill="x", pady=(2, 10))
        if any(g.get("canal") and not g.get("participando") for g in (r.get("servidores") or [])):
            botao(c, "Mandar meus alertas em todos os servidores com canal", self.todos, height=34).pack(fill="x", pady=(0, 8))

        servidores = r.get("servidores") or []
        if not servidores:
            self.texto("O bot ainda não está em nenhum servidor seu. Clique em \"+ Adicionar bot\", "
                       "escolha o servidor e depois clique em ↻ para atualizar.")
            return

        lista = ctk.CTkScrollableFrame(c, fg_color="transparent")
        lista.pack(fill="both", expand=True)
        escolhidos = [g for g in servidores if g.get("canal") and g.get("participando", True)]
        salvar_config(canal_discord=(
            f"#{escolhidos[0]['canal']['nome']}" + (f" +{len(escolhidos) - 1}" if len(escolhidos) > 1 else "")
        ) if escolhidos else None)
        for g in servidores:
            self._cartao_servidor(lista, g)

    def _cartao_servidor(self, lista, g):
        card = cartao(lista)
        card.pack(fill="x", pady=5, padx=2)
        card.grid_columnconfigure(1, weight=1)
        icone = ctk.CTkLabel(card, text=g["nome"][:1].upper(), width=40, height=40, corner_radius=20,
                             fg_color=COR["sec2"], text_color=COR["texto"], font=fonte(16, "bold"))
        icone.grid(row=0, column=0, rowspan=2, padx=(14, 10), pady=14)
        if g.get("icone"):
            def pronto(img, erro, icone=icone):
                if img is not None and icone.winfo_exists():
                    foto = ctk.CTkImage(light_image=img, dark_image=img, size=(40, 40))
                    self.imagens.append(foto)
                    icone.configure(image=foto, text="", fg_color="transparent")
            self.app.em_segundo_plano(lambda u=g["icone"]: baixar_imagem(u), pronto)
        ctk.CTkLabel(card, text=g["nome"], text_color=COR["texto"], font=fonte(14, "bold"), anchor="w").grid(
            row=0, column=1, sticky="sw", pady=(14, 0))
        canal, eu = g.get("canal"), g.get("participando")
        if canal and eu:
            sub, cor = f"Seus alertas vão para #{canal['nome']}", COR["ok"]
        elif canal:
            sub, cor = f"Canal #{canal['nome']} · seus alertas não vão para lá", COR["fraco"]
        elif g.get("admin"):
            sub, cor = "Nenhum canal escolhido", COR["fraco"]
        else:
            sub, cor = "Esperando um administrador escolher o canal", COR["fraco"]
        ctk.CTkLabel(card, text=sub, text_color=cor, font=fonte(12), anchor="w", wraplength=300,
                     justify="left").grid(row=1, column=1, sticky="nw", pady=(0, 10))

        linha = ctk.CTkFrame(card, fg_color="transparent")
        linha.grid(row=2, column=0, columnspan=2, sticky="ew", padx=14, pady=(0, 14))
        if canal:
            if eu:
                botao(linha, "Parar meus alertas", lambda: self.acao("remover", g, None), "perigo",
                      height=32).pack(side="left", padx=(0, 6))
            else:
                botao(linha, "Mandar meus alertas aqui",
                      lambda: self.acao("participar", g, f"Pronto! Seus alertas vão para #{canal['nome']}."),
                      "pri", height=32).pack(side="left", padx=(0, 6))
        if g.get("admin"):
            botao(linha, "Trocar canal" if canal else "Escolher canal", lambda: self.escolher_canal(g),
                  "sec" if canal else "pri", height=32).pack(side="left", padx=(0, 6))
            if canal:
                botao(linha, "Desligar canal", lambda: self.desligar(g), "perigo", height=32).pack(side="left")
        if not linha.winfo_children():
            linha.destroy()

    def todos(self):
        def fim(r, e):
            total = (r or {}).get("total", 0)
            self._depois(e, f"Pronto! Seus alertas vão para {total} servidor(es)." if total
                         else "Nenhum servidor tem canal escolhido ainda.")
        self.app.em_segundo_plano(lambda: chamar_discord("participar_todos"), fim)

    def acao(self, qual, g, msg_ok):
        self.app.em_segundo_plano(lambda: chamar_discord(qual, guild_id=g["id"]),
                                  lambda r, e: self._depois(e, msg_ok))

    def desligar(self, g):
        if dialogo(self.win, "Discord", f"Desligar o canal de alertas de \"{g['nome']}\"?\n"
                                        "Para os alertas de TODOS os membros.", ("Cancelar", "Desligar"),
                   "aviso") != "Desligar":
            return
        self.acao("desligar", g, None)

    def escolher_canal(self, g):
        janela = ctk.CTkToplevel(self.win)
        janela.title(f"Canal em {g['nome']}")
        janela.geometry("380x460")
        janela.configure(fg_color=COR["fundo"])
        janela.transient(self.win)
        trazer_para_frente(janela)
        ctk.CTkLabel(janela, text=g["nome"], text_color=COR["texto"], font=fonte(17, "bold")).pack(
            anchor="w", padx=18, pady=(16, 0))
        aviso = ctk.CTkLabel(janela, text="Carregando canais...", text_color=COR["fraco"], font=fonte(12),
                             wraplength=340, justify="left")
        aviso.pack(anchor="w", padx=18, pady=(2, 8))
        lista = ctk.CTkScrollableFrame(janela, fg_color=COR["cartao"], corner_radius=12)
        lista.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        def usar(ch):
            aviso.configure(text="Salvando e mandando mensagem de teste...")
            for w in lista.winfo_children():
                w.configure(state="disabled")
            self.app.em_segundo_plano(
                lambda: chamar_discord("escolher", guild_id=g["id"], channel_id=ch["id"]),
                lambda r, e: (janela.destroy(), self._depois(e, f"Os alertas vão chegar em #{ch['nome']}. "
                                                               "O bot mandou uma mensagem de teste lá.")))

        def mostrar_canais(r, erro):
            if not janela.winfo_exists():
                return
            if erro:
                aviso.configure(text=f"Erro: {erro}", text_color="#ff6b6b")
                return
            aviso.configure(text="Clique no canal que vai receber os alertas:")
            atual = (g.get("canal") or {}).get("id")
            for ch in r.get("canais") or []:
                marcado = ch["id"] == atual
                ctk.CTkButton(lista, text=f"#  {ch['nome']}" + ("   ✓" if marcado else ""), anchor="w",
                              fg_color=COR["sec2"] if marcado else "transparent", hover_color=COR["sec"],
                              text_color=COR["ok"] if marcado else COR["texto"], corner_radius=8,
                              height=36, font=fonte(13), command=lambda ch=ch: usar(ch)).pack(fill="x", pady=2)

        self.app.em_segundo_plano(lambda: chamar_discord("canais", guild_id=g["id"]), mostrar_canais)

    def _depois(self, erro, msg_ok):
        pai = self.win if self.win.winfo_exists() else self.app.root
        if erro:
            dialogo(pai, "Discord", str(erro), tipo="erro")
        elif msg_ok:
            log(msg_ok)
            dialogo(pai, "Discord", msg_ok)
        if self.win.winfo_exists():
            self.carregar()


def ja_esta_aberto():
    """Evita abrir dois Alerta Roblox ao mesmo tempo (Windows)."""
    try:
        k = ctypes.windll.kernel32
        App._mutex = k.CreateMutexW(None, False, "AlertaRoblox_Unico")
        return k.GetLastError() == 183   # ERROR_ALREADY_EXISTS
    except Exception:
        return False


# ----------------------------- comandos (terminal) -------------------------
def testar_imagem(caminho):
    nome_leitor, ler = criar_leitor()
    if ler is None:
        print("Nenhum leitor de texto encontrado (pip install rapidocr_onnxruntime).")
        return
    img = cv2.imread(caminho, cv2.IMREAD_COLOR)
    if img is None:
        print("Nao consegui abrir:", caminho)
        return
    texto = ler(preparar(img))
    print(f"Leitor: {nome_leitor}\n--- texto lido ---\n{texto}\n------------------")
    norm = normalizar(texto)
    for nome, frase in MENSAGENS.items():
        nota = similaridade(normalizar(frase), norm)
        print(f"mensagem {nome} ({frase}): nota {nota:.2f}",
              "<- DETECTADA" if nota >= LIMIAR_TEXTO else "")


def autoteste():
    """Escreve uma frase numa imagem e confere se o leitor de texto le. 0 = ok."""
    nome_leitor, ler = criar_leitor()
    if ler is None:
        log("AUTOTESTE FALHOU: nenhum leitor de texto")
        return 1
    img = np.zeros((80, 700, 3), dtype=np.uint8)
    cv2.putText(img, "Something feels off", (10, 55), cv2.FONT_HERSHEY_SIMPLEX,
                1.5, (255, 255, 255), 3)
    texto = ler(preparar(img))
    nota = similaridade(normalizar("Something feels off"), normalizar(texto))
    log(f"AUTOTESTE Leitor: {nome_leitor} | leu: {texto!r} | nota {nota:.2f}")
    if nota < LIMIAR_TEXTO:
        return 1
    # A janela e o icone perto do relogio tambem precisam funcionar no .exe
    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
        imagem_icone()
        janela = ctk.CTk()
        janela.withdraw()
        ctk.CTkButton(janela, text="teste").pack()
        janela.update()
        janela.destroy()
        log(f"AUTOTESTE Janela: ok | icone: {caminho_recurso('icone.ico') or 'nao encontrado'}")
    except Exception as erro:
        log("AUTOTESTE Janela FALHOU:", repr(erro))
        return 1
    return 0


def debug_terminal():
    m = Monitor()
    m.debug = True
    m.iniciar()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        m.parar()


def abrir_janela():
    if ja_esta_aberto():
        try:
            ctypes.windll.user32.MessageBoxW(
                None, "O Alerta Roblox ja esta aberto.\nProcure o icone perto do relogio do Windows.",
                "Alerta Roblox", 0x40)
        except Exception:
            pass
        return
    App().root.mainloop()


if __name__ == "__main__":
    arg = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    carregar_opcoes()
    if arg == "autoteste":           # usado no build para checar o .exe
        sys.exit(autoteste())
    elif INSTALADO or arg in ("", "janela"):
        abrir_janela()
    elif arg == "debug":
        debug_terminal()
    elif arg == "imagem":
        testar_imagem(sys.argv[2] if len(sys.argv) > 2 else "")
    elif arg == "conectar":
        conectar_email()
    else:
        print(__doc__)
