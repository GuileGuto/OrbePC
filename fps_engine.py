"""
fps_engine.py -- FPS do jogo em primeiro plano, via PresentMon (Intel).

Como funciona: o PresentMon captura, pelo ETW do Windows, cada frame
"apresentado" por cada processo (mesma fonte dos overlays da NVIDIA e
do XTU). Este modulo roda o PresentMon em segundo plano lendo o CSV
pela saida padrao, conta quantos frames o processo EM PRIMEIRO PLANO
apresentou no ultimo segundo -- isso E' o FPS -- e entrega pro app.

Requisitos:
  - Rodar como administrador (o ETW exige -- o OrbePC ja abre elevado).
  - PresentMon.exe ao lado do OrbePC.exe (ou em %APPDATA%\\PainelPC).
    Download oficial (gratis, licenca MIT, permite distribuir junto):
    https://github.com/GameTechDev/PresentMon/releases
    Baixe o "PresentMon-<versao>-x64.exe" e renomeie para PresentMon.exe.

Se o PresentMon nao estiver presente, a metrica so mostra "--" no
display -- nada quebra. A captura ETW so e iniciada quando alguma tela
realmente usa a metrica de FPS (lazy), pra nao gastar CPU a toa.
"""

import os
import subprocess
import sys
import threading
import time
from collections import deque

_lock = threading.Lock()
_frames = deque(maxlen=2000)  # (timestamp_local, pid) -- ~2000 frames cobrem >1s ate a 500fps
_iniciado = False
_pronto = False
erro = None  # legivel pelo app pra diagnostico ("Ver log")


def _caminho_presentmon():
    candidatos = []
    if getattr(sys, "frozen", False):
        candidatos.append(os.path.dirname(sys.executable))          # pasta do OrbePC.exe
        candidatos.append(getattr(sys, "_MEIPASS", ""))             # empacotado via --add-binary
    candidatos.append(os.path.dirname(os.path.abspath(__file__)))   # rodando como .py (dev)
    candidatos.append(os.path.join(os.environ.get("APPDATA", ""), "PainelPC"))
    for pasta in candidatos:
        if not pasta:
            continue
        for nome in ("PresentMon.exe", "presentmon.exe"):
            c = os.path.join(pasta, nome)
            if os.path.exists(c):
                return c
    return None


def _pid_primeiro_plano():
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value or None
    except Exception:
        return None


def _thread_leitura(proc):
    """Le o CSV do PresentMon linha a linha. So precisamos de DUAS coisas
    de cada linha: que ela existe (1 linha = 1 frame apresentado) e o
    ProcessID -- por isso o parser tolera qualquer versao do PresentMon
    (v1/v2 mudam as colunas de tempo, mas ProcessID existe em todas)."""
    global erro
    try:
        idx_pid = None
        for linha in proc.stdout:
            linha = linha.strip()
            if not linha:
                continue
            if idx_pid is None:
                if "ProcessID" in linha:  # cabecalho do CSV
                    cabecalho = [c.strip() for c in linha.split(",")]
                    idx_pid = cabecalho.index("ProcessID")
                continue
            partes = linha.split(",")
            try:
                pid = int(partes[idx_pid])
            except (ValueError, IndexError):
                continue
            with _lock:
                _frames.append((time.time(), pid))
        erro = "PresentMon encerrou"
    except Exception as e:
        erro = f"leitura do PresentMon falhou: {e}"


def _thread_iniciar():
    """Sobe o PresentMon em segundo plano. Tenta as duas convencoes de
    flag (v2 usa --, v1 usa -) e fica com a que sobreviver."""
    global _pronto, erro
    exe = _caminho_presentmon()
    if exe is None:
        erro = ("PresentMon.exe nao encontrado -- baixe em "
                "github.com/GameTechDev/PresentMon/releases e coloque ao lado do OrbePC.exe")
        return

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for args in (["--output_stdout", "--stop_existing_session"],
                 ["-output_stdout", "-stop_existing_session"]):
        try:
            proc = subprocess.Popen([exe] + args, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True,
                                    creationflags=flags)
            time.sleep(2.0)
            if proc.poll() is not None:
                continue  # morreu na largada -- flags da outra versao
            threading.Thread(target=_thread_leitura, args=(proc,), daemon=True).start()
            _pronto = True
            erro = None
            return
        except Exception:
            continue
    erro = "PresentMon nao iniciou (versao incompativel?)"


def fps_atual():
    """FPS do aplicativo em primeiro plano no ultimo segundo, ou None se
    nao ha jogo rodando / PresentMon indisponivel. Primeira chamada
    dispara a inicializacao em segundo plano (lazy) e retorna None."""
    global _iniciado
    with _lock:
        if not _iniciado:
            _iniciado = True
            threading.Thread(target=_thread_iniciar, daemon=True).start()
            return None
    if not _pronto:
        return None

    pid = _pid_primeiro_plano()
    if not pid:
        return None
    agora = time.time()
    with _lock:
        n = sum(1 for (ts, p) in _frames if p == pid and agora - ts <= 1.0)
    # menos de 5 apresentacoes/s = janela comum (desktop), nao um jogo
    return float(n) if n >= 5 else None
