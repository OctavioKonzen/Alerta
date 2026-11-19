"""
Alerta Roblox - monitor do PC
-----------------------------
Le o texto de uma regiao da tela e, quando aparecer uma das frases
configuradas em MENSAGENS, manda alerta para o app Alerta Roblox no celular
com a mensagem, o nome do jogador e o codigo do servidor.

Instalacao (uma vez):
    pip install opencv-python mss numpy
    pip install rapidocr onnxruntime          <- leitor de texto (recomendado)
      (alternativa: instalar o programa Tesseract-OCR para Windows)

Uso:
    python monitor.py conectar   -> liga este PC a sua conta do app (1a vez)
    python monitor.py setup      -> escolher a area da tela a monitorar
    python monitor.py            -> iniciar o monitoramento
    python monitor.py debug      -> mostra o que ele esta lendo e as notas
    python monitor.py imagem foto.png -> testa a leitura em um print
    python monitor.py teste      -> manda um alerta de teste para o celular
    python monitor.py servidor   -> mostra o jogador e o servidor detectados
    python monitor.py configurar -> edita frases e opcoes (config.json)
Pare com Ctrl+C no terminal.

Pelo instalador (AlertaRoblox-Setup.exe) esses comandos viram atalhos
no Menu Iniciar. As configuracoes ficam em %APPDATA%\\AlertaRoblox.
"""
import ctypes
import getpass
import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
from difflib import SequenceMatcher

try:
    import cv2
    import mss
    import numpy as np
except ImportError as erro:
    print("Falta instalar uma biblioteca:", erro)
    print("Rode no cmd:  pip install opencv-python mss numpy")
    input("Aperte ENTER para fechar...")
    raise SystemExit

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
SUPABASE_URL = "https://SEU-PROJETO.supabase.co"
SUPABASE_ANON_KEY = "SUA_ANON_KEY"
# ---------------------------------------------------------------------------

INSTALADO = getattr(sys, "frozen", False)   # True quando roda pelo .exe do instalador
if INSTALADO or os.environ.get("APPDATA"):
    PASTA = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "AlertaRoblox")
else:
    PASTA = os.path.dirname(os.path.abspath(__file__))
os.makedirs(PASTA, exist_ok=True)
CONFIG = os.path.join(PASTA, "config.json")
USER_AGENT = "AlertaRoblox-PC/1.0"

# Opcoes que o usuario pode mudar no config.json (comando "configurar")
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
                print(f"Aviso: valor invalido para '{chave}' no config.json, usando o padrao.")
        else:
            opcoes[chave] = globals()[var]
            mudou = True
    if mudou:
        salvar_config(opcoes=opcoes)


def configurar():
    """Abre o config.json no Bloco de Notas para editar frases e opcoes."""
    carregar_opcoes()
    print("Arquivo de configuracao:", CONFIG)
    print('Edite "mensagens" (frases procuradas) e as outras opcoes, salve e feche.')
    print("Depois reabra o Alerta Roblox para valer.")
    try:
        subprocess.run(["notepad.exe", CONFIG])
    except Exception:
        try:
            os.startfile(CONFIG)
        except Exception:
            print("Abra o arquivo acima em um editor de texto.")
    try:
        with open(CONFIG, encoding="utf-8") as f:
            json.load(f)
        print("Configuracao OK.")
    except ValueError as erro:
        print("ATENCAO: o arquivo ficou com erro de formato:", erro)
        print("Confira virgulas e aspas, ou apague o arquivo para voltar ao padrao.")


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


def nuvem_configurada():
    if "SEU-PROJETO" in SUPABASE_URL or "SUA_ANON" in SUPABASE_ANON_KEY:
        print("SUPABASE_URL / SUPABASE_ANON_KEY ainda nao foram preenchidos no monitor.py.")
        return False
    return True


