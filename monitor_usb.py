"""
monitor_usb.py — le sensores do LibreHardwareMonitor e manda pro ESP32
via USB Serial. Detecta o dispositivo sozinho (por VID/PID) e fica
esperando em segundo plano ate o cabo ser conectado.

USO (produto final, cliente so faz isso UMA vez):
    - Da duplo-clique no PainelPC.exe (ou nesse .py, se tiver Python
      instalado). Na primeira execucao ele se registra pra iniciar
      sozinho com o Windows. Depois disso o cliente nao precisa mais
      abrir nada: basta plugar o aparelho na USB que o painel liga.

Requisitos p/ rodar como .py (dev):
    pip install pyserial requests

Pra virar um .exe sem precisar Python instalado no PC do cliente:
    pip install pyinstaller
    pyinstaller --onefile --noconsole --name PainelPC monitor_usb.py
    (o executavel final fica em dist/PainelPC.exe)

Dica: no LibreHardwareMonitor tambem da pra marcar em Options
"Start Minimized" / iniciar junto com o Windows, pra ninguem precisar
abrir ele manualmente tambem.
"""

import json
import os
import sys
import time
import traceback

import requests
import serial
import serial.tools.list_ports

CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "PainelPC")
MARCADOR_INSTALADO = os.path.join(CONFIG_DIR, "autostart_ok.txt")
LOG_PATH = os.path.join(CONFIG_DIR, "log.txt")

LHM_URL = "http://localhost:8085/data.json"
BAUD = 115200
INTERVALO_SEGUNDOS = 0.5  # nao adianta ser menor que o intervalo de atualizacao do LibreHardwareMonitor

# VIDs (Vendor ID) dos chips USB-serial mais comuns em placas ESP32
VIDS_CONHECIDOS = {
    0x10C4,  # Silicon Labs CP210x
    0x1A86,  # WCH CH340 / CH9102
    0x303A,  # Espressif (USB nativo do ESP32-C3/S3)
}


def log(msg):
    """Imprime (se tiver console) e sempre grava num arquivo de log, ja
    que rodando com --noconsole nao da pra ver nada na tela."""
    linha = f"[{time.strftime('%H:%M:%S')}] {msg}"
    try:
        print(linha)
    except Exception:
        pass
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except Exception:
        pass


