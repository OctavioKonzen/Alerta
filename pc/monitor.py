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
import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
import webbrowser
from difflib import SequenceMatcher
from tkinter import messagebox, ttk

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
COOLDOWN = 30            # segundos minimos entre dois alertas da mesma mensagem
ZOOM_OCR = 2             # aumenta a imagem antes de ler (ajuda com letras pequenas)

ALERTA_TELA = False      # True = tambem pisca a tela do PC (F8 para parar)

# --- ROBLOX ---
NOME_JOGADOR = ""        # vazio = descobre sozinho pelo log do Roblox
LINK_SERVIDOR_PRIVADO = ""   # opcional: link do seu servidor privado (vai no alerta)

# --- NUVEM (preenchido por quem publica o app; nao precisa mexer) ---
SUPABASE_URL = "https://vtyxkowxnesclwtndbog.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_zvhYotnIF3LIm5FzzpkjZQ_GpNsp0Bz"
FUNCAO_ALERTA = "smooth-responder"   # Edge Function que recebe os alertas
FUNCAO_DISCORD = "discord-bot"       # Edge Function do login/painel do Discord
# ---------------------------------------------------------------------------

INSTALADO = getattr(sys, "frozen", False)   # True quando roda pelo .exe do instalador
if INSTALADO or os.environ.get("APPDATA"):
    PASTA = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "AlertaRoblox")
else:
    PASTA = os.path.dirname(os.path.abspath(__file__))
os.makedirs(PASTA, exist_ok=True)
CONFIG = os.path.join(PASTA, "config.json")
ARQUIVO_LOG = os.path.join(PASTA, "alerta.log")
USER_AGENT = "AlertaRoblox-PC/2.0"

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
}

try:  # evita problemas de escala (DPI) no Windows
    ctypes.windll.user32.SetProcessDPIAware()
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


def link_servidor(info):
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
                 "link": link_servidor(info), "teste": teste}
        for _tentativa in range(3):
            try:
                status, r = http(f"{SUPABASE_URL}/functions/v1/{FUNCAO_ALERTA}", dados,
                                 {"x-chave-pc": chave, "apikey": SUPABASE_ANON_KEY})
            except Exception as erro:
                log("Falha de conexao:", erro)
                time.sleep(2)
                continue
            if status == 200:
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
    janela.focus_force()


_leitor = None
_trava_leitor = threading.Lock()


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
            motor = __import__(modulo).RapidOCR()
        except Exception:
            continue

        def ler_rapid(gray, motor=motor):
            img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            res = motor(img)
            if isinstance(res, tuple):            # versao antiga: (lista, tempo)
                itens = res[0] or []
                return "\n".join(str(item[1]) for item in itens)
            txts = getattr(res, "txts", None)     # versao nova
            return "\n".join(txts) if txts else ""

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
                self.status = "Parado: escolha a area da tela"
            else:
                self.status = "Preparando o leitor de texto..."
                nome_leitor, ler = criar_leitor()
                if ler is None:
                    self.status = "Erro: leitor de texto nao encontrado"
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
        visivel = {n: False for n in chaves}   # ja alertou esta aparicao?
        ausente = {n: 0 for n in chaves}       # leituras seguidas sem ver a mensagem
        ultimo = {n: 0.0 for n in chaves}
        self.status = "Monitorando"
        log("Monitorando a area escolhida.")

        with mss.mss() as sct:
            while not parar.is_set():
                try:
                    texto = ler(preparar(capturar(sct, regiao)))
                except Exception as erro:          # falha passageira: tenta de novo
                    log("Erro na leitura (tentando de novo):", erro)
                    parar.wait(INTERVALO)
                    continue
                if parar.is_set():
                    break
                norm = normalizar(texto)
                if self.debug:
                    log("leu:", texto.replace("\n", " | ")[:300] or "(nada)")
                agora = time.time()
                for nome, chave in chaves.items():
                    nota = similaridade(chave, norm)
                    if self.debug and nota > 0.3:
                        log(f"  mensagem {nome}: nota {nota:.2f}")
                    if nota >= LIMIAR_TEXTO:
                        ausente[nome] = 0
                        if not visivel[nome] and agora - ultimo[nome] > COOLDOWN:
                            visivel[nome] = True
                            ultimo[nome] = agora
                            linha = linha_da_mensagem(texto, chave)
                            log(f"Detectado: {linha} ({nota:.2f})")
                            enviar_alerta(MENSAGENS[nome], linha)
                            if ALERTA_TELA and self.ao_detectar:
                                self.ao_detectar(nome)
                    else:
                        ausente[nome] += 1
                        if ausente[nome] >= 3:   # sumiu de vez: pode alertar de novo
                            visivel[nome] = False
                parar.wait(INTERVALO)