# ----------------------------- conectar ------------------------------------
def conectar():
    """Faz login com a conta do app e cria a chave deste PC."""
    if not nuvem_configurada():
        return
    print("Entre com a MESMA conta que voce usa no app Alerta Roblox.")
    print("(a senha e usada so agora para criar a chave; ela nao fica salva)")
    email = input("E-mail: ").strip()
    senha = getpass.getpass("Senha (nao aparece ao digitar): ")
    status, r = http(f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
                     {"email": email, "password": senha},
                     {"apikey": SUPABASE_ANON_KEY})
    if status != 200 or not isinstance(r, dict) or "access_token" not in r:
        msg = r.get("error_description") or r.get("msg") if isinstance(r, dict) else r
        print("Nao consegui entrar:", msg or status)
        print("Confira e-mail/senha e se voce ja confirmou o e-mail da conta.")
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
    print("Teste com:  python monitor.py teste")


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
        print("Nao achei os logs do Roblox. Abra o jogo e tente de novo.")
        return
    print("Log lido:", info["arquivo"])
    print("Jogador :", info["jogador"] or "(nao detectado - preencha NOME_JOGADOR)")
    print("Servidor:", info["job_id"] or "(nao detectado)")
    print("Place ID:", info["place_id"] or "(nao detectado)")
    print("Em jogo :", "sim" if info["em_jogo"] else "nao")
    print("Link    :", link_servidor(info) or "-")


# ----------------------------- envio ---------------------------------------
def enviar_alerta(frase, mensagem, teste=False, esperar=False):
    """Manda o alerta para a nuvem, que avisa os celulares da sua conta."""
    chave = ler_config().get("chave_pc")
    if not chave:
        print("Este PC ainda nao esta conectado. Rode:  python monitor.py conectar")
        return

    def _enviar():
        info = info_roblox()
        dados = {"frase": frase, "mensagem": mensagem, "jogador": info["jogador"],
                 "job_id": info["job_id"], "place_id": info["place_id"],
                 "link": link_servidor(info), "teste": teste}
        for tentativa in range(3):
            try:
                status, r = http(f"{SUPABASE_URL}/functions/v1/send-alert", dados,
                                 {"x-chave-pc": chave, "apikey": SUPABASE_ANON_KEY})
            except Exception as erro:
                print("Falha de conexao:", erro)
                time.sleep(2)
                continue
            if status == 200:
                env = r.get("enviados", 0) if isinstance(r, dict) else 0
                aviso = r.get("aviso", "") if isinstance(r, dict) else ""
                print(f"Alerta enviado ({env} celular(es)). {aviso}".strip())
            elif status == 401:
                print("Chave do PC invalida (PC removido no app?). Rode: python monitor.py conectar")
            elif status == 429:
                print("Muitos alertas seguidos; a nuvem pediu para esperar.")
            else:
                print("Erro ao enviar:", status, r)
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


def _console(acao):
    """Minimiza (6) ou restaura (9) a janela do cmd, se possivel."""
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, acao)
    except Exception:
        pass