# ---------------- AUTO-INICIO COM O WINDOWS ----------------
def instalar_autostart():
    """Cria um atalho na pasta Startup do Windows pra esse programa abrir
    sozinho (minimizado, sem janela) toda vez que o usuario logar."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        if os.path.exists(MARCADOR_INSTALADO):
            return  # ja instalado antes, nao faz de novo

        startup = os.path.join(
            os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
        )

        if getattr(sys, "frozen", False):
            # rodando como .exe compilado (PyInstaller)
            alvo = sys.executable
            comando = f'"{alvo}"'
        else:
            # rodando como script .py: usa pythonw pra nao abrir janela preta
            pythonw = sys.executable.replace("python.exe", "pythonw.exe")
            if not os.path.exists(pythonw):
                pythonw = sys.executable
            script = os.path.abspath(__file__)
            comando = f'"{pythonw}" "{script}"'

        # "comando" ja vem com aspas em volta do(s) caminho(s) (necessario pra
        # rodar certo no Windows se o caminho tiver espaco). Pra colocar esse
        # texto DENTRO de uma string do VBScript, cada aspas precisa virar
        # duas ("") -- e so essa string inteira que fica entre aspas simples.
        # Sem esse escape, o .vbs fica com aspas duplicadas invalidas e da
        # erro de compilacao ("Fim da instrucao esperada").
        comando_escapado = comando.replace('"', '""')
        vbs_path = os.path.join(startup, "PainelPC_AutoStart.vbs")
        conteudo = f'CreateObject("Wscript.Shell").Run "{comando_escapado}", 0, False'
        with open(vbs_path, "w") as f:
            f.write(conteudo)

        with open(MARCADOR_INSTALADO, "w") as f:
            f.write("ok")

        print("Configurado para iniciar automaticamente com o Windows.")
    except Exception as e:
        # Nao trava o programa se por algum motivo nao conseguir instalar
        print(f"Aviso: nao consegui configurar o inicio automatico ({e}).")


# ---------------- DETECCAO DO ESP32 ----------------
def encontrar_porta_automatica():
    portas = list(serial.tools.list_ports.comports())
    if not portas:
        return None
    for p in portas:
        if p.vid in VIDS_CONHECIDOS:
            return p.device
    # nao achou por VID conhecido -- loga o que tem disponivel pra ajudar
    # a diagnosticar (VID pode nao estar na nossa lista)
    detalhes = ", ".join(f"{p.device} (vid={p.vid}, {p.description})" for p in portas)
    log(f"Nenhuma porta com VID conhecido. Portas disponiveis: {detalhes}")
    return None


def esperar_dispositivo():
    log("Procurando o ESP32 (aguardando USB)...")
    porta = encontrar_porta_automatica()
    while porta is None:
        time.sleep(2)
        porta = encontrar_porta_automatica()
    log(f"Dispositivo encontrado em {porta}")
    return porta


# ---------------- LEITURA DOS SENSORES ----------------
def buscar_sensores():
    log(f"Consultando {LHM_URL} ...")
    try:
        r = requests.get(
            LHM_URL,
            timeout=(2, 3),  # (conectar, ler resposta) em segundos
            headers={"Connection": "close"},  # evita reusar conexao com o servidor simples do LHM
        )
        r.raise_for_status()
        arvore = r.json()
        log(f"Resposta recebida ({len(r.content)} bytes).")
    except Exception as e:
        log(f"Erro ao consultar LibreHardwareMonitor em {LHM_URL}: {e}")
        return None

    dados = {}

    def percorrer(no):
        texto = no.get("Text", "")
        valor = no.get("Value", "")
        sensor_id = no.get("SensorId", "") or ""

        if texto and valor:
            v = valor.replace(",", ".")
            partes = v.split()
            if partes:
                try:
                    numero = float(partes[0])
                except ValueError:
                    numero = None

                if numero is not None:
                    eh_integrada = "integrated" in sensor_id.lower()

                    # numero > 5 descarta leituras baixas demais pra serem reais --
                    # o LibreHardwareMonitor as vezes reporta um valor passageiro
                    # perto de 0 nesse sensor (ex: durante o proprio ciclo de
                    # atualizacao dele). O display mostra a temperatura arredondada
                    # (sem casas decimais), entao ate um "0,3" passava pelo filtro
                    # antigo (numero > 0) e ainda aparecia como "0" na tela -- por
                    # isso o piso agora e 5, bem abaixo de qualquer CPU package real
                    # rodando, mas alto o suficiente pra pegar esses valores residuais.
                    # Se cair nesse caso, o "CPU=" simplesmente nao entra na linha
                    # desse ciclo e o ESP32 mantem o ultimo valor valido que recebeu.
                    if "CPU Package" in texto and "C" in v and "MHz" not in v and "cpuTemp" not in dados and numero > 5:
                        dados["cpuTemp"] = numero

                    if texto == "CPU Total" and "%" in v:
                        dados["cpuLoad"] = numero

                    # CPUs hibridas (Intel 12/13/14 gen) usam "P-Core #1" em vez
                    # de "CPU Core #1" -- aceita os dois formatos
                    if (texto == "CPU Core #1" or texto == "P-Core #1") and "MHz" in v:
                        dados["cpuClock"] = numero

                    # ignora GPU integrada (Intel/AMD) e prioriza a GPU dedicada
                    if "GPU Core" in texto and "C" in v and "MHz" not in v and not eh_integrada and "gpuTemp" not in dados and numero > 5:
                        dados["gpuTemp"] = numero

                    if "GPU Core" in texto and "%" in v and not eh_integrada and "gpuLoad" not in dados:
                        dados["gpuLoad"] = numero

                    # "GPU Memory Used" e o valor real de VRAM dedicada alocada
                    # (o mesmo que o GPU-Z mostra) -- nao confundir com os
                    # contadores "D3D Dedicated/Shared Memory Used" do Windows,
                    # que somam memoria compartilhada e podem ficar bem acima
                    # da VRAM real. Exige sensor_id comecando com /gpu-nvidia
                    # pra garantir que e a GPU dedicada NVIDIA, nao a
                    # integrada (Intel/AMD) nem outro contador generico.
                    # Em GPUs com pouca VRAM o LibreHardwareMonitor reporta
                    # esse sensor em MB em vez de GB -- aceita os dois e converte.
                    if (texto == "GPU Memory Used" and sensor_id.startswith("/gpu-nvidia")
                            and "vram" not in dados):
                        if "GB" in v:
                            dados["vram"] = numero
                        elif "MB" in v:
                            dados["vram"] = numero / 1024.0

                    # "Memory" sozinho e so a versao em % (Load); o valor em GB
                    # vem em "Memory Used" -- e precisa ser do /ram, nao do
                    # /vram (memoria virtual/paginacao, que conta a mais)
                    if texto == "Memory Used" and "GB" in v and sensor_id.startswith("/ram/data"):
                        dados["ram"] = numero

                    # percentual de uso da RAM fisica (nao confundir com
                    # /vram/load, que e memoria virtual/paginacao)
                    if texto == "Memory" and "%" in v and sensor_id.startswith("/ram/load"):
                        dados["ramPct"] = numero

        for filho in no.get("Children", []):
            percorrer(filho)

    try:
        percorrer(arvore)
    except Exception:
        log("Erro ao percorrer os sensores:\n" + traceback.format_exc())
        return None

    return dados


def montar_linha(dados):
    mapa = [
        ("cpuTemp", "CPU"),
        ("cpuLoad", "CPULOAD"),
        ("gpuTemp", "GPU"),
        ("gpuLoad", "GPULOAD"),
        ("cpuClock", "CLK"),
        ("ram", "RAM"),
        ("ramPct", "RAMPCT"),
        ("vram", "VRAM"),
    ]
    partes = [f"{tag}={dados[chave]:.1f}" for chave, tag in mapa if chave in dados]
    return ";".join(partes) + "\n"


# ---------------- LOOP PRINCIPAL ----------------
def main():
    instalar_autostart()

    while True:
        porta = esperar_dispositivo()
        try:
            with serial.Serial(porta, BAUD, timeout=2, write_timeout=2) as ser:
                time.sleep(2)  # espera o ESP32 estabilizar apos abrir a porta
                log(f"Conectado em {porta}, enviando dados a cada {INTERVALO_SEGUNDOS}s")
                while True:
                    try:
                        # se o dispositivo for desconectado, a escrita falha e cai pro except
                        dados = buscar_sensores()
                        if dados:
                            linha = montar_linha(dados)
                            ser.write(linha.encode())
                            log(f"Enviado: {linha.strip()}")
                        else:
                            log("Sem dados dos sensores nesse ciclo (ver erro acima).")
                    except serial.SerialException:
                        raise  # deixa o except de fora tratar (dispositivo desconectado)
                    except Exception:
                        log("Erro inesperado no loop principal:\n" + traceback.format_exc())
                    time.sleep(INTERVALO_SEGUNDOS)
        except serial.SerialException as e:
            log(f"Porta serial desconectada ou com erro: {e}")
            time.sleep(2)  # dispositivo foi desconectado, volta a esperar
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    main()