# ----------------------------- janela --------------------------------------
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


class App:
    def __init__(self):
        global _fila_log
        _fila_log = queue.Queue()
        self.acoes = queue.Queue()      # funcoes para rodar na janela (vindas de outras threads)
        self.root = tk.Tk()
        self.root.title("Alerta Roblox")
        self.root.geometry("560x520")
        self.root.minsize(460, 420)
        ico = caminho_recurso("icone.ico")
        if ico:
            try:
                self.root.iconbitmap(ico)
            except Exception:
                pass
        self.icone_bandeja = None
        self.monitor = Monitor(ao_detectar=lambda nome: self.na_janela(alerta_tela, self.root, nome))
        self.ocupado = False
        self._montar()
        self.root.protocol("WM_DELETE_WINDOW", self.esconder)
        self._iniciar_bandeja()
        self.monitor.iniciar()
        self.root.after(200, self._processar_filas)
        self.root.after(500, self._atualizar_status)
        log("Alerta Roblox aberto.")

    # --- montagem da janela ---
    def _montar(self):
        r = self.root
        topo = ttk.Frame(r, padding=12)
        topo.pack(fill="x")
        self.lbl_conta = ttk.Label(topo, font=("Segoe UI", 10, "bold"))
        self.lbl_conta.grid(row=0, column=0, sticky="w")
        self.lbl_area = ttk.Label(topo)
        self.lbl_area.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.lbl_status = ttk.Label(topo)
        self.lbl_status.grid(row=2, column=0, sticky="w", pady=(2, 0))

        botoes = ttk.Frame(r, padding=(12, 0))
        botoes.pack(fill="x")
        itens = [
            ("Conectar com Discord", self.conectar),
            ("Escolher area da tela", self.escolher_area),
            ("Canal do Discord", self.abrir_painel_discord),
            ("Enviar teste", self.enviar_teste),
            ("Editar frases e opcoes", self.editar_opcoes),
            ("Ver jogador e servidor", lambda: threading.Thread(target=mostrar_servidor, daemon=True).start()),
        ]
        for i, (texto, cmd) in enumerate(itens):
            b = ttk.Button(botoes, text=texto, command=cmd)
            b.grid(row=i // 2, column=i % 2, sticky="ew", padx=3, pady=3)
            if i == 0:
                self.btn_conectar = b
        botoes.columnconfigure(0, weight=1)
        botoes.columnconfigure(1, weight=1)

        self.var_debug = tk.BooleanVar(value=False)
        ttk.Checkbutton(r, text="Mostrar o que esta lendo (para testar)", variable=self.var_debug,
                        command=lambda: setattr(self.monitor, "debug", self.var_debug.get())
                        ).pack(anchor="w", padx=15, pady=(6, 0))

        caixa = ttk.Frame(r, padding=12)
        caixa.pack(fill="both", expand=True)
        self.txt = tk.Text(caixa, height=10, state="disabled", wrap="word",
                           bg="#0f1115", fg="#f2f4f8", font=("Consolas", 9), relief="flat")
        barra = ttk.Scrollbar(caixa, command=self.txt.yview)
        self.txt.configure(yscrollcommand=barra.set)
        self.txt.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")

        ttk.Label(r, foreground="#777", padding=(12, 0, 12, 10),
                  text="Fechar esta janela NAO para o alerta: ele continua perto do relogio. "
                       "Para sair, clique com o botao direito no icone e escolha Sair.",
                  wraplength=520).pack(fill="x")

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
        cfg = ler_config()
        if cfg.get("chave_pc"):
            self.lbl_conta.configure(text="Conta: conectada", foreground="#2e7d32")
            self.btn_conectar.configure(text="Conectar de novo")
        else:
            self.lbl_conta.configure(text="Conta: nao conectada", foreground="#c62828")
            self.btn_conectar.configure(text="Conectar com Discord")
        self.lbl_area.configure(text="Area da tela: " + ("escolhida" if cfg.get("regiao") else "nao escolhida"))
        self.lbl_status.configure(text="Situacao: " + self.monitor.status)
        if self.icone_bandeja is not None:
            try:
                self.icone_bandeja.title = "Alerta Roblox - " + self.monitor.status
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
            pystray.MenuItem("Sair", lambda: self.na_janela(self.sair)),
        )
        self.icone_bandeja = pystray.Icon("AlertaRoblox", imagem_icone(), "Alerta Roblox", menu)
        threading.Thread(target=self.icone_bandeja.run, daemon=True).start()

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
        if not messagebox.askyesno("Alerta Roblox", "Parar o Alerta Roblox?\nOs alertas deixam de ser enviados."):
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
        self.btn_conectar.state(["disabled"])
        log("Conectando com o Discord...")

        def fim(res, erro):
            self.ocupado = False
            self.btn_conectar.state(["!disabled"])
            ok, msg = res if res else (False, str(erro))
            log(msg)
            if ok:
                messagebox.showinfo("Alerta Roblox", msg + "\n\nAgora escolha a area da tela e o canal do Discord.")
                self.monitor.reiniciar()
            else:
                messagebox.showwarning("Alerta Roblox", msg)
            self.mostrar()
        self.em_segundo_plano(conectar_discord, fim)

    def escolher_area(self):
        self.root.withdraw()
        log("Deixe o jogo visivel. Em 3 segundos a tela escurece: arraste sobre a area das mensagens.")

        def pronto(regiao):
            if regiao:
                salvar_config(regiao=regiao)
                log("Area salva:", regiao)
                self.monitor.reiniciar()
            else:
                log("Escolha da area cancelada.")
            self.mostrar()
        self.root.after(3000, lambda: selecionar_area(self.root, pronto))

    def enviar_teste(self):
        if not ler_config().get("chave_pc"):
            messagebox.showwarning("Alerta Roblox", "Primeiro clique em 'Conectar com Discord'.")
            return
        log("Enviando alerta de teste...")
        enviar_alerta("Teste", "Se voce recebeu isto, esta tudo funcionando!", teste=True)

    def editar_opcoes(self):
        log("Abrindo as opcoes no Bloco de Notas. Salve e feche para valer.")

        def fim(erro_cfg, erro):
            msg = erro_cfg or (str(erro) if erro else None)
            if msg:
                log(msg)
                messagebox.showwarning("Alerta Roblox", msg)
            else:
                log("Opcoes atualizadas.")
                self.monitor.reiniciar()
        self.em_segundo_plano(editar_config, fim)

    def abrir_painel_discord(self):
        if not ler_config().get("chave_pc"):
            messagebox.showwarning("Alerta Roblox", "Primeiro clique em 'Conectar com Discord'.")
            return
        PainelDiscord(self)