def setup():
    """Seleciona a area ao vivo: arraste um retangulo sobre o jogo."""
    print("O cmd sera minimizado. Voce tem 5 segundos para deixar o jogo visivel")
    print("(clique na janela do jogo). Depois, ARRASTE o mouse sobre a area das")
    print("mensagens. ESC cancela.")
    _console(6)
    for i in range(5, 0, -1):
        print(i, "...")
        time.sleep(1)

    resultado = {}
    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.30)
    root.configure(bg="black", cursor="crosshair")
    canvas = tk.Canvas(root, bg="black", highlightthickness=0, cursor="crosshair")
    canvas.pack(fill="both", expand=True)
    canvas.create_text(
        root.winfo_screenwidth() // 2, 40, fill="white",
        font=("Arial", 22, "bold"),
        text="Arraste o mouse sobre a area das mensagens  (ESC cancela)")
    estado = {"x0": 0, "y0": 0, "ret": None}

    def apertou(e):
        estado["x0"], estado["y0"] = e.x_root, e.y_root
        if estado["ret"]:
            canvas.delete(estado["ret"])
        estado["ret"] = canvas.create_rectangle(
            e.x, e.y, e.x, e.y, outline="red", width=3)
        estado["cx0"], estado["cy0"] = e.x, e.y

    def arrastou(e):
        if estado["ret"]:
            canvas.coords(estado["ret"], estado["cx0"], estado["cy0"], e.x, e.y)

    def soltou(e):
        x1, y1 = e.x_root, e.y_root
        x0, y0 = estado["x0"], estado["y0"]
        l, t = min(x0, x1), min(y0, y1)
        w, h = abs(x1 - x0), abs(y1 - y0)
        if w > 5 and h > 5:
            resultado.update({"left": l, "top": t, "width": w, "height": h})
        root.destroy()

    canvas.bind("<ButtonPress-1>", apertou)
    canvas.bind("<B1-Motion>", arrastou)
    canvas.bind("<ButtonRelease-1>", soltou)
    root.bind("<Escape>", lambda e: root.destroy())
    root.focus_force()
    root.mainloop()

    _console(9)
    if not resultado:
        print("Cancelado.")
        return
    salvar_config(regiao=resultado)
    print("Area salva:", resultado)


def criar_leitor():
    """Escolhe o leitor de texto disponivel: RapidOCR ou Tesseract."""
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

        return "RapidOCR", ler_rapid

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

        return "Tesseract", ler_tess
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


AJUDA_OCR = """
Nenhum leitor de texto encontrado. Instale UM destes:
  1) No cmd:  pip install rapidocr onnxruntime
  2) Ou instale o Tesseract-OCR para Windows (instalador "UB Mannheim").
Depois rode de novo.
"""


# ----------------------------- alerta na tela ------------------------------
def som(parar):
    try:
        import winsound
        while not parar.is_set():
            winsound.Beep(1200, 250)
            winsound.Beep(800, 250)
    except ImportError:
        while not parar.is_set():
            print("\a", end="", flush=True)
            time.sleep(0.5)


def f8_apertado():
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(0x77) & 0x8000)
    except Exception:
        return False


def alerta_tela(nome):
    """Pisca a tela inteira ate voce apertar F8."""
    parar = threading.Event()
    threading.Thread(target=som, args=(parar,), daemon=True).start()
    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.45)
    root.configure(bg="red")
    label = tk.Label(root, text=f"ALERTA!\nMensagem {nome}\n\nAperte F8 para parar",
                     font=("Arial", 44, "bold"), fg="white", bg="red")
    label.pack(expand=True)
    estado = {"vermelho": True, "fechado": False}

    try:  # deixa os cliques passarem para o jogo (Windows)
        root.update()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        estilo = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
        ctypes.windll.user32.SetWindowLongW(hwnd, -20, estilo | 0x80000 | 0x20)
    except Exception:
        pass

    def fechar(e=None):
        if estado["fechado"]:
            return
        estado["fechado"] = True
        parar.set()
        root.destroy()

    def piscar():
        if estado["fechado"]:
            return
        estado["vermelho"] = not estado["vermelho"]
        cor = "red" if estado["vermelho"] else "yellow"
        root.configure(bg=cor)
        label.configure(bg=cor, fg="white" if estado["vermelho"] else "black")
        root.after(250, piscar)

    def verificar_f8():
        if estado["fechado"]:
            return
        if f8_apertado():
            fechar()
            return
        root.after(30, verificar_f8)

    root.bind("<F8>", fechar)
    piscar()
    verificar_f8()
    root.mainloop()