class PainelDiscord:
    """Janela com os servidores onde voce e o bot estao; admin escolhe o canal."""

    def __init__(self, app):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.title("Canal do Discord")
        self.win.geometry("520x480")
        self.win.transient(app.root)
        self.corpo = ttk.Frame(self.win, padding=12)
        self.corpo.pack(fill="both", expand=True)
        self.carregar()

    def limpar(self):
        for w in self.corpo.winfo_children():
            w.destroy()

    def carregar(self):
        self.limpar()
        ttk.Label(self.corpo, text="Carregando seus servidores...").pack(anchor="w")
        self.app.em_segundo_plano(lambda: chamar_discord("painel"), self.mostrar)

    def mostrar(self, r, erro):
        if not self.win.winfo_exists():
            return
        self.limpar()
        c = self.corpo
        if erro:
            ttk.Label(c, text=f"Erro: {erro}", foreground="#c62828", wraplength=480).pack(anchor="w")
            ttk.Button(c, text="Tentar de novo", command=self.carregar).pack(anchor="w", pady=8)
            return
        if not r.get("conectado"):
            ttk.Label(c, wraplength=480, text="O login do Discord expirou. Clique em 'Conectar de novo' "
                      "na janela principal e depois abra este painel outra vez.").pack(anchor="w")
            return
        ttk.Label(c, text=f"Discord: {r.get('nome')}", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        linha = ttk.Frame(c)
        linha.pack(fill="x", pady=6)
        ttk.Button(linha, text="Adicionar o bot a um servidor",
                   command=lambda: webbrowser.open(r["convite"])).pack(side="left")
        ttk.Button(linha, text="Atualizar", command=self.carregar).pack(side="left", padx=6)

        servidores = r.get("servidores") or []
        if not servidores:
            ttk.Label(c, wraplength=480, text="O bot ainda nao esta em nenhum servidor seu. "
                      "Adicione o bot e clique em Atualizar.").pack(anchor="w", pady=10)
            return

        area = tk.Canvas(c, highlightthickness=0)
        barra = ttk.Scrollbar(c, command=area.yview)
        lista = ttk.Frame(area)
        lista.bind("<Configure>", lambda e: area.configure(scrollregion=area.bbox("all")))
        item = area.create_window((0, 0), window=lista, anchor="nw")
        area.bind("<Configure>", lambda e: area.itemconfigure(item, width=e.width))
        area.configure(yscrollcommand=barra.set)
        area.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")

        for g in servidores:
            quadro = ttk.LabelFrame(lista, text=g["nome"], padding=8)
            quadro.pack(fill="x", pady=4, padx=2)
            canal = f"#{g['canal']['nome']}" if g.get("canal") else "nenhum (nao recebe alertas)"
            ttk.Label(quadro, text=f"Canal dos alertas: {canal}").pack(anchor="w")
            if g.get("admin"):
                botoes = ttk.Frame(quadro)
                botoes.pack(anchor="w", pady=(4, 0))
                ttk.Button(botoes, text="Trocar canal" if g.get("canal") else "Escolher canal",
                           command=lambda g=g: self.escolher_canal(g)).pack(side="left")
                if g.get("canal"):
                    ttk.Button(botoes, text="Parar alertas aqui",
                               command=lambda g=g: self.parar(g)).pack(side="left", padx=6)
            else:
                ttk.Label(quadro, foreground="#777",
                          text="So administradores deste servidor podem configurar o bot.").pack(anchor="w")

    def parar(self, g):
        if not messagebox.askyesno("Discord", f"Parar de mandar alertas em \"{g['nome']}\"?", parent=self.win):
            return
        self.app.em_segundo_plano(lambda: chamar_discord("remover", guild_id=g["id"]),
                                  lambda r, e: self._depois(e, None))

    def escolher_canal(self, g):
        janela = tk.Toplevel(self.win)
        janela.title(f"Canal em {g['nome']}")
        janela.geometry("360x400")
        janela.transient(self.win)
        aviso = ttk.Label(janela, text="Carregando canais...", padding=8)
        aviso.pack(anchor="w")
        caixa = tk.Listbox(janela, activestyle="none", font=("Segoe UI", 10))
        caixa.pack(fill="both", expand=True, padx=8)
        canais = []

        def mostrar_canais(r, erro):
            if not janela.winfo_exists():
                return
            if erro:
                aviso.configure(text=f"Erro: {erro}", foreground="#c62828", wraplength=330)
                return
            canais.extend(r.get("canais") or [])
            aviso.configure(text="Escolha o canal e clique em 'Usar este canal':")
            for ch in canais:
                caixa.insert("end", f"# {ch['nome']}")

        def usar():
            sel = caixa.curselection()
            if not sel:
                return
            ch = canais[sel[0]]
            aviso.configure(text="Salvando e mandando mensagem de teste...")
            self.app.em_segundo_plano(
                lambda: chamar_discord("escolher", guild_id=g["id"], channel_id=ch["id"]),
                lambda r, e: (janela.destroy(), self._depois(e, f"Os alertas vao chegar em #{ch['nome']}. "
                                                               "O bot mandou uma mensagem de teste la.")))

        ttk.Button(janela, text="Usar este canal", command=usar).pack(pady=8)
        caixa.bind("<Double-Button-1>", lambda e: usar())
        self.app.em_segundo_plano(lambda: chamar_discord("canais", guild_id=g["id"]), mostrar_canais)

    def _depois(self, erro, msg_ok):
        if erro:
            messagebox.showwarning("Discord", str(erro), parent=self.win if self.win.winfo_exists() else None)
        elif msg_ok:
            log(msg_ok)
            messagebox.showinfo("Discord", msg_ok, parent=self.win)
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
    return 0 if nota >= LIMIAR_TEXTO else 1


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