# ----------------------------- comandos ------------------------------------
def testar_imagem(caminho):
    nome_leitor, ler = criar_leitor()
    if ler is None:
        print(AJUDA_OCR)
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
        print("FALHOU: nenhum leitor de texto")
        return 1
    img = np.zeros((80, 700, 3), dtype=np.uint8)
    cv2.putText(img, "Something feels off", (10, 55), cv2.FONT_HERSHEY_SIMPLEX,
                1.5, (255, 255, 255), 3)
    texto = ler(preparar(img))
    nota = similaridade(normalizar("Something feels off"), normalizar(texto))
    print(f"Leitor: {nome_leitor} | leu: {texto!r} | nota {nota:.2f}")
    return 0 if nota >= LIMIAR_TEXTO else 1


def monitorar(debug=False):
    if not nuvem_configurada():
        return
    if not ler_config().get("chave_pc"):
        print("Primeiro ligue este PC a sua conta do app:")
        conectar()
        if not ler_config().get("chave_pc"):
            return
    if not ler_config().get("regiao"):
        print("Agora escolha a area da tela:")
        setup()
        if not ler_config().get("regiao"):
            return
    regiao = ler_config()["regiao"]
    nome_leitor, ler = criar_leitor()
    if ler is None:
        print(AJUDA_OCR)
        return
    print("Leitor de texto:", nome_leitor)
    info = info_roblox()
    print("Jogador:", info["jogador"] or "?", "| Servidor:", info["job_id"] or "?")

    chaves = {n: normalizar(t) for n, t in MENSAGENS.items()}
    visivel = {n: False for n in chaves}   # ja alertou esta aparicao?
    ausente = {n: 0 for n in chaves}       # leituras seguidas sem ver a mensagem
    ultimo = {n: 0.0 for n in chaves}

    print("Monitorando... (Ctrl+C para parar)")
    with mss.mss() as sct:
        while True:
            try:
                texto = ler(preparar(capturar(sct, regiao)))
            except Exception as erro:          # falha passageira: tenta de novo
                print("Erro na leitura (tentando de novo):", erro)
                time.sleep(INTERVALO)
                continue
            norm = normalizar(texto)
            if debug:
                print("--- leu:", texto.replace("\n", " | ")[:400])
            agora = time.time()
            for nome, chave in chaves.items():
                nota = similaridade(chave, norm)
                if debug:
                    print(f"mensagem {nome}: nota {nota:.2f}")
                if nota >= LIMIAR_TEXTO:
                    ausente[nome] = 0
                    if not visivel[nome] and agora - ultimo[nome] > COOLDOWN:
                        visivel[nome] = True
                        ultimo[nome] = agora
                        linha = linha_da_mensagem(texto, chave)
                        print(f"[{time.strftime('%H:%M:%S')}] Detectado: {linha} ({nota:.2f})")
                        enviar_alerta(MENSAGENS[nome], linha)
                        if ALERTA_TELA:
                            alerta_tela(nome)
                else:
                    ausente[nome] += 1
                    if ausente[nome] >= 3:   # sumiu de vez: pode alertar de novo
                        visivel[nome] = False
            time.sleep(INTERVALO)


if __name__ == "__main__":
    import traceback
    arg = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    try:
        carregar_opcoes()
        if arg == "autoteste":           # usado no build para checar o .exe
            sys.exit(autoteste())
        elif arg == "configurar":
            configurar()
        elif arg == "setup":
            setup()
        elif arg == "conectar":
            conectar()
        elif arg == "imagem":
            testar_imagem(sys.argv[2] if len(sys.argv) > 2 else "")
        elif arg == "servidor":
            mostrar_servidor()
        elif arg == "teste":
            if nuvem_configurada():
                print("Enviando alerta de teste...")
                enviar_alerta("Teste", "Se voce recebeu isto, esta tudo funcionando!",
                              teste=True, esperar=True)
        else:
            monitorar(debug=(arg == "debug"))
    except KeyboardInterrupt:
        print("\nEncerrado.")
    except Exception:
        print("\n=== ERRO ===")
        traceback.print_exc()
    input("\nAperte ENTER para fechar...")
