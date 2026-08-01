"""
orbepc_app.py -- app de bandeja + configuracoes do OrbePC. Evolucao do
antigo monitor_usb.py: continua lendo o LibreHardwareMonitor e mandando
os dados pro ESP32 via USB Serial, mas agora com:

  - icone na bandeja do Windows (status de conexao, pausar/retomar, log)
  - janela de configuracoes moderna (CustomTkinter): sidebar com paginas
    Metricas (cores + preview ao vivo do display), Telas (personalizadas),
    Sensores, Alertas e Geral
  - telas personalizadas: alem da tela classica, o usuario cria ate
    MAX_TELAS_CUSTOM telas extras (aneis + linhas escolhiveis), com
    rotacao automatica e "Proxima tela" na bandeja
  - deteccao de sensores em camadas (sensor_engine.py), resiliente a
    CPU/GPU de fabricantes diferentes -- veja sensor_engine.py pros
    detalhes de como isso funciona
  - leitura de sensores DIRETO da LibreHardwareMonitorLib (via
    pythonnet), sem precisar do LibreHardwareMonitor.exe aberto
    separado -- por isso o app agora pede elevacao (UAC) ao abrir, e o
    autostart usa o Agendador de Tarefas do Windows (em vez do .vbs
    simples de antes) pra poder iniciar ja com privilegios de admin

Requisitos (dev):
    pip install pyserial requests pystray Pillow pythonnet "HardwareMonitor>=1.2.0" customtkinter

    IMPORTANTE -- driver PawnIO: a partir da versao 1.2.0 do pacote
    HardwareMonitor (pip), a leitura de CPU (temperatura/energia via MSR)
    passou a depender do driver PawnIO em vez do WinRing0 antigo. Precisa
    instalar o runtime uma vez na maquina (nao vai dentro do .exe):
        winget install PawnIO
        (ou baixar o instalador em https://pawnio.eu/)
    Por que essa troca importa: desde a atualizacao de 2022 do Windows 11,
    a "lista de bloqueio de drivers vulneraveis" da Microsoft vem ATIVADA
    POR PADRAO em toda instalacao nova -- e o WinRing0x64.sys (embutido em
    versoes antigas da LibreHardwareMonitorLib) esta nessa lista (CVE-2020-
    14979). Numa maquina com essa lista ativa, ele e' bloqueado em
    silencio: o app abre elevado normalmente, GPU/RAM continuam lendo
    (nao dependem de MSR), mas CPU (temperatura e energia) simplesmente
    nao aparece nos sensores -- sem erro nenhum no log. Isso NAO tem
    relacao com a "Integridade de Memoria" do Windows Seguranca (pode
    estar desligada e o bloqueio acontece do mesmo jeito, ja que a lista
    e' independente desse toggle). O PawnIO e' assinado e nao entra
    nessa lista, entao resolve de forma definitiva. Sintoma clássico pra
    reconhecer isso num PC de cliente: aba Sensores mostra "CPU ·
    temperatura: não encontrado" mas GPU/VRAM/RAM normais, e o
    "Exportar sensores" nao mostra NENHUMA entrada em /intelcpu/.../
    temperature/ ou /amdcpu/.../temperature/ (nem com valor None -- o
    sensor simplesmente nao existe na lista, porque o driver que o
    alimentaria nunca carregou).

Pra virar .exe (rodar dentro da pasta, com sensor_engine.py do lado --
o PyInstaller acha ele sozinho, e' um import normal, nao precisa de
--add-data):
    python -m PyInstaller --onefile --noconsole --name OrbePC --icon orbepc_icon.ico ^
        --collect-all HardwareMonitor --collect-all pythonnet --collect-all customtkinter ^
        orbepc_app.py
    (o executavel final fica em dist/OrbePC.exe, ja com o icone aplicado)

    IMPORTANTE -- PawnIO no PC do CLIENTE: desde que garantir_pawnio() foi
    adicionado (chamado no inicio de main(), logo apos elevar), o proprio
    OrbePC.exe instala o driver PawnIO sozinho e em silencio na primeira
    vez que roda, se ainda nao estiver presente -- o cliente NAO precisa
    baixar nada do site do PawnIO nem rodar instalador separado. Pra isso
    funcionar, o PawnIO_setup.exe precisa estar na pasta do projeto ANTES
    de gerar o build (baixe uma vez em
    https://github.com/namazso/PawnIO.Setup/releases/latest/download/PawnIO_setup.exe
    e salve como "PawnIO_setup.exe" do lado do orbepc_app.py) -- o
    OrbePC.spec ja detecta o arquivo e embute ele dentro do .exe sozinho
    (build com `python -m PyInstaller OrbePC.spec` pra isso valer; o
    comando "raw" abaixo, com --onefile direto, precisaria do flag
    --add-binary "PawnIO_setup.exe;." adicionado na mao). Sem o arquivo
    presente no build, o app cai no aviso antigo no log.txt pedindo
    instalacao manual -- nao quebra nada, so perde a automacao.

    IMPORTANTE: --collect-all HardwareMonitor e obrigatorio. O pacote
    HardwareMonitor carrega LibreHardwareMonitorLib.dll de dentro da
    propria pasta do pacote (HardwareMonitor/lib/...) -- sem essa flag
    o PyInstaller nao empacota esse .dll (so pega .py), e o app fica
    em loop de erro "Unable to find assembly ...LibreHardwareMonitorLib.dll"
    mesmo rodando como administrador.

    (--collect-all customtkinter tambem e' obrigatorio: a lib carrega
    temas .json e assets de dentro da propria pasta do pacote)

    (--collect-all esptool tambem e' obrigatorio a partir da funcionalidade
    de atualizar firmware pelo app: o pacote carrega os "stub flashers"
    dele de dentro da propria pasta, igual HardwareMonitor faz com o .dll)

    RECOMENDADO: pra nao ter que lembrar de todas essas flags -- e pra
    embutir o PawnIO_setup.exe automaticamente -- use o OrbePC.spec em vez
    do comando cru acima:
        python -m PyInstaller OrbePC.spec
    (mesmo resultado final em dist/OrbePC.exe, so que o .spec ja sabe
    detectar o PawnIO_setup.exe sozinho -- ver comentarios la.)

FPS (opcional): a metrica "Jogo · FPS" das telas personalizadas usa o
PresentMon da Intel (licenca MIT). Baixe o PresentMon-<versao>-x64.exe em
github.com/GameTechDev/PresentMon/releases, renomeie para PresentMon.exe
e deixe na MESMA pasta do OrbePC.exe (ou em %APPDATA%\\PainelPC). Sem ele,
a metrica so mostra "--". Detalhes em fps_engine.py.

ATUALIZACAO DE FIRMWARE PELO APP: a aba "Firmware" da janela de
configuracoes grava o painel_pc_esp32c3.ino direto no ESP32 (via esptool),
sem precisar do Arduino IDE no PC do cliente. Nao tem firmware embutido no
.exe -- o proprio usuario aponta o arquivo .bin (Selecionar) e confirma a
gravacao (Aplicar). Pra gerar esse .bin depois de editar o .ino: Arduino
IDE > Sketch > Exportar Binario Compilado, com a opcao de exportar como um
unico arquivo combinado ("merged binary") se a versao do core tiver essa
opcao -- e' esse arquivo que se seleciona na aba Firmware. Detalhes em
firmware_engine.py.
"""

import json
import os
import subprocess
import sys
import threading
import time
import traceback

# tkinter/customtkinter sao importados sob demanda (dentro das funcoes que
# realmente constroem janelas), nao aqui no topo -- assim o resto do modulo
# (config, deteccao de sensores, montagem da linha serial, autostart)
# continua testavel isoladamente em qualquer ambiente, mesmo sem GUI.

import serial
import serial.tools.list_ports

import sensor_engine as se
import fps_engine
import clima_engine
import firmware_engine
import atualizacao_engine

# versao deste app -- comparada com a tag da release mais recente no
# GitHub (ver atualizacao_engine.py) pra avisar quando tiver uma nova.
# Suba isso a cada release publicada no repositorio.
APP_VERSAO = "1.4.0"

# ---------------------------------------------------------------------
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "PainelPC")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
LOG_PATH = os.path.join(CONFIG_DIR, "log.txt")
VBS_PATH = None  # calculado em definir_autostart/autostart_esta_ativo

BAUD = 115200
VIDS_CONHECIDOS = {0x10C4, 0x1A86, 0x303A}

CONFIG_PADRAO = {
    "colorCpu": "00DC00",
    "colorGpu": "0090FF",
    "ramLimitPct": 90.0,
    "brilhoPct": 100.0,  # brilho do backlight (%), enviado como BRIGHT= no protocolo
    "updateIntervalSec": 1.0,
    "autostart": False,
    "sensorOverrides": {},
    # telas personalizadas: ate MAX_TELAS_CUSTOM dicts no formato
    # {"anel1": id|None, "anel2": id|None, "linhas": [id|None x4]}
    # (a tela 1, classica, e fixa e nao entra aqui)
    "telasCustom": [],
    "rotacaoSec": 0,  # troca automatica de tela a cada N segundos (0 = desligada)
    "atalhoTela": "",  # atalho global de teclado pra trocar de tela (ex: "ctrl+alt+n"; "" = desligado)
    # clima (Open-Meteo): cidade escolhida na aba Geral
    "climaCidade": "",
    "climaLat": None,
    "climaLon": None,
}


LOG_MAX_BYTES = 2 * 1024 * 1024  # rotaciona em 2MB -- ja tivemos um log.txt de 9.9MB


def log(msg):
    linha = f"[{time.strftime('%H:%M:%S')}] {msg}"
    try:
        print(linha)
    except Exception:
        pass
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        # rotacao simples: passou do limite, vira log.txt.old (1 geracao)
        try:
            if os.path.getsize(LOG_PATH) > LOG_MAX_BYTES:
                antigo = LOG_PATH + ".old"
                if os.path.exists(antigo):
                    os.remove(antigo)
                os.replace(LOG_PATH, antigo)
        except OSError:
            pass
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------
# CONFIGURACAO -- carregada uma vez, mantida em memoria (protegida por
# lock porque a interface roda numa thread e o loop de sensores noutra),
# salva em disco a cada mudanca pra persistir entre execucoes.
# ---------------------------------------------------------------------
class Config:
    def __init__(self):
        self._lock = threading.Lock()
        self._dados = dict(CONFIG_PADRAO)
        self.carregar()

    def carregar(self):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                salvo = json.load(f)
            with self._lock:
                self._dados.update(salvo)
        except FileNotFoundError:
            pass
        except Exception:
            log("Erro ao carregar config, usando padrao:\n" + traceback.format_exc())

    def salvar(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with self._lock:
                copia = dict(self._dados)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(copia, f, indent=2, ensure_ascii=False)
        except Exception:
            log("Erro ao salvar config:\n" + traceback.format_exc())

    def get(self, chave, padrao=None):
        with self._lock:
            return self._dados.get(chave, padrao)

    def set(self, chave, valor):
        with self._lock:
            self._dados[chave] = valor
        self.salvar()

    def set_override(self, metrica, sensor_id):
        with self._lock:
            self._dados.setdefault("sensorOverrides", {})[metrica] = sensor_id
        self.salvar()

    def overrides(self):
        with self._lock:
            return dict(self._dados.get("sensorOverrides", {}))

    def exportar(self, caminho):
        """Salva uma copia de TODAS as configuracoes atuais (cores, telas
        personalizadas, overrides de sensor, alertas, atalho, cidade do
        clima etc.) num arquivo .json a parte, escolhido pelo usuario --
        serve de backup antes de formatar o PC ou pra levar a config pra
        outra maquina. Nao mexe no config.json de verdade, so le e copia."""
        with self._lock:
            copia = dict(self._dados)
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(copia, f, indent=2, ensure_ascii=False)

    def importar(self, caminho):
        """Le um .json exportado por exportar() e substitui a configuracao
        atual por ele (mesclado sobre os padroes, entao chaves que nao
        existiam na epoca do backup nao ficam faltando). Levanta ValueError
        se o arquivo nao parecer um backup valido -- o chamador decide como
        mostrar isso na UI. Persiste em disco (salvar()) antes de retornar,
        mas os widgets ja abertos na janela de config NAO se atualizam
        sozinhos -- o chamador deve orientar a reabrir o OrbePC."""
        with open(caminho, "r", encoding="utf-8") as f:
            novo = json.load(f)
        if not isinstance(novo, dict):
            raise ValueError("Arquivo de configuração inválido (não é um backup do OrbePC).")
        with self._lock:
            self._dados = dict(CONFIG_PADRAO)
            self._dados.update(novo)
        self.salvar()


config = Config()


# ---------------------------------------------------------------------
# ELEVACAO (UAC) -- a leitura direta de sensores via LibreHardwareMonitorLib
# exige administrador (mesma exigencia que o LibreHardwareMonitor.exe
# sempre teve). Sem isso a maioria dos sensores vem vazia.
# ---------------------------------------------------------------------
def esta_elevado():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _comando_executavel():
    """Monta (executavel, [argumentos]) pra relançar o app -- funciona
    tanto rodando como .py (dev) quanto ja empacotado em .exe."""
    if getattr(sys, "frozen", False):
        return sys.executable, []
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    return pythonw, [os.path.abspath(__file__)]


def elevar_e_reiniciar():
    """Relanca o processo pedindo elevacao (aparece o UAC do Windows) e
    encerra a instancia atual (nao-elevada). Se o usuario recusar o UAC,
    so loga e sai -- nao fica tentando de novo em loop."""
    import ctypes
    exe, args = _comando_executavel()
    params = " ".join(f'"{a}"' for a in args)
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    except Exception:
        log("Elevacao (UAC) recusada ou falhou -- OrbePC precisa rodar como administrador pra ler os sensores.")
    sys.exit(0)


# ---------------------------------------------------------------------
# DRIVER PAWNIO -- a leitura de CPU (temperatura/energia via MSR) na
# HardwareMonitor>=1.2.0 depende do driver PawnIO (substituiu o WinRing0
# antigo, que o Windows passou a bloquear por padrao -- ver nota grande
# no topo do arquivo). O PawnIO em si e' um runtime que precisa estar
# INSTALADO no Windows (nao da pra so "importar" ele como uma lib comum),
# mas isso nao precisa virar trabalho manual pro cliente: o instalador
# oficial (PawnIO_setup.exe, assinado, MIT) e' rodado escondido, uma
# unica vez, pelo proprio OrbePC -- na pratica o usuario so continua
# dando duplo-clique no OrbePC.exe de sempre. Mesma tecnica que o
# FanControl e o OpenRGB usam.
#
# Pra isso funcionar, o PawnIO_setup.exe precisa estar disponivel pro
# app achar em tempo de execucao -- baixe uma vez em
#   https://github.com/namazso/PawnIO.Setup/releases/latest/download/PawnIO_setup.exe
# e deixe do lado do orbepc_app.py (dev) ou do OrbePC.exe (produto). Pra
# empacotar ele DENTRO do .exe (instalador nao aparece nem como arquivo
# solto na pasta do cliente), adicione ao comando do PyInstaller:
#   --add-binary "PawnIO_setup.exe;."
# (o _caminho_pawnio_instalador() abaixo acha o arquivo nos dois casos --
# embutido via _MEIPASS ou solto do lado do executavel/script, mesmo
# esquema ja usado por fps_engine._caminho_presentmon()).
NOME_SERVICO_PAWNIO = "PawnIO"


def _caminho_pawnio_instalador():
    candidatos = []
    if getattr(sys, "frozen", False):
        candidatos.append(os.path.dirname(sys.executable))
        candidatos.append(getattr(sys, "_MEIPASS", ""))
    candidatos.append(os.path.dirname(os.path.abspath(__file__)))
    for pasta in candidatos:
        if not pasta:
            continue
        c = os.path.join(pasta, "PawnIO_setup.exe")
        if os.path.exists(c):
            return c
    return None


def pawnio_instalado():
    """Confere se o driver ja esta registrado no Windows (servico no
    registro) -- checagem so-leitura, nao precisa admin pra isso."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             rf"SYSTEM\CurrentControlSet\Services\{NOME_SERVICO_PAWNIO}"):
            return True
    except FileNotFoundError:
        return False
    except Exception:
        return False  # na duvida, tenta instalar -- o instalador e' idempotente


def garantir_pawnio():
    """Instala o driver PawnIO em silencio se ainda nao estiver presente.
    Chamado uma vez no startup, ja com o processo elevado (o instalador
    tambem exige admin pra registrar o servico). Nunca derruba o app: se
    o instalador nao for encontrado ou falhar, so loga -- a deteccao de
    sensores continua funcionando pro que nao depende de MSR (GPU/RAM),
    e a CPU fica sem valor ate o driver ser resolvido.

    Alem de logar, guarda um resumo legivel em estado.pawnio_aviso (None
    se tudo certo) -- a aba Sensores da UI le esse campo pra mostrar um
    aviso proativo (com botao "Tentar reinstalar") em vez do usuario so
    descobrir o problema procurando no log.txt, como aconteceu na pratica
    antes desse campo existir."""
    if pawnio_instalado():
        estado.atualizar(pawnio_aviso=None)
        return
    instalador = _caminho_pawnio_instalador()
    if instalador is None:
        aviso = ("Driver PawnIO não encontrado e não está empacotado com este "
                  "app -- CPU pode ficar sem temperatura/energia. Baixe em "
                  "pawnio.eu e instale manualmente, ou clique em \"Tentar "
                  "reinstalar\" depois de colocar o PawnIO_setup.exe do lado "
                  "do executável.")
        log(aviso)
        estado.atualizar(pawnio_aviso=aviso)
        return
    try:
        log("Driver PawnIO nao encontrado -- instalando em segundo plano...")
        resultado = subprocess.run(
            [instalador, "-install", "-silent"],
            capture_output=True, timeout=60, creationflags=_sem_janela(),
        )
        if resultado.returncode == 0 and pawnio_instalado():
            log("PawnIO instalado com sucesso.")
            estado.atualizar(pawnio_aviso=None)
        else:
            aviso = ("Driver PawnIO não pôde ser instalado automaticamente "
                      f"(código {resultado.returncode}) -- CPU pode ficar sem "
                      "temperatura/energia. Veja o log.txt (bandeja → Ver log) "
                      "pra detalhes, ou tente reinstalar manualmente em pawnio.eu.")
            log(f"PawnIO_setup.exe rodou mas o servico nao apareceu no registro "
                f"(codigo {resultado.returncode}). stderr: "
                f"{resultado.stderr.decode(errors='replace')[:300]}")
            estado.atualizar(pawnio_aviso=aviso)
    except Exception:
        log("Erro ao instalar o PawnIO:\n" + traceback.format_exc())
        estado.atualizar(pawnio_aviso="Erro ao instalar o driver PawnIO -- veja o log.txt (bandeja → Ver log).")


# ---------------------------------------------------------------------
# INSTANCIA UNICA -- mutex nomeado do Windows. Evita duas copias reais do
# app brigando pela mesma porta serial e pelo driver de sensores (ex:
# autostart do Agendador + clique no atalho). Obs: os "2 processos
# OrbePC.exe" no Gerenciador de Tarefas NAO sao duas instancias -- e' o
# lancador do PyInstaller --onefile + o processo real; isso e' normal.
# O handle do mutex fica vivo o processo inteiro (guardado no atributo
# da funcao) e o Windows libera sozinho quando o processo morre.
# ---------------------------------------------------------------------
def ja_esta_rodando():
    try:
        import ctypes
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\OrbePC_InstanciaUnica")
        ja_esta_rodando._handle = handle  # impede o garbage collector de fechar
        return ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return False  # na duvida, deixa abrir


# ---------------------------------------------------------------------
# AUTO-INICIO COM O WINDOWS -- via Agendador de Tarefas (schtasks), com
# "executar com privilegios mais altos", ja que o app precisa abrir
# elevado. O metodo antigo (.vbs na pasta Startup) nao eleva sozinho,
# entao nao serve mais -- definir_autostart() tambem limpa um .vbs
# deixado por uma versao anterior, se sobrou algum.
# ---------------------------------------------------------------------
NOME_TAREFA = "OrbePC_AutoStart"


def _sem_janela():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _remover_vbs_antigo():
    try:
        startup = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
        vbs_antigo = os.path.join(startup, "OrbePC_AutoStart.vbs")
        if os.path.exists(vbs_antigo):
            os.remove(vbs_antigo)
    except Exception:
        pass


def autostart_esta_ativo():
    try:
        resultado = subprocess.run(
            ["schtasks", "/query", "/tn", NOME_TAREFA],
            capture_output=True, creationflags=_sem_janela(),
        )
        return resultado.returncode == 0
    except Exception:
        return False


def definir_autostart(ativo):
    _remover_vbs_antigo()
    try:
        if not ativo:
            subprocess.run(
                ["schtasks", "/delete", "/tn", NOME_TAREFA, "/f"],
                capture_output=True, creationflags=_sem_janela(),
            )
            return True

        exe, args = _comando_executavel()
        comando = " ".join([f'"{exe}"'] + [f'"{a}"' for a in args])
        resultado = subprocess.run(
            ["schtasks", "/create", "/tn", NOME_TAREFA, "/tr", comando,
             "/sc", "onlogon", "/rl", "highest", "/f"],
            capture_output=True, creationflags=_sem_janela(),
        )
        if resultado.returncode != 0:
            log("Erro ao criar tarefa de autostart:\n" + resultado.stderr.decode(errors="replace"))
            return False
        return True
    except Exception:
        log("Erro ao configurar autostart:\n" + traceback.format_exc())
        return False


# ---------------------------------------------------------------------
# DETECCAO DA PORTA SERIAL
# ---------------------------------------------------------------------
def encontrar_porta_automatica():
    portas = list(serial.tools.list_ports.comports())
    for p in portas:
        if p.vid in VIDS_CONHECIDOS:
            return p.device
    return None


# ---------------------------------------------------------------------
# ESTADO COMPARTILHADO (lido pela UI, escrito pela thread de sensores) --
# usado pro icone da bandeja e pra aba Sensores mostrarem status atual
# ---------------------------------------------------------------------
class Estado:
    def __init__(self):
        self.lock = threading.Lock()
        self.conectado = False
        self.pausado = False
        self.porta = None
        self.pagina = 0
        self.trocar_tela = False  # pedido manual de "Proxima tela" (bandeja)
        self.ultima_deteccao = {}
        self.ultimo_erro = None
        self.versao_firmware = None  # preenchida ao ler "DBG:versao=..." do ESP32
        self.pawnio_aviso = None  # preenchido por garantir_pawnio() se algo deu errado
        self.atualizacao_disponivel = None  # dict {"versao","url"} ou None -- ver atualizacao_engine
        self.firmware_disponivel = None  # dict {"versao","url","nome_arquivo"} ou None -- ver atualizacao_engine

    def atualizar(self, **kwargs):
        with self.lock:
            for k, v in kwargs.items():
                setattr(self, k, v)

    def consumir_troca_manual(self):
        with self.lock:
            pedido = self.trocar_tela
            self.trocar_tela = False
            return pedido

    def snapshot(self):
        with self.lock:
            return {
                "conectado": self.conectado,
                "pausado": self.pausado,
                "porta": self.porta,
                "pagina": self.pagina,
                "ultima_deteccao": dict(self.ultima_deteccao),
                "ultimo_erro": self.ultimo_erro,
                "versao_firmware": self.versao_firmware,
                "pawnio_aviso": self.pawnio_aviso,
                "atualizacao_disponivel": self.atualizacao_disponivel,
                "firmware_disponivel": self.firmware_disponivel,
            }


estado = Estado()

# sinalizado pelo fluxo de "Atualizar firmware" (ver firmware_engine.py e a
# aba Geral) enquanto uma gravacao esta em andamento -- thread_monitoramento
# respeita essa flag pra soltar a porta COM por completo (fechar de verdade,
# nao so pausar o envio), ja que o esptool precisa de acesso exclusivo a ela
pausar_para_flash = threading.Event()


# ---------------------------------------------------------------------
# ATALHO GLOBAL DE TECLADO -- RegisterHotKey do Windows via ctypes (sem
# dependencia nova). Atalho global de verdade: dispara com o app
# minimizado e ate dentro de jogos. Exigencia da API: registrar e
# escutar mensagens na MESMA thread -- por isso a thread propria com
# message loop; pra trocar o atalho, a thread antiga recebe WM_QUIT e
# uma nova sobe com a combinacao nova.
# ---------------------------------------------------------------------
_MODIFICADORES = {"ctrl": 0x2, "alt": 0x1, "shift": 0x4, "win": 0x8}


def _vk_de_tecla(nome):
    """Converte o nome de uma tecla ('N', 'F9', 'PGUP') no codigo VK."""
    nome = nome.strip().upper()
    # so A-Z e 0-9 (isalnum() aceitaria acentuadas tipo 'ç', que nao tem VK direto)
    if len(nome) == 1 and ("A" <= nome <= "Z" or "0" <= nome <= "9"):
        return ord(nome)
    if nome.startswith("F") and nome[1:].isdigit():
        n = int(nome[1:])
        if 1 <= n <= 24:
            return 0x70 + n - 1
    especiais = {"SPACE": 0x20, "TAB": 0x09, "HOME": 0x24, "END": 0x23,
                 "PGUP": 0x21, "PGDOWN": 0x22, "INS": 0x2D, "DEL": 0x2E,
                 "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27}
    return especiais.get(nome)


class AtalhoGlobal:
    def __init__(self, ao_disparar):
        self.ao_disparar = ao_disparar
        self._tid = None
        self._lock = threading.Lock()

    def aplicar(self, combo):
        """Registra a combinacao (ex: 'ctrl+alt+n'); '' desliga o atalho."""
        with self._lock:
            self._parar()
            if combo:
                threading.Thread(target=self._loop, args=(combo,), daemon=True).start()

    def _parar(self):
        if self._tid:
            try:
                import ctypes
                ctypes.windll.user32.PostThreadMessageW(self._tid, 0x0012, 0, 0)  # WM_QUIT
            except Exception:
                pass
            self._tid = None

    def _loop(self, combo):
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
        except Exception:
            return  # fora do Windows (dev/teste) -- atalho simplesmente inativo

        mods = 0x4000  # MOD_NOREPEAT: segurar a combinacao nao fica trocando em loop
        vk = None
        for parte in combo.split("+"):
            parte = parte.strip().lower()
            if parte in _MODIFICADORES:
                mods |= _MODIFICADORES[parte]
            elif parte:
                vk = _vk_de_tecla(parte)
        if vk is None:
            log(f"Atalho invalido, ignorado: '{combo}'")
            return

        self._tid = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, 1, mods, vk):
            log(f"Nao consegui registrar o atalho '{combo}' -- provavelmente ja esta em uso por outro programa.")
            self._tid = None
            return
        log(f"Atalho global ativo: {combo}")

        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312:  # WM_HOTKEY
                    try:
                        self.ao_disparar()
                    except Exception:
                        pass
        finally:
            user32.UnregisterHotKey(None, 1)


atalho_global = AtalhoGlobal(lambda: estado.atualizar(trocar_tela=True))


# ---------------------------------------------------------------------
# MONTAGEM DA LINHA SERIAL
# ---------------------------------------------------------------------
def montar_linha(deteccao):
    mapa = [
        ("cpuTemp", "CPU"), ("cpuLoad", "CPULOAD"),
        ("gpuTemp", "GPU"), ("gpuLoad", "GPULOAD"),
        ("cpuClock", "CLK"), ("ram", "RAM"),
        ("ramPct", "RAMPCT"), ("vram", "VRAM"),
    ]
    partes = []
    for chave, tag in mapa:
        v = deteccao.get(chave, {}).get("valor")
        if v is not None:
            partes.append(f"{tag}={v:.1f}")

    partes.append(f"COLORCPU={config.get('colorCpu')}")
    partes.append(f"COLORGPU={config.get('colorGpu')}")
    partes.append(f"LIMITERAM={config.get('ramLimitPct'):.1f}")
    partes.append(f"BRIGHT={config.get('brilhoPct', 100.0):.0f}")
    if estado.snapshot().get("versao_firmware") is None:
        # ainda nao sabemos a versao do firmware conectado -- pergunta a
        # cada pacote ate a resposta chegar (ver REQVERSAO no .ino). Para
        # sozinho assim que thread_monitoramento capturar o DBG:versao=
        # (nao fica perguntando pra sempre).
        partes.append("REQVERSAO=1")

    return ";".join(partes) + "\n"


# ---------------------------------------------------------------------
# TELAS PERSONALIZADAS -- alem da tela classica (fixa), o usuario cria
# ate MAX_TELAS_CUSTOM telas extras, cada uma com 2 aneis (metricas em %)
# e 4 linhas de texto, escolhidas na aba "Telas". O firmware nao sabe o
# que esta mostrando: recebe PAGE=n + R1/R2 (aneis) + L1..L4 (textos ja
# formatados aqui) e so desenha.
# ---------------------------------------------------------------------
MAX_TELAS_CUSTOM = 5  # + a tela classica = 6; acima disso a rotacao vira carrossel confuso


def _tela_tem_conteudo(tela):
    return bool(tela.get("anel1") or tela.get("anel2") or any(tela.get("linhas") or []))


def telas_ativas():
    """Somente telas custom com pelo menos uma vaga preenchida. Tela
    recem-criada (ainda toda vazia) NAO entra na rotacao nem no "Proxima
    tela" -- senao o display alterna pra uma tela "quebrada" so com a
    escala e o OrbePC, parecendo bug (aconteceu na v1 do recurso)."""
    return [t for t in (config.get("telasCustom") or []) if _tela_tem_conteudo(t)]


# metricas que podem alimentar os ANEIS (precisam ser 0-100%)
METRICAS_ANEL = {
    "cpuLoad":        "CPU · uso (%)",
    "gpuLoad":        "GPU · uso (%)",
    "ramPct":         "RAM · uso (%)",
    "vramPct":        "VRAM · uso (%)",
    "discoPct":       "Disco · espaço usado (%)",
    "discoAtividade": "Disco · atividade (%)",  # o "uso de disco" do Gerenciador de Tarefas
}

# metricas de LINHA: id -> (rotulo no dropdown, formatador valor->texto).
# Textos com largura fixa de proposito (mesma tecnica da tela classica:
# o fundo do proprio texto apaga o valor antigo, sem piscar). O '~' vira
# o simbolo de grau (char 248) na fonte do display.
METRICAS_LINHA = {
    "cpuTemp":    ("CPU · temperatura",   lambda v: f"CPU {v:3.0f}~C"),
    "gpuTemp":    ("GPU · temperatura",   lambda v: f"GPU {v:3.0f}~C"),
    "ram":        ("RAM · GB",            lambda v: f"RAM {v:4.1f} GB"),
    "vram":       ("VRAM · GB",           lambda v: f"VRAM{v:4.1f} GB"),
    "ramPct":     ("RAM · %",             lambda v: f"RAM  {v:3.0f} %"),
    "vramPct":    ("VRAM · %",            lambda v: f"VRAM {v:3.0f} %"),
    "cpuClock":   ("CPU · clock",         lambda v: f"CPU {v:4.0f}MHz"),
    "gpuClock":   ("GPU · clock",         lambda v: f"GPU {v:4.0f}MHz"),
    "discoTemp":      ("Disco · temperatura",       lambda v: f"SSD {v:3.0f}~C"),
    "discoPct":       ("Disco · espaço usado (%)",  lambda v: f"SSD  {v:3.0f} %"),
    "discoAtividade": ("Disco · atividade (%)",     lambda v: f"DSK  {v:3.0f} %"),
    "discoRead":  ("Disco · leitura",     lambda v: f"LER{v:6.1f}MB"),
    "discoWrite": ("Disco · escrita",     lambda v: f"GRV{v:6.1f}MB"),
    "netDown":    ("Rede · download",     lambda v: f"DW {v:6.2f}MB"),
    "netUp":      ("Rede · upload",       lambda v: f"UP {v:6.2f}MB"),
    "fan":        ("Fan · RPM",           lambda v: f"FAN {v:4.0f}RPM"),
    "hora":       ("Relógio do PC",       None),  # calculadas aqui no app,
    "uptime":     ("Tempo ligado",        None),  # nao vem de sensor
    "fps":        ("Jogo · FPS",          None),  # via PresentMon (fps_engine)
    "climaTemp":  ("Clima · temperatura", None),  # via Open-Meteo (clima_engine),
    "climaCond":  ("Clima · condição",    None),  # cidade escolhida na aba Geral
    "climaUmid":  ("Clima · umidade",     None),
}


def _valor_metrica_local(metrica_id):
    """Metricas que nao vem de sensor nenhum -- calculadas na hora."""
    if metrica_id == "fps":
        # FPS do jogo em primeiro plano (PresentMon). Sem jogo rodando ou
        # sem PresentMon.exe instalado, mostra "--" -- nada quebra.
        v = fps_engine.fps_atual()
        return f"FPS  {v:4.0f}" if v is not None else "FPS    --"
    if metrica_id in ("climaTemp", "climaCond", "climaUmid"):
        clima = clima_engine.atual()
        if metrica_id == "climaTemp":
            return f"T. Ext:{clima['temp']:3.0f}~C" if clima else "T. Ext: --~C"
        if metrica_id == "climaUmid":
            return (f"UMID {clima['umid']:3.0f} %" if clima and clima["umid"] >= 0
                    else "UMID  -- %")
        # condicao (SOL/CHUVA/...) centralizada em largura fixa de 10 --
        # a largura constante evita fantasma de texto no display
        return f"{clima['cond'][:10]:^10}" if clima else "    --    "
    if metrica_id == "hora":
        return time.strftime("  %H:%M:%S")
    if metrica_id == "uptime":
        try:
            import ctypes
            ms = ctypes.windll.kernel32.GetTickCount64()
            h, m = int(ms // 3600000), int(ms % 3600000 // 60000)
            return f"LIGADO{h:3d}h{m:02d}" if h < 1000 else f"LIGADO {h:4d}h"
        except Exception:
            return None
    return None


def _sanitizar_linha(texto):
    """';' e '=' quebrariam o protocolo serial -- nunca deixa passar."""
    return texto.replace(";", ",").replace("=", ":")


def montar_linha_pagina(deteccao, pagina):
    """Monta a linha serial da pagina atual: PAGE=0 e a tela classica
    (protocolo antigo intacto), PAGE>=1 sao as telas personalizadas
    ATIVAS (as vazias ficam de fora -- ver telas_ativas())."""
    telas = telas_ativas()
    if pagina <= 0 or pagina > len(telas):
        return "PAGE=0;" + montar_linha(deteccao)

    tela = telas[pagina - 1]
    partes = [f"PAGE={pagina}"]

    def v(mid):
        return deteccao.get(mid, {}).get("valor") if mid else None

    for chave_cfg, tag in (("anel1", "R1"), ("anel2", "R2")):
        val = v(tela.get(chave_cfg))
        if val is not None:
            partes.append(f"{tag}={val:.1f}")

    linhas = (tela.get("linhas") or [None] * 4)[:4]
    for i, mid in enumerate(linhas, start=1):
        texto = ""
        if mid:
            local = _valor_metrica_local(mid)
            if local is not None:
                texto = local
            else:
                entrada = METRICAS_LINHA.get(mid)
                val = v(mid)
                if entrada and entrada[1] and val is not None:
                    texto = entrada[1](val)
        partes.append(f"L{i}={_sanitizar_linha(texto)}")

    partes.append(f"COLORCPU={config.get('colorCpu')}")
    partes.append(f"COLORGPU={config.get('colorGpu')}")
    partes.append(f"LIMITERAM={config.get('ramLimitPct'):.1f}")
    partes.append(f"BRIGHT={config.get('brilhoPct', 100.0):.0f}")
    if estado.snapshot().get("versao_firmware") is None:
        # ainda nao sabemos a versao do firmware conectado -- pergunta a
        # cada pacote ate a resposta chegar (ver REQVERSAO no .ino). Para
        # sozinho assim que thread_monitoramento capturar o DBG:versao=
        # (nao fica perguntando pra sempre).
        partes.append("REQVERSAO=1")
    return ";".join(partes) + "\n"


# ---------------------------------------------------------------------
# FONTE DE SENSORES -- um unico Computer (LibreHardwareMonitorLib) pro
# app inteiro. NAO abrir mais de um: o acesso direto a hardware usa um
# driver de kernel (WinRing0/PawnIO) que nao aguenta duas instancias
# mexendo nele ao mesmo tempo -- isso foi o que derrubava o processo
# inteiro (sem excecao Python pra pegar) quando a aba Sensores abria um
# segundo Computer enquanto a thread de monitoramento ja tinha um
# aberto e rodando. Toda leitura (da thread de fundo OU da aba Sensores)
# passa por aqui, protegida por lock.
# ---------------------------------------------------------------------
INTERVALO_UPDATE_LENTO = 30.0  # s entre updates de Storage -- a leitura
                               # SMART pode travar por segundos em muitos
                               # discos; uso/temperatura mudam devagar,
                               # entao 30s de defasagem nao faz falta


class FonteSensores:
    def __init__(self):
        self.lock = threading.Lock()
        self.computer = None
        self._ultimo_update_lento = 0.0

    def ler(self, overrides):
        with self.lock:
            if self.computer is None:
                self.computer = se.abrir_computer_dotnet()
                log("Sensores: conectado direto na LibreHardwareMonitorLib.")
            incluir_lentos = time.time() - self._ultimo_update_lento >= INTERVALO_UPDATE_LENTO
            se.atualizar_computer_dotnet(self.computer, incluir_lentos)
            if incluir_lentos:
                self._ultimo_update_lento = time.time()
            sensores = se.listar_sensores_dotnet(self.computer)
        return se.detectar_tudo_com_sensores(sensores, overrides=overrides)

    def dump(self):
        """Lista BRUTA de todos os sensores que a LibreHardwareMonitorLib
        expoe nesta maquina -- alimenta o botao "Exportar sensores" da aba
        Sensores. E o raio-x pra ajustar a deteccao em hardware novo:
        se algo nao aparece no display, o dump mostra se a lib nem expoe
        (limitacao de hardware/driver) ou se expoe com outro nome (ajuste
        de deteccao no sensor_engine)."""
        with self.lock:
            if self.computer is None:
                self.computer = se.abrir_computer_dotnet()
            se.atualizar_computer_dotnet(self.computer, True)
            self._ultimo_update_lento = time.time()
            return se.listar_sensores_dotnet(self.computer)

    def fechar(self):
        with self.lock:
            if self.computer is not None:
                try:
                    self.computer.Close()
                except Exception:
                    pass
                self.computer = None


fonte_sensores = FonteSensores()


# ---------------------------------------------------------------------
# THREAD PRINCIPAL DE MONITORAMENTO
# ---------------------------------------------------------------------
def thread_monitoramento(parar_evento):
    # auto-cura: se o usuario ligou "iniciar com o Windows" numa execucao
    # anterior mas a tarefa sumiu do Agendador por algum motivo, recria aqui
    if config.get("autostart") and not autostart_esta_ativo():
        definir_autostart(True)

    pagina = 0                 # tela exibida agora (0 = classica)
    ultimo_giro = time.time()  # quando a tela trocou pela ultima vez
    ultimo_envio = None        # quando o ultimo pacote saiu (detector de buracos)

    while not parar_evento.is_set():
        if pausar_para_flash.is_set():
            # gravacao de firmware em andamento (ver firmware_engine.py) --
            # nao encosta na porta ate a flag ser limpa, o esptool precisa
            # dela sozinho
            estado.atualizar(conectado=False, porta=None)
            time.sleep(0.5)
            continue

        porta = encontrar_porta_automatica()
        if porta is None:
            estado.atualizar(conectado=False, porta=None)
            time.sleep(2)
            continue

        try:
            # NAO usar serial.Serial(porta, BAUD, ...) direto -- esse atalho
            # abre a porta com DTR/RTS em nivel alto por padrao, e essa
            # transicao (de "flutuando" pra alto, na primeira abertura) e'
            # exatamente o sinal que o ESP32-C3 (USB nativo/CDC) usa como
            # auto-reset -- o mesmo mecanismo que o esptool usa pra resetar
            # a placa sozinho na hora de gravar. Resultado: toda vez que o
            # app abre a porta, o ESP32 reinicia (tela volta pro splash e
            # sai de novo) mesmo sem nenhum problema real de energia.
            # Construindo o objeto Serial fechado, com dtr/rts ja em False
            # ANTES do open(), evita essa transicao e o reset indesejado.
            ser = serial.Serial()
            ser.port = porta
            ser.baudrate = BAUD
            ser.timeout = 2
            ser.write_timeout = 2
            ser.dtr = False
            ser.rts = False
            try:
                ser.open()
                time.sleep(2)
                log(f"Conectado em {porta}")
                estado.atualizar(conectado=True, ultimo_erro=None, porta=porta)
                primeira_linha = True
                ultimo_envio = None

                while not parar_evento.is_set() and not pausar_para_flash.is_set():
                    if estado.snapshot()["pausado"]:
                        time.sleep(0.5)
                        continue

                    try:
                        inicio_leitura = time.time()
                        deteccao = fonte_sensores.ler(config.overrides())
                        duracao = time.time() - inicio_leitura
                        if duracao > 2.5:
                            log(f"Aviso: leitura de sensores demorou {duracao:.1f}s "
                                "(provavel SMART de disco lento -- se o display recriar a tela, e isso)")
                        estado.atualizar(ultima_deteccao=deteccao, ultimo_erro=None)

                        # qual tela mostrar: troca manual (bandeja) tem
                        # prioridade; senao, rotacao automatica por tempo.
                        # So telas com conteudo contam -- vazia nao roda.
                        num_telas = 1 + len(telas_ativas())
                        rotacao = config.get("rotacaoSec", 0) or 0
                        if estado.consumir_troca_manual():
                            pagina = (pagina + 1) % num_telas
                            ultimo_giro = time.time()
                        elif (rotacao > 0 and num_telas > 1
                              and time.time() - ultimo_giro >= rotacao):
                            pagina = (pagina + 1) % num_telas
                            ultimo_giro = time.time()
                        pagina %= num_telas  # usuario pode ter removido telas
                        estado.atualizar(pagina=pagina)

                        linha = montar_linha_pagina(deteccao, pagina)

                        # detector de buracos: qualquer pausa > 5s entre envios
                        # fica registrada -- se o display "recriar" a tela, da
                        # pra cruzar o horario com essas entradas do log
                        agora = time.time()
                        if ultimo_envio is not None and agora - ultimo_envio > 5:
                            log(f"Aviso: {agora - ultimo_envio:.1f}s sem enviar -- buraco no ciclo "
                                "(display deve ter mostrado o splash nesse instante)")

                        ser.write(linha.encode())
                        ultimo_envio = time.time()
                        # loga so a primeira leitura de cada conexao -- logar
                        # toda linha (1x/seg) foi o que gerou um log de 9.9MB
                        if primeira_linha:
                            log(f"Enviado (primeira leitura): {linha.strip()}")
                            primeira_linha = False

                        # escuta o ESP32: o firmware reporta "DBG:..." toda
                        # vez que limpa a tela (e por que) -- vai pro log e
                        # fecha o diagnostico de "tela sendo recriada"
                        try:
                            while ser.in_waiting:
                                resposta = ser.readline().decode(errors="replace").strip()
                                if resposta:
                                    log(f"ESP32: {resposta}")
                                    if resposta.startswith("DBG:versao="):
                                        estado.atualizar(versao_firmware=resposta.split("=", 1)[1].strip())
                        except Exception:
                            pass  # diagnostico nunca pode derrubar o ciclo
                    except serial.SerialException:
                        raise
                    except Exception:
                        log("Erro no ciclo de leitura:\n" + traceback.format_exc())
                        estado.atualizar(ultimo_erro="Falha ao ler sensores")

                    intervalo = config.get("updateIntervalSec", 1.0)
                    for _ in range(int(max(intervalo, 0.2) / 0.2)):
                        if (parar_evento.is_set() or pausar_para_flash.is_set()
                                or estado.snapshot()["pausado"]):
                            break
                        time.sleep(0.2)
            finally:
                ser.close()
        except serial.SerialException as e:
            log(f"Porta serial desconectada: {e}")
            estado.atualizar(conectado=False, porta=None)
            time.sleep(2)
        except Exception:
            log("Erro inesperado na thread de monitoramento:\n" + traceback.format_exc())
            estado.atualizar(conectado=False, porta=None)
            time.sleep(2)

    fonte_sensores.fechar()


# ---------------------------------------------------------------------
# INTERFACE -- janela de configuracoes (CustomTkinter). O visual antigo
# (ttk tema clam, cara de "Windows 98") foi aposentado: agora e sidebar
# de navegacao, cards arredondados, switch/slider modernos e uma pre-
# visualizacao ao vivo do proprio display redondo dentro da janela.
# ---------------------------------------------------------------------
COR_FUNDO = "#161616"
COR_SIDEBAR = "#1b1b1b"
COR_FUNDO_CARD = "#1e1e1e"
COR_TEXTO = "#e8e8e8"
COR_TEXTO_MUTED = "#9a9a9a"
COR_ACCENT = "#ff7a1a"
COR_ACCENT_HOVER = "#e56a10"
COR_ACCENT_BG = "#2a2118"    # fundo do item selecionado na sidebar
COR_HOVER_NAV = "#242424"
COR_BORDA = "#2c2c2c"
COR_VERDE = "#1d9e75"
COR_AGUARDANDO = "#d85a30"
COR_VERMELHO = "#ff2828"  # mesmo vermelho do alerta de RAM no firmware (255,40,40)
FONTE = "Segoe UI"


_janela_config = None  # referencia da janela aberta -- garante janela unica


def abrir_janela_configuracoes(master):
    """Monta e mostra a janela de configuracoes. E uma funcao (nao uma
    classe) de proposito: assim os imports de tkinter/customtkinter ficam
    locais a essa funcao, e o resto do modulo (config, deteccao de
    sensores, protocolo serial, autostart) continua importavel/testavel
    em qualquer ambiente, mesmo sem interface grafica instalada."""
    import tkinter as tk
    from tkinter import colorchooser
    import customtkinter as ctk

    # janela unica: se ja tem uma aberta, so traz pra frente em vez de
    # empilhar outra copia a cada clique em "Configuracoes" na bandeja
    global _janela_config
    try:
        if _janela_config is not None and _janela_config.winfo_exists():
            _janela_config.deiconify()
            _janela_config.lift()
            _janela_config.focus_force()
            return _janela_config
    except Exception:
        pass

    janela = ctk.CTkToplevel(master)
    janela.title("OrbePC — configurações")
    janela.configure(fg_color=COR_FUNDO)
    janela.resizable(False, False)

    # centraliza na tela (em vez de abrir onde o Windows decidir)
    larg, alt = 660, 480
    x = max((janela.winfo_screenwidth() - larg) // 2, 0)
    y = max((janela.winfo_screenheight() - alt) // 2, 0)
    janela.geometry(f"{larg}x{alt}+{x}+{y}")

    # icone do OrbePC na barra de titulo. Quirk conhecido do CTkToplevel:
    # ele re-aplica o icone padrao ~250ms depois de criar a janela, entao
    # o nosso precisa ser agendado pra DEPOIS disso
    try:
        from PIL import ImageTk
        img_icone = ImageTk.PhotoImage(gerar_icone((255, 122, 26, 255)))
        janela._icone_ref = img_icone  # segura a referencia (senao o tk perde o icone)
        janela.after(350, lambda: janela.iconphoto(False, img_icone))
    except Exception:
        pass

    # esqueleto: sidebar de navegacao fixa a esquerda + conteudo a direita
    sidebar = ctk.CTkFrame(janela, width=150, fg_color=COR_SIDEBAR, corner_radius=0)
    sidebar.pack(side="left", fill="y")
    sidebar.pack_propagate(False)

    conteudo = ctk.CTkFrame(janela, fg_color=COR_FUNDO, corner_radius=0)
    conteudo.pack(side="left", fill="both", expand=True)

    # -------------------- Métricas (cores + preview ao vivo) --------------------
    swatches = {}  # chave_config -> widgets do card de cor (pra atualizar apos escolher)
    preview = {}   # itens do canvas da pre-visualizacao (atualizados a cada 1s)

    def montar_aba_metricas(parent):
        f = ctk.CTkFrame(parent, fg_color="transparent")

        esq = ctk.CTkFrame(f, fg_color="transparent")
        esq.pack(side="left", fill="both", expand=True, padx=(20, 10), pady=18)

        ctk.CTkLabel(esq, text="Cores dos anéis", font=(FONTE, 15, "bold"),
                     text_color=COR_TEXTO, anchor="w").pack(anchor="w", pady=(0, 10))
        cartao_cor(esq, "CPU", "colorCpu")
        cartao_cor(esq, "GPU", "colorGpu")
        ctk.CTkLabel(esq, text="Clique no quadrado colorido pra trocar.\nA mudança aparece no display na próxima\nleitura (e na prévia ao lado).",
                     font=(FONTE, 10), text_color=COR_TEXTO_MUTED, anchor="w",
                     justify="left").pack(anchor="w", pady=(10, 0))

        # ----- brilho da tela -----
        # SEM SLIDER DE PROPOSITO: o modulo de display usado (GC9A01 redondo,
        # so' RST/CS/DC/SDA/SCL/GND/VCC) nao expoe pino de backlight -- o
        # LED fica ligado direto no VCC dentro da propria placinha da tela,
        # sem trilha externa que de pra interceptar. Confirmado via log:
        # o firmware recebe BRIGHT= e chama ledcWrite() certinho (linha
        # "DBG:brilho mudou X->Y"), mas nao ha efeito fisico nenhum porque
        # o pino nao esta de fato conectado ao backlight. O protocolo
        # (BRIGHT= no montar_linha/montar_linha_pagina, config "brilhoPct")
        # e o firmware (ledcAttach/ledcWrite em TFT_BL) continuam prontos e
        # documentados -- se um dia trocar pra um modulo com pino BLK/LED
        # exposto, so' add o slider de volta aqui, sem mexer no resto.

        dir_ = ctk.CTkFrame(f, fg_color="transparent")
        dir_.pack(side="right", padx=(0, 20), pady=14)
        ctk.CTkLabel(dir_, text="Pré-visualização ao vivo", font=(FONTE, 11),
                     text_color=COR_TEXTO_MUTED).pack(pady=(0, 4))
        montar_preview(dir_)
        return f

    def cartao_cor(parent, rotulo, chave_config):
        card = ctk.CTkFrame(parent, fg_color=COR_FUNDO_CARD, corner_radius=10,
                            border_width=1, border_color=COR_BORDA)
        card.pack(fill="x", pady=5)

        hexcolor = f"#{config.get(chave_config)}"
        sw = ctk.CTkButton(card, text="", width=28, height=28, corner_radius=8,
                           fg_color=hexcolor, hover_color=hexcolor, border_width=0,
                           command=lambda: escolher_cor(rotulo, chave_config))
        sw.pack(side="left", padx=12, pady=12)

        col = ctk.CTkFrame(card, fg_color="transparent")
        col.pack(side="left", pady=8)
        ctk.CTkLabel(col, text=rotulo, font=(FONTE, 13), text_color=COR_TEXTO,
                     anchor="w", height=16).pack(anchor="w")
        lbl_hex = ctk.CTkLabel(col, text=hexcolor.upper(), font=(FONTE, 10),
                               text_color=COR_TEXTO_MUTED, anchor="w", height=14)
        lbl_hex.pack(anchor="w")

        swatches[chave_config] = (sw, lbl_hex)

    def escolher_cor(rotulo, chave_config):
        atual = f"#{config.get(chave_config)}"
        cor = colorchooser.askcolor(color=atual, title=f"Cor da {rotulo}", parent=janela)
        if cor and cor[1]:
            novo_hex = cor[1].lstrip("#").upper()
            config.set(chave_config, novo_hex)
            sw, lbl_hex = swatches[chave_config]
            sw.configure(fg_color=f"#{novo_hex}", hover_color=f"#{novo_hex}")
            lbl_hex.configure(text=f"#{novo_hex}")

    # clone fiel da telinha, em escala 0.85 do display real (240x240 ->
    # 204x204, centro 120 -> 102): mesmos aneis (CPU r114/w8 fora, GPU
    # r94/w7 dentro, 270 graus com vao embaixo), escala 0/50/100 com
    # tracinhos, termometros, separador, RAM/VRAM e o "OrbePC" laranja
    # perto da borda de baixo -- tudo nas MESMAS posicoes do firmware
    # (multiplicadas por 0.85). tk.Canvas puro, "tela" redonda desenhada.
    def montar_preview(parent):
        import math
        # canvas com o fundo da janela e um circulo preto desenhado em
        # cima -- assim a "tela" fica redonda, imitando o display de 1,28"
        # (canvas do tk e sempre retangular, entao o circulo e desenhado)
        cv = tk.Canvas(parent, width=204, height=204, bg=COR_FUNDO,
                       highlightthickness=0, bd=0)
        cv.pack()
        cv.create_oval(1, 1, 203, 203, fill="#000000", outline=COR_BORDA)

        # escala estatica (tracinhos em 135/270/405 graus + numeros), igual
        # desenharMarcaEscala() do firmware. As formulas de seno/cosseno
        # valem direto aqui: coordenadas de pixel tambem tem y pra baixo
        for ang in (135.0, 270.0, 405.0):
            rad = math.radians(ang)
            cv.create_line(102 + 97 * math.cos(rad), 102 + 97 * math.sin(rad),
                           102 + 100 * math.cos(rad), 102 + 100 * math.sin(rad),
                           fill="#6e6e6e")
        cv.create_text(31, 165, text="0", fill="#6e6e6e", font=("Consolas", 7))
        cv.create_text(102, 14, text="50", fill="#6e6e6e", font=("Consolas", 7))
        cv.create_text(167, 165, text="100", fill="#6e6e6e", font=("Consolas", 7))

        # aneis de carga SEM trilho de fundo -- no display real o fundo e
        # preto e o anel cresce "do nada", entao aqui e igual.
        # nota de coordenadas dos arcos: no tk, angulo 0 = 3h e sentido
        # anti-horario (y pra cima) -- start=225 com extent negativo
        # reproduz o gauge do firmware (135 a 405 graus com y pra baixo):
        # comeca embaixo-esquerda, sobe pelo topo, termina embaixo-direita
        preview["arco_cpu"] = cv.create_arc(5, 5, 199, 199, start=225, extent=-1,
                                            style="arc", width=7, outline="#00DC00",
                                            state="hidden")
        preview["arco_gpu"] = cv.create_arc(22, 22, 182, 182, start=225, extent=-1,
                                            style="arc", width=6, outline="#0090FF",
                                            state="hidden")

        fonte_g = ("Consolas", 11, "bold")
        # termometros (haste + bulbo) na frente das linhas de temperatura
        preview["term_cpu"] = (cv.create_rectangle(56, 59, 59, 68, fill="#00DC00", outline=""),
                               cv.create_oval(54, 66, 61, 73, fill="#00DC00", outline=""))
        preview["term_gpu"] = (cv.create_rectangle(56, 81, 59, 90, fill="#0090FF", outline=""),
                               cv.create_oval(54, 88, 61, 95, fill="#0090FF", outline=""))
        preview["txt_cpu"] = cv.create_text(107, 65, text="CPU  --", fill="#00DC00", font=fonte_g)
        preview["txt_gpu"] = cv.create_text(107, 87, text="GPU  --", fill="#0090FF", font=fonte_g)

        cv.create_line(64, 99, 140, 99, fill="#323232")  # separador (HLine do firmware)

        preview["txt_ram"] = cv.create_text(102, 114, text="RAM   -- GB", fill="#b4b4b4", font=fonte_g)
        preview["txt_vram"] = cv.create_text(102, 133, text="VRAM  -- GB", fill="#0090FF", font=fonte_g)
        cv.create_text(102, 178, text="OrbePC", fill=COR_ACCENT, font=("Consolas", 12, "bold"))
        preview["canvas"] = cv

    def atualizar_preview(snap):
        cv = preview.get("canvas")
        if not cv:
            return
        det = snap["ultima_deteccao"]

        def valor(chave):
            return det.get(chave, {}).get("valor")

        cor_cpu = f"#{config.get('colorCpu')}"
        cor_gpu = f"#{config.get('colorGpu')}"

        for chave_carga, arco, cor in (("cpuLoad", "arco_cpu", cor_cpu),
                                       ("gpuLoad", "arco_gpu", cor_gpu)):
            carga = valor(chave_carga)
            if carga is None or carga <= 0:
                cv.itemconfigure(preview[arco], state="hidden")
            else:
                extent = -270.0 * min(max(carga, 0.0), 100.0) / 100.0
                cv.itemconfigure(preview[arco], extent=extent, outline=cor, state="normal")

        for parte in preview["term_cpu"]:
            cv.itemconfigure(parte, fill=cor_cpu)
        for parte in preview["term_gpu"]:
            cv.itemconfigure(parte, fill=cor_gpu)

        t_cpu = valor("cpuTemp")
        t_gpu = valor("gpuTemp")
        ram = valor("ram")
        vram = valor("vram")
        ram_pct = valor("ramPct")

        # mesmos formatos de texto do firmware (largura fixa, alinhado)
        cv.itemconfigure(preview["txt_cpu"], fill=cor_cpu,
                         text=f"CPU {t_cpu:3.0f}°C" if t_cpu is not None else "CPU  --")
        cv.itemconfigure(preview["txt_gpu"], fill=cor_gpu,
                         text=f"GPU {t_gpu:3.0f}°C" if t_gpu is not None else "GPU  --")
        # mesmas regras do firmware: RAM cinza (vermelha acima do limite),
        # VRAM sempre na cor da GPU
        acima = ram_pct is not None and ram_pct >= config.get("ramLimitPct", 90.0)
        cv.itemconfigure(preview["txt_ram"], fill=COR_VERMELHO if acima else "#b4b4b4",
                         text=f"RAM {ram:4.1f} GB" if ram is not None else "RAM   -- GB")
        cv.itemconfigure(preview["txt_vram"], fill=cor_gpu,
                         text=f"VRAM{vram:4.1f} GB" if vram is not None else "VRAM  -- GB")

    # -------------------- Sensores --------------------
    def montar_aba_sensores(parent):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        interno = ctk.CTkFrame(f, fg_color="transparent")
        interno.pack(fill="both", expand=True, padx=20, pady=16)

        lbl_resumo = ctk.CTkLabel(interno, text="Detectando…", font=(FONTE, 11),
                                  text_color=COR_TEXTO_MUTED, anchor="w")
        lbl_resumo.pack(anchor="w", pady=(0, 6))

        frame_linhas = ctk.CTkFrame(interno, fg_color="transparent")
        frame_linhas.pack(fill="both", expand=True)

        def linha_sensor(parent, chave, rotulo, info):
            card = ctk.CTkFrame(parent, fg_color=COR_FUNDO_CARD, corner_radius=10,
                                border_width=1, border_color=COR_BORDA)
            card.pack(fill="x", pady=3)

            texto_atual = info.get("texto") or "não encontrado"
            ctk.CTkLabel(card, text=rotulo, font=(FONTE, 12), text_color=COR_TEXTO,
                         anchor="w", height=16).pack(anchor="w", padx=12, pady=(7, 0))

            candidatos = info.get("candidatos", [])
            if len(candidatos) > 1:
                nomes = [c["texto"] for c in candidatos]

                def ao_escolher(escolhido_texto, chave=chave, candidatos=candidatos):
                    escolhido = next((c for c in candidatos if c["texto"] == escolhido_texto), None)
                    if escolhido:
                        config.set_override(chave, escolhido["sensor_id"])

                menu = ctk.CTkOptionMenu(card, values=nomes, command=ao_escolher,
                                         fg_color="#262626", button_color="#303030",
                                         button_hover_color=COR_ACCENT,
                                         text_color=COR_TEXTO, font=(FONTE, 11),
                                         dropdown_fg_color=COR_FUNDO_CARD,
                                         dropdown_text_color=COR_TEXTO,
                                         dropdown_hover_color=COR_ACCENT_BG,
                                         width=380, height=26)
                if texto_atual in nomes:
                    menu.set(texto_atual)
                menu.pack(anchor="w", padx=12, pady=(2, 8))
            else:
                ctk.CTkLabel(card, text=texto_atual, font=(FONTE, 11),
                             text_color=COR_TEXTO_MUTED, anchor="w",
                             height=14).pack(anchor="w", padx=12, pady=(0, 7))

        def redetectar():
            for w in frame_linhas.winfo_children():
                w.destroy()

            try:
                # reaproveita o MESMO Computer da thread de monitoramento
                # (fonte_sensores) -- nunca abrir um segundo aqui, dois
                # handles simultaneos no driver de hardware derrubavam
                # o app inteiro (ver comentario acima de FonteSensores)
                deteccao = fonte_sensores.ler(config.overrides())
            except Exception as e:
                log("Erro ao redetectar sensores (aba Sensores):\n" + traceback.format_exc())
                ctk.CTkLabel(frame_linhas,
                             text=f"Não consegui ler os sensores:\n{type(e).__name__}: {e}\n\nVeja o log completo em Ver log (bandeja).",
                             font=(FONTE, 11), text_color=COR_TEXTO_MUTED,
                             wraplength=420, justify="left").pack(anchor="w")
                return

            achados, total = se.resumo_deteccao(deteccao)
            lbl_resumo.configure(text=f"{achados} de {total} sensores detectados automaticamente")

            metricas_visiveis = [
                ("cpuTemp", "CPU · temperatura"),
                ("gpuTemp", "GPU · temperatura"),
                ("vram", "VRAM dedicada"),
                ("ram", "RAM utilizada"),
            ]
            for chave, rotulo in metricas_visiveis:
                info = deteccao.get(chave, {})
                linha_sensor(frame_linhas, chave, rotulo, info)

            # nenhuma temperatura de CPU em lugar nenhum -- mostra a causa mais
            # provavel PRIMEIRO com base no que garantir_pawnio() descobriu no
            # startup (estado.pawnio_aviso), com um botao de acao direta em vez
            # de so texto -- e' o driver PawnIO ausente/mal instalado na grande
            # maioria dos casos (ver saga de diagnostico que motivou isso: nao
            # era Integridade de Memoria, era o WinRing0 antigo bloqueado pela
            # lista de drivers vulneraveis do Windows). Isolamento de Nucleo
            # ainda fica mencionado por baixo, como causa secundaria possivel.
            if deteccao.get("cpuTemp", {}).get("valor") is None:
                aviso_pawnio = estado.snapshot().get("pawnio_aviso")
                if aviso_pawnio:
                    bloco = ctk.CTkFrame(frame_linhas, fg_color="transparent")
                    bloco.pack(fill="x", pady=(6, 0))
                    ctk.CTkLabel(bloco, text=f"⚠ {aviso_pawnio}",
                                 font=(FONTE, 10), text_color="#e0a030",
                                 wraplength=430, justify="left").pack(anchor="w")

                    def tentar_reinstalar_pawnio():
                        garantir_pawnio()
                        redetectar()

                    ctk.CTkButton(bloco, text="Tentar reinstalar PawnIO",
                                  command=tentar_reinstalar_pawnio,
                                  fg_color="transparent", hover_color=COR_HOVER_NAV,
                                  text_color=COR_ACCENT, font=(FONTE, 11),
                                  border_width=1, border_color=COR_ACCENT,
                                  corner_radius=8, height=28, width=180).pack(anchor="w", pady=(6, 0))
                else:
                    ctk.CTkLabel(frame_linhas,
                                 text=("⚠ Sem temperatura de CPU. Causas possíveis: driver PawnIO "
                                       "com problema (veja Ver log na bandeja), a \"Integridade de "
                                       "Memória\" do Windows (Segurança do Windows → Isolamento de "
                                       "Núcleo) bloqueando o driver, ou o hardware sem suporte."),
                                 font=(FONTE, 10), text_color="#e0a030",
                                 wraplength=430, justify="left").pack(anchor="w", pady=(6, 0))

        def exportar_sensores():
            """Gera %APPDATA%\\PainelPC\\sensores_detectados.txt com TUDO
            que a lib enxerga e abre no bloco de notas -- pra diagnosticar
            deteccao em qualquer maquina (fan que nao aparece etc.)."""
            try:
                brutos = fonte_sensores.dump()
                caminho = os.path.join(CONFIG_DIR, "sensores_detectados.txt")
                with open(caminho, "w", encoding="utf-8") as arq:
                    arq.write(f"OrbePC — sensores expostos pela LibreHardwareMonitorLib "
                              f"({time.strftime('%d/%m/%Y %H:%M')})\n")
                    arq.write(f"{len(brutos)} sensores encontrados\n\n")
                    for s in sorted(brutos, key=lambda x: x.sensor_id):
                        arq.write(f"{s.sensor_id}\n    {s.texto}  =  {s.valor_raw}\n")
                os.startfile(caminho)
            except Exception:
                log("Erro ao exportar sensores:\n" + traceback.format_exc())

        botoes = ctk.CTkFrame(interno, fg_color="transparent")
        botoes.pack(fill="x", pady=(8, 0))
        ctk.CTkButton(botoes, text="Redetectar", command=redetectar,
                      fg_color=COR_ACCENT, hover_color=COR_ACCENT_HOVER,
                      text_color="#1a1a1a", font=(FONTE, 12, "bold"),
                      corner_radius=8, height=30, width=110).pack(side="left")
        ctk.CTkButton(botoes, text="Exportar sensores", command=exportar_sensores,
                      fg_color="transparent", hover_color=COR_HOVER_NAV,
                      text_color=COR_TEXTO_MUTED, font=(FONTE, 11),
                      border_width=1, border_color=COR_BORDA,
                      corner_radius=8, height=30, width=130).pack(side="left", padx=(8, 0))

        redetectar()
        return f

    # -------------------- Alertas --------------------
    def montar_aba_alertas(parent):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        interno = ctk.CTkFrame(f, fg_color="transparent")
        interno.pack(fill="both", expand=True, padx=20, pady=18)

        ctk.CTkLabel(interno, text="Alerta de RAM", font=(FONTE, 15, "bold"),
                     text_color=COR_TEXTO, anchor="w").pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(interno, text="A partir de qual % de uso de RAM o número fica vermelho no display",
                     font=(FONTE, 11), text_color=COR_TEXTO_MUTED, anchor="w",
                     wraplength=420, justify="left").pack(anchor="w", pady=(0, 14))

        valor_inicial = int(config.get("ramLimitPct", 90))
        lbl_valor = ctk.CTkLabel(interno, text=f"{valor_inicial}%", font=(FONTE, 26, "bold"),
                                 text_color=COR_ACCENT)
        lbl_valor.pack(anchor="w")

        def ao_mudar(v):
            iv = int(float(v))
            lbl_valor.configure(text=f"{iv}%")
            config.set("ramLimitPct", float(iv))

        escala = ctk.CTkSlider(interno, from_=50, to=100, number_of_steps=50,
                               command=ao_mudar, progress_color=COR_ACCENT,
                               button_color=COR_ACCENT, button_hover_color=COR_ACCENT_HOVER,
                               fg_color=COR_BORDA)
        escala.set(valor_inicial)
        escala.pack(fill="x", pady=(6, 0))
        return f

    # -------------------- Geral --------------------
    # widgets do aviso de atualizacao disponivel -- preenchido por
    # montar_aba_geral(), atualizado a cada 1s pelo loop_atualizacao()
    # mais abaixo (a checagem no GitHub e' assincrona, pode terminar
    # depois da janela ja aberta)
    atualizacao_ui = {}

    def montar_aba_geral(parent):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        interno = ctk.CTkFrame(f, fg_color="transparent")
        interno.pack(fill="both", expand=True, padx=20, pady=18)

        # ----- aviso de atualizacao disponivel (GitHub Releases) -----
        card_att = ctk.CTkFrame(interno, fg_color=COR_ACCENT_BG, corner_radius=10,
                                border_width=1, border_color=COR_ACCENT)
        lbl_att = ctk.CTkLabel(card_att, text="", font=(FONTE, 12),
                               text_color=COR_ACCENT, anchor="w")
        lbl_att.pack(side="left", padx=14, pady=10)

        def abrir_pagina_atualizacao():
            info = estado.snapshot().get("atualizacao_disponivel")
            if info:
                import webbrowser
                webbrowser.open(info["url"])

        ctk.CTkButton(card_att, text="Baixar", command=abrir_pagina_atualizacao,
                      fg_color=COR_ACCENT, hover_color=COR_ACCENT_HOVER,
                      text_color="#1a1a1a", font=(FONTE, 11, "bold"),
                      corner_radius=8, height=28, width=80).pack(side="right", padx=14)
        # card_att fica escondido ate ter atualizacao (pack so' e' chamado
        # dinamicamente por atualizar_aviso_versao(), la no loop_atualizacao)

        atualizacao_ui["card"] = card_att
        atualizacao_ui["label"] = lbl_att
        atualizacao_ui["mostrado"] = False

        def ao_mudar_autostart():
            ativo = bool(switch_autostart.get())
            ok = definir_autostart(ativo)
            if not ok:
                (switch_autostart.deselect() if ativo else switch_autostart.select())
            else:
                config.set("autostart", ativo)

        switch_autostart = ctk.CTkSwitch(interno, text="Iniciar com o Windows",
                                         command=ao_mudar_autostart, font=(FONTE, 13),
                                         text_color=COR_TEXTO, progress_color=COR_ACCENT,
                                         button_color="#dddddd", fg_color=COR_BORDA)
        if autostart_esta_ativo():
            switch_autostart.select()
        switch_autostart.pack(anchor="w", pady=(0, 20))
        atualizacao_ui["ancora"] = switch_autostart  # loop_atualizacao usa isso pra
        # posicionar o aviso de atualizacao no TOPO da aba (antes deste switch)

        ctk.CTkLabel(interno, text="Intervalo entre leituras", font=(FONTE, 11),
                     text_color=COR_TEXTO_MUTED, anchor="w").pack(anchor="w")
        lbl_intervalo = ctk.CTkLabel(interno, text=f"{config.get('updateIntervalSec', 1.0):.1f}s",
                                     font=(FONTE, 20, "bold"), text_color=COR_ACCENT)
        lbl_intervalo.pack(anchor="w")

        def ao_mudar_intervalo(v):
            iv = round(float(v), 1)
            lbl_intervalo.configure(text=f"{iv}s")
            config.set("updateIntervalSec", iv)

        escala = ctk.CTkSlider(interno, from_=0.5, to=3.0, number_of_steps=25,
                               command=ao_mudar_intervalo, progress_color=COR_ACCENT,
                               button_color=COR_ACCENT, button_hover_color=COR_ACCENT_HOVER,
                               fg_color=COR_BORDA)
        escala.set(config.get("updateIntervalSec", 1.0))
        escala.pack(fill="x", pady=(6, 0))

        # ----- atalho global pra trocar de tela -----
        ctk.CTkLabel(interno, text="Atalho de teclado pra trocar de tela (funciona até dentro de jogos)",
                     font=(FONTE, 11), text_color=COR_TEXTO_MUTED, anchor="w").pack(anchor="w", pady=(18, 4))

        captura = {"bind_id": None}
        # keysyms do tk -> nomes que o registrador entende
        mapa_keysym = {"prior": "PGUP", "next": "PGDOWN", "insert": "INS",
                       "delete": "DEL", "up": "UP", "down": "DOWN",
                       "left": "LEFT", "right": "RIGHT", "space": "SPACE"}

        def texto_atalho():
            return (config.get("atalhoTela") or "").upper().replace("+", " + ") or "clique e pressione…"

        def parar_captura():
            if captura["bind_id"]:
                janela.unbind("<KeyPress>", captura["bind_id"])
                captura["bind_id"] = None

        def ao_teclar(ev):
            keysym = ev.keysym.lower()
            if keysym in ("control_l", "control_r", "alt_l", "alt_r",
                          "shift_l", "shift_r", "super_l", "super_r"):
                return  # ainda segurando modificadores -- espera a tecla final
            if keysym == "escape":
                parar_captura()
                btn_atalho.configure(text=texto_atalho())
                return
            mods = []
            if ev.state & 0x0004:
                mods.append("ctrl")
            if ev.state & 0x20000 or ev.state & 0x0008:
                mods.append("alt")
            if ev.state & 0x0001:
                mods.append("shift")
            tecla = mapa_keysym.get(keysym, keysym)
            if _vk_de_tecla(tecla) is None:
                return  # tecla sem suporte (ex: acentos) -- segue esperando
            if not mods and len(tecla) == 1:
                return  # letra sozinha viraria armadilha ao digitar -- exige modificador
            combo = "+".join(mods + [tecla.lower()])
            parar_captura()
            config.set("atalhoTela", combo)
            atalho_global.aplicar(combo)
            btn_atalho.configure(text=texto_atalho())

        def iniciar_captura():
            parar_captura()
            btn_atalho.configure(text="pressione a combinação… (Esc cancela)")
            janela.focus_force()
            captura["bind_id"] = janela.bind("<KeyPress>", ao_teclar)

        def limpar_atalho():
            parar_captura()
            config.set("atalhoTela", "")
            atalho_global.aplicar("")
            btn_atalho.configure(text=texto_atalho())

        linha_atalho = ctk.CTkFrame(interno, fg_color="transparent")
        linha_atalho.pack(fill="x")
        btn_atalho = ctk.CTkButton(linha_atalho, text=texto_atalho(), command=iniciar_captura,
                                   fg_color=COR_FUNDO_CARD, hover_color=COR_HOVER_NAV,
                                   text_color=COR_TEXTO, font=(FONTE, 12),
                                   border_width=1, border_color=COR_BORDA,
                                   corner_radius=8, height=32, width=220)
        btn_atalho.pack(side="left")
        ctk.CTkButton(linha_atalho, text="Limpar", command=limpar_atalho,
                      fg_color="transparent", hover_color=COR_HOVER_NAV,
                      text_color=COR_TEXTO_MUTED, font=(FONTE, 11),
                      border_width=1, border_color=COR_BORDA,
                      corner_radius=8, height=32, width=70).pack(side="left", padx=(8, 0))

        # ----- clima: cidade (Open-Meteo) -----
        ctk.CTkLabel(interno, text="Clima no display — escolha a cidade (fonte: Open-Meteo, sem cadastro)",
                     font=(FONTE, 11), text_color=COR_TEXTO_MUTED, anchor="w").pack(anchor="w", pady=(16, 4))

        linha_clima = ctk.CTkFrame(interno, fg_color="transparent")
        linha_clima.pack(fill="x")
        entry_cidade = ctk.CTkEntry(linha_clima, placeholder_text="digite a cidade…",
                                    width=200, height=30, fg_color=COR_FUNDO_CARD,
                                    border_color=COR_BORDA, text_color=COR_TEXTO,
                                    font=(FONTE, 12))
        entry_cidade.pack(side="left")

        cidade_atual = config.get("climaCidade") or "nenhuma cidade definida"
        lbl_cidade = ctk.CTkLabel(interno, text=f"Atual: {cidade_atual}", font=(FONTE, 10),
                                  text_color=COR_TEXTO_MUTED, anchor="w")

        menu_resultados = ctk.CTkOptionMenu(interno, values=[""], width=300, height=26,
                                            fg_color="#262626", button_color="#303030",
                                            button_hover_color=COR_ACCENT, text_color=COR_TEXTO,
                                            font=(FONTE, 11), dropdown_fg_color=COR_FUNDO_CARD,
                                            dropdown_text_color=COR_TEXTO,
                                            dropdown_hover_color=COR_ACCENT_BG)
        resultados_busca = {"lista": []}

        def escolher_cidade(rotulo):
            escolhida = next((c for c in resultados_busca["lista"] if c["rotulo"] == rotulo), None)
            if not escolhida:
                return
            config.set("climaCidade", escolhida["rotulo"])
            config.set("climaLat", escolhida["lat"])
            config.set("climaLon", escolhida["lon"])
            clima_engine.configurar(escolhida["lat"], escolhida["lon"])
            lbl_cidade.configure(text=f"Atual: {escolhida['rotulo']}")

        menu_resultados.configure(command=escolher_cidade)

        def buscar_cidade():
            nome = entry_cidade.get().strip()
            if not nome:
                return
            try:
                achadas = clima_engine.buscar_cidades(nome)
            except Exception:
                lbl_cidade.configure(text="Busca falhou — verifique a internet e tente de novo")
                return
            if not achadas:
                lbl_cidade.configure(text=f"Nenhuma cidade encontrada para “{nome}”")
                return
            resultados_busca["lista"] = achadas
            menu_resultados.configure(values=[c["rotulo"] for c in achadas])
            menu_resultados.set(achadas[0]["rotulo"])
            menu_resultados.pack(anchor="w", pady=(6, 0))
            lbl_cidade.configure(text="Escolha na lista acima pra confirmar")

        ctk.CTkButton(linha_clima, text="Buscar", command=buscar_cidade,
                      fg_color=COR_ACCENT, hover_color=COR_ACCENT_HOVER,
                      text_color="#1a1a1a", font=(FONTE, 11, "bold"),
                      corner_radius=8, height=30, width=70).pack(side="left", padx=(8, 0))
        lbl_cidade.pack(anchor="w", pady=(4, 0))

        # ----- backup de configuracoes (exportar/importar) -----
        ctk.CTkLabel(interno, text="Backup de configurações — cores, telas, sensores, alertas etc.",
                     font=(FONTE, 11), text_color=COR_TEXTO_MUTED, anchor="w").pack(anchor="w", pady=(18, 4))

        lbl_backup = ctk.CTkLabel(interno, text="", font=(FONTE, 10),
                                  text_color=COR_TEXTO_MUTED, anchor="w")

        def exportar_config():
            from tkinter import filedialog
            caminho = filedialog.asksaveasfilename(
                parent=janela, title="Exportar configurações do OrbePC",
                defaultextension=".json", initialfile="OrbePC_config_backup.json",
                filetypes=[("Configuração OrbePC (.json)", "*.json")],
            )
            if not caminho:
                return
            try:
                config.exportar(caminho)
                lbl_backup.configure(text=f"Exportado em: {caminho}", text_color=COR_TEXTO_MUTED)
            except Exception:
                log("Erro ao exportar config:\n" + traceback.format_exc())
                lbl_backup.configure(text="Falha ao exportar — veja Ver log (bandeja).", text_color="#e0a030")

        def importar_config():
            from tkinter import filedialog
            import tkinter.messagebox as messagebox
            caminho = filedialog.askopenfilename(
                parent=janela, title="Importar configurações do OrbePC",
                filetypes=[("Configuração OrbePC (.json)", "*.json"), ("Todos os arquivos", "*.*")],
            )
            if not caminho:
                return
            if not messagebox.askyesno(
                "Importar configurações",
                "Isso substitui TODAS as configurações atuais (cores, telas, "
                "sensores, alertas, atalho, cidade) pelas do arquivo escolhido.\n\n"
                "Continuar?",
                parent=janela,
            ):
                return
            try:
                config.importar(caminho)
                lbl_backup.configure(text="Importado! Feche e abra o OrbePC de novo pra tudo atualizar.",
                                     text_color=COR_ACCENT)
            except Exception:
                log("Erro ao importar config:\n" + traceback.format_exc())
                lbl_backup.configure(text="Falha ao importar — arquivo inválido ou corrompido.",
                                     text_color="#e0a030")

        linha_backup = ctk.CTkFrame(interno, fg_color="transparent")
        linha_backup.pack(fill="x")
        ctk.CTkButton(linha_backup, text="Exportar…", command=exportar_config,
                      fg_color=COR_FUNDO_CARD, hover_color=COR_HOVER_NAV,
                      text_color=COR_TEXTO, font=(FONTE, 12),
                      border_width=1, border_color=COR_BORDA,
                      corner_radius=8, height=32, width=110).pack(side="left")
        ctk.CTkButton(linha_backup, text="Importar…", command=importar_config,
                      fg_color=COR_FUNDO_CARD, hover_color=COR_HOVER_NAV,
                      text_color=COR_TEXTO, font=(FONTE, 12),
                      border_width=1, border_color=COR_BORDA,
                      corner_radius=8, height=32, width=110).pack(side="left", padx=(8, 0))
        lbl_backup.pack(anchor="w", pady=(6, 0))

        return f

    # -------------------- Telas (personalizadas) --------------------
    def montar_aba_telas(parent):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        interno = ctk.CTkFrame(f, fg_color="transparent")
        interno.pack(fill="both", expand=True, padx=20, pady=12)

        # mapeamentos rotulo <-> id pros dropdowns
        VAZIO = "— vazio —"
        anel_por_rotulo = {r: k for k, r in METRICAS_ANEL.items()}
        linha_por_rotulo = {e[0]: k for k, e in METRICAS_LINHA.items()}
        opcoes_anel = [VAZIO] + list(METRICAS_ANEL.values())
        opcoes_linha = [VAZIO] + [e[0] for e in METRICAS_LINHA.values()]

        def telas():
            return list(config.get("telasCustom") or [])

        def nomes_telas():
            return [f"Tela {i + 2}" for i in range(len(telas()))]

        estado_aba = {"idx": 0}

        # ----- rotacao automatica -----
        rot_atual = int(config.get("rotacaoSec", 0) or 0)

        def rotulo_rotacao(s):
            return "Rotação automática: desligada" if s == 0 else f"Rotação automática: a cada {s}s"

        lbl_rot = ctk.CTkLabel(interno, text=rotulo_rotacao(rot_atual), font=(FONTE, 11),
                               text_color=COR_TEXTO_MUTED, anchor="w")
        lbl_rot.pack(anchor="w")

        def ao_mudar_rotacao(v):
            s = int(float(v))
            lbl_rot.configure(text=rotulo_rotacao(s))
            config.set("rotacaoSec", s)

        slider_rot = ctk.CTkSlider(interno, from_=0, to=30, number_of_steps=30,
                                   command=ao_mudar_rotacao, progress_color=COR_ACCENT,
                                   button_color=COR_ACCENT, button_hover_color=COR_ACCENT_HOVER,
                                   fg_color=COR_BORDA, height=16)
        slider_rot.set(rot_atual)
        slider_rot.pack(fill="x", pady=(2, 10))

        # ----- barra: seletor de tela + adicionar/remover -----
        barra = ctk.CTkFrame(interno, fg_color="transparent")
        barra.pack(fill="x", pady=(0, 6))

        seletor = ctk.CTkOptionMenu(barra, values=nomes_telas() or [VAZIO],
                                    fg_color="#262626", button_color="#303030",
                                    button_hover_color=COR_ACCENT, text_color=COR_TEXTO,
                                    font=(FONTE, 12), dropdown_fg_color=COR_FUNDO_CARD,
                                    dropdown_text_color=COR_TEXTO,
                                    dropdown_hover_color=COR_ACCENT_BG,
                                    width=110, height=28,
                                    command=lambda nome: selecionar(nome))
        seletor.pack(side="left")

        area_config = ctk.CTkFrame(interno, fg_color="transparent")
        area_config.pack(fill="both", expand=True, pady=(4, 0))

        def salvar_telas(novas):
            config.set("telasCustom", novas)

        def atualizar_seletor():
            nomes = nomes_telas()
            seletor.configure(values=nomes or [VAZIO])
            if nomes:
                estado_aba["idx"] = min(estado_aba["idx"], len(nomes) - 1)
                seletor.set(nomes[estado_aba["idx"]])
            else:
                seletor.set(VAZIO)

        def selecionar(nome):
            try:
                estado_aba["idx"] = int(nome.split()[-1]) - 2
            except (ValueError, IndexError):
                estado_aba["idx"] = 0
            montar_config_tela()

        def linha_escolha(parent, rotulo, valor_id, mapa_por_rotulo, opcoes, ao_definir):
            linha = ctk.CTkFrame(parent, fg_color="transparent")
            linha.pack(fill="x", pady=2)
            ctk.CTkLabel(linha, text=rotulo, font=(FONTE, 11), text_color=COR_TEXTO,
                         anchor="w", width=90).pack(side="left")

            def ao_escolher(rotulo_escolhido):
                ao_definir(mapa_por_rotulo.get(rotulo_escolhido))  # None se "— vazio —"

            menu = ctk.CTkOptionMenu(linha, values=opcoes, command=ao_escolher,
                                     fg_color="#262626", button_color="#303030",
                                     button_hover_color=COR_ACCENT, text_color=COR_TEXTO,
                                     font=(FONTE, 11), dropdown_fg_color=COR_FUNDO_CARD,
                                     dropdown_text_color=COR_TEXTO,
                                     dropdown_hover_color=COR_ACCENT_BG,
                                     width=300, height=26)
            rotulo_atual = VAZIO
            for r, k in mapa_por_rotulo.items():
                if k == valor_id:
                    rotulo_atual = r
                    break
            menu.set(rotulo_atual)
            menu.pack(side="left", padx=(6, 0))

        def montar_config_tela():
            for w in area_config.winfo_children():
                w.destroy()

            ts = telas()
            if not ts:
                ctk.CTkLabel(area_config,
                             text="Nenhuma tela personalizada ainda.\nClique em \"+ Nova tela\" pra criar a primeira —\nvocê escolhe o que aparece em cada anel e linha.",
                             font=(FONTE, 11), text_color=COR_TEXTO_MUTED,
                             justify="left").pack(anchor="w", pady=8)
                return

            i = estado_aba["idx"]
            tela = ts[i]

            def definir(chave, valor, indice_linha=None):
                ts2 = telas()
                if indice_linha is None:
                    ts2[i][chave] = valor
                else:
                    linhas = (ts2[i].get("linhas") or [None] * 4)[:4]
                    linhas += [None] * (4 - len(linhas))
                    linhas[indice_linha] = valor
                    ts2[i]["linhas"] = linhas
                salvar_telas(ts2)

            linha_escolha(area_config, "Anel externo", tela.get("anel1"),
                          anel_por_rotulo, opcoes_anel, lambda v: definir("anel1", v))
            linha_escolha(area_config, "Anel interno", tela.get("anel2"),
                          anel_por_rotulo, opcoes_anel, lambda v: definir("anel2", v))
            linhas_atuais = (tela.get("linhas") or [None] * 4)[:4]
            linhas_atuais += [None] * (4 - len(linhas_atuais))
            for n in range(4):
                linha_escolha(area_config, f"Linha {n + 1}", linhas_atuais[n],
                              linha_por_rotulo, opcoes_linha,
                              lambda v, n=n: definir("linhas", v, indice_linha=n))

        def adicionar_tela():
            ts = telas()
            if len(ts) >= MAX_TELAS_CUSTOM:
                lbl_rot.configure(text=f"Limite de {MAX_TELAS_CUSTOM} telas personalizadas atingido")
                return
            ts.append({"anel1": None, "anel2": None, "linhas": [None] * 4})
            salvar_telas(ts)
            estado_aba["idx"] = len(ts) - 1
            atualizar_seletor()
            montar_config_tela()

        def remover_tela():
            ts = telas()
            if not ts:
                return
            ts.pop(estado_aba["idx"])
            salvar_telas(ts)
            estado_aba["idx"] = max(0, min(estado_aba["idx"], len(ts) - 1))
            atualizar_seletor()
            montar_config_tela()

        ctk.CTkButton(barra, text="+ Nova tela", command=adicionar_tela,
                      fg_color=COR_ACCENT, hover_color=COR_ACCENT_HOVER,
                      text_color="#1a1a1a", font=(FONTE, 11, "bold"),
                      corner_radius=8, height=28, width=90).pack(side="left", padx=(8, 0))
        ctk.CTkButton(barra, text="Remover", command=remover_tela,
                      fg_color="transparent", hover_color=COR_HOVER_NAV,
                      text_color=COR_TEXTO_MUTED, font=(FONTE, 11),
                      border_width=1, border_color=COR_BORDA,
                      corner_radius=8, height=28, width=80).pack(side="left", padx=(6, 0))

        # passa o display pra proxima tela daqui tambem (mesmo comando do
        # "Proxima tela" da bandeja -- a thread de monitoramento consome
        # o pedido no proximo ciclo, ~1s)
        def passar_tela():
            estado.atualizar(trocar_tela=True)

        ctk.CTkButton(barra, text="Passar tela ▸", command=passar_tela,
                      fg_color="transparent", hover_color=COR_HOVER_NAV,
                      text_color=COR_ACCENT, font=(FONTE, 11),
                      border_width=1, border_color=COR_ACCENT,
                      corner_radius=8, height=28, width=100).pack(side="right")

        atualizar_seletor()
        montar_config_tela()
        return f

    # -------------------- Firmware (atualizacao do ESP32) --------------------
    # widgets que o loop_atualizacao (mais abaixo) precisa tocar a cada 1s --
    # preenchido por montar_aba_firmware(), lido so se a aba ja foi montada
    firmware_ui = {}

    def montar_aba_firmware(parent):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        interno = ctk.CTkFrame(f, fg_color="transparent")
        interno.pack(fill="both", expand=True, padx=20, pady=18)

        ctk.CTkLabel(interno, text="Firmware do display", font=(FONTE, 15, "bold"),
                     text_color=COR_TEXTO, anchor="w").pack(anchor="w", pady=(0, 10))

        card = ctk.CTkFrame(interno, fg_color=COR_FUNDO_CARD, corner_radius=10,
                            border_width=1, border_color=COR_BORDA)
        card.pack(fill="x", pady=(0, 12))

        lbl_instalada = ctk.CTkLabel(card, text="Versão instalada: —", font=(FONTE, 12),
                                     text_color=COR_TEXTO, anchor="w")
        lbl_instalada.pack(anchor="w", padx=14, pady=(12, 6))

        # ----- aviso de firmware novo disponivel (GitHub Releases) -----
        # escondido por padrao -- loop_atualizacao() (mais abaixo) decide
        # quando mostrar, comparando com a versao do display CONECTADO
        # agora (so se sabe isso depois que ele manda DBG:versao=)
        card_fw_att = ctk.CTkFrame(interno, fg_color=COR_ACCENT_BG, corner_radius=10,
                                   border_width=1, border_color=COR_ACCENT)
        lbl_fw_att = ctk.CTkLabel(card_fw_att, text="", font=(FONTE, 12),
                                  text_color=COR_ACCENT, anchor="w")
        lbl_fw_att.pack(side="left", padx=14, pady=10)

        def baixar_e_preparar_firmware():
            info = estado.snapshot().get("firmware_disponivel")
            if not info or not info.get("url"):
                return
            nome = info.get("nome_arquivo") or f"OrbePC_firmware_v{info['versao']}.bin"
            destino = os.path.join(CONFIG_DIR, "firmware_cache", nome)

            btn_baixar_fw.configure(state="disabled", text="Baixando…")
            escrever_log(f"Baixando firmware v{info['versao']}...")

            def callback_download(linha):
                janela.after(0, lambda: escrever_log(linha))

            def ao_terminar_download(erro):
                def _ui():
                    btn_baixar_fw.configure(state="normal", text="Baixar e preparar")
                    if erro is None:
                        estado_arquivo["caminho"] = destino
                        lbl_arquivo.configure(text=os.path.basename(destino), text_color=COR_TEXTO)
                        btn_aplicar.configure(state="normal")
                        escrever_log("✔ Firmware baixado e pronto -- clique em Aplicar quando quiser gravar.")
                    else:
                        escrever_log(f"✘ Falha ao baixar firmware: {erro}")
                janela.after(0, _ui)

            atualizacao_engine.baixar_arquivo_async(
                info["url"], destino, callback=callback_download, ao_terminar=ao_terminar_download)

        btn_baixar_fw = ctk.CTkButton(card_fw_att, text="Baixar e preparar", command=baixar_e_preparar_firmware,
                                      fg_color=COR_ACCENT, hover_color=COR_ACCENT_HOVER,
                                      text_color="#1a1a1a", font=(FONTE, 11, "bold"),
                                      corner_radius=8, height=28, width=140)
        btn_baixar_fw.pack(side="right", padx=14)

        firmware_ui["card_att"] = card_fw_att
        firmware_ui["label_att"] = lbl_fw_att
        firmware_ui["ancora_att"] = card
        firmware_ui["mostrado_att"] = False

        # ----- selecao manual do arquivo .bin -----
        estado_arquivo = {"caminho": None}

        linha_arquivo = ctk.CTkFrame(card, fg_color="transparent")
        linha_arquivo.pack(fill="x", padx=14, pady=(0, 12))

        lbl_arquivo = ctk.CTkLabel(linha_arquivo, text="Nenhum arquivo selecionado",
                                   font=(FONTE, 11), text_color=COR_TEXTO_MUTED,
                                   anchor="w")
        lbl_arquivo.pack(side="left", fill="x", expand=True)

        def selecionar_arquivo():
            from tkinter import filedialog
            caminho = filedialog.askopenfilename(
                parent=janela,
                title="Selecione o firmware (.bin) do OrbePC",
                filetypes=[("Firmware ESP32 (.bin)", "*.bin"), ("Todos os arquivos", "*.*")],
            )
            if not caminho:
                return
            estado_arquivo["caminho"] = caminho
            lbl_arquivo.configure(text=os.path.basename(caminho), text_color=COR_TEXTO)
            btn_aplicar.configure(state="normal")

        btn_selecionar = ctk.CTkButton(linha_arquivo, text="Selecionar…", command=selecionar_arquivo,
                                       fg_color="transparent", hover_color=COR_HOVER_NAV,
                                       text_color=COR_TEXTO, font=(FONTE, 11),
                                       border_width=1, border_color=COR_BORDA,
                                       corner_radius=8, height=28, width=110)
        btn_selecionar.pack(side="right", padx=(8, 0))

        log_box = ctk.CTkTextbox(interno, height=170, fg_color=COR_FUNDO_CARD,
                                 text_color=COR_TEXTO_MUTED, font=("Consolas", 10),
                                 border_width=1, border_color=COR_BORDA, corner_radius=8)
        log_box.pack(fill="both", expand=True, pady=(0, 10))
        log_box.configure(state="disabled")

        def escrever_log(texto):
            log_box.configure(state="normal")
            log_box.insert("end", texto + "\n")
            log_box.see("end")
            log_box.configure(state="disabled")

        def callback_progresso(linha):
            # vem da thread de gravacao (firmware_engine) -- widgets tkinter
            # so podem ser tocados pela thread da janela, entao agenda de volta
            janela.after(0, lambda: escrever_log(linha))

        def ao_terminar(erro):
            def _atualizar_ui():
                btn_aplicar.configure(state="normal", text="Aplicar")
                btn_selecionar.configure(state="normal")
                if erro is None:
                    escrever_log("✔ Firmware gravado com sucesso. O display deve reiniciar sozinho.")
                else:
                    escrever_log(f"✘ Falha ao gravar: {erro}")
                pausar_para_flash.clear()  # devolve a porta pro monitoramento normal
            janela.after(0, _atualizar_ui)

        def aplicar_firmware():
            caminho = estado_arquivo["caminho"]
            if not caminho:
                escrever_log("✘ Selecione um arquivo .bin antes de aplicar.")
                return
            porta_atual = estado.snapshot()["porta"]
            if not porta_atual:
                escrever_log("✘ Nenhum OrbePC conectado agora -- conecte o cabo USB e tente de novo.")
                return

            import tkinter.messagebox as messagebox
            if not messagebox.askyesno(
                "Atualizar firmware",
                f"Isso vai gravar \"{os.path.basename(caminho)}\" no OrbePC conectado "
                f"em {porta_atual}.\n\nNão desconecte o cabo USB durante o processo "
                "(leva alguns segundos). Continuar?",
                parent=janela,
            ):
                return

            btn_aplicar.configure(state="disabled", text="Gravando…")
            btn_selecionar.configure(state="disabled")
            log_box.configure(state="normal")
            log_box.delete("1.0", "end")
            log_box.configure(state="disabled")
            escrever_log(f"Gravando {os.path.basename(caminho)} em {porta_atual}...")

            # trava o thread de monitoramento fora da porta ANTES de comecar --
            # o esptool precisa da porta sozinho (ver comentario em pausar_para_flash)
            pausar_para_flash.set()
            janela.after(600, lambda: firmware_engine.gravar_firmware_async(
                porta_atual, caminho, callback=callback_progresso, ao_terminar=ao_terminar))

        btn_aplicar = ctk.CTkButton(interno, text="Aplicar", command=aplicar_firmware,
                                   state="disabled",
                                   fg_color=COR_ACCENT, hover_color=COR_ACCENT_HOVER,
                                   text_color="#1a1a1a", font=(FONTE, 12, "bold"),
                                   corner_radius=8, height=32, width=140)
        btn_aplicar.pack(anchor="w")

        firmware_ui["lbl_instalada"] = lbl_instalada
        return f

    # -------------------- navegacao (sidebar) --------------------
    ctk.CTkLabel(sidebar, text="OrbePC", font=(FONTE, 15, "bold"),
                 text_color=COR_ACCENT, anchor="w").pack(anchor="w", padx=18, pady=(14, 10))

    paginas = {
        "Métricas": montar_aba_metricas(conteudo),
        "Telas": montar_aba_telas(conteudo),
        "Sensores": montar_aba_sensores(conteudo),
        "Alertas": montar_aba_alertas(conteudo),
        "Geral": montar_aba_geral(conteudo),
        "Firmware": montar_aba_firmware(conteudo),
    }
    botoes_nav = {}

    def mostrar_pagina(nome):
        for pag in paginas.values():
            pag.pack_forget()
        paginas[nome].pack(fill="both", expand=True)
        for n, b in botoes_nav.items():
            if n == nome:
                b.configure(fg_color=COR_ACCENT_BG, text_color=COR_ACCENT)
            else:
                b.configure(fg_color="transparent", text_color=COR_TEXTO_MUTED)

    for nome in paginas:
        b = ctk.CTkButton(sidebar, text=nome, anchor="w", corner_radius=8,
                          fg_color="transparent", hover_color=COR_HOVER_NAV,
                          text_color=COR_TEXTO_MUTED, font=(FONTE, 13), height=34,
                          command=lambda n=nome: mostrar_pagina(n))
        b.pack(fill="x", padx=8, pady=2)
        botoes_nav[nome] = b

    # status no pe da sidebar (bolinha colorida + texto)
    lbl_status = ctk.CTkLabel(sidebar, text="●  …", font=(FONTE, 11),
                              text_color=COR_TEXTO_MUTED, anchor="w")
    lbl_status.pack(side="bottom", fill="x", padx=16, pady=12)

    # um unico loop de 1s atualiza status E a pre-visualizacao ao vivo
    def loop_atualizacao():
        try:
            if not janela.winfo_exists():
                return
            snap = estado.snapshot()
            if snap["pausado"]:
                lbl_status.configure(text="●  Envio pausado", text_color=COR_TEXTO_MUTED)
            elif snap["conectado"]:
                lbl_status.configure(text=f"●  {snap['porta'] or '?'} conectado",
                                     text_color=COR_VERDE)
            else:
                lbl_status.configure(text="●  Aguardando USB…",
                                     text_color=COR_AGUARDANDO)
            atualizar_preview(snap)
            if "lbl_instalada" in firmware_ui:
                versao = snap["versao_firmware"]
                firmware_ui["lbl_instalada"].configure(
                    text=f"Versão instalada: {versao}" if versao
                    else "Versão instalada: aguardando conexão do display…")
            if "card" in atualizacao_ui:
                info = snap.get("atualizacao_disponivel")
                if info and not atualizacao_ui["mostrado"]:
                    atualizacao_ui["label"].configure(
                        text=f"Nova versão do OrbePC disponível: v{info['versao']}")
                    atualizacao_ui["card"].pack(fill="x", pady=(0, 14), before=atualizacao_ui["ancora"])
                    atualizacao_ui["mostrado"] = True
                elif not info and atualizacao_ui["mostrado"]:
                    atualizacao_ui["card"].pack_forget()
                    atualizacao_ui["mostrado"] = False

            if "card_att" in firmware_ui:
                fw_info = snap.get("firmware_disponivel")
                versao_conectada = snap.get("versao_firmware")
                # so mostra o aviso se: tem release de firmware achada E
                # (nao sabemos a versao conectada ainda, OU ela e' mais
                # velha que a disponivel) -- sem isso, avisaria pra sempre
                # mesmo com o display ja atualizado
                deve_mostrar = bool(fw_info) and (
                    versao_conectada is None
                    or atualizacao_engine.eh_mais_nova(fw_info["versao"], versao_conectada)
                )
                if deve_mostrar and not firmware_ui["mostrado_att"]:
                    firmware_ui["label_att"].configure(
                        text=f"Novo firmware disponível: v{fw_info['versao']}")
                    firmware_ui["card_att"].pack(fill="x", pady=(0, 12), before=firmware_ui["ancora_att"])
                    firmware_ui["mostrado_att"] = True
                elif not deve_mostrar and firmware_ui["mostrado_att"]:
                    firmware_ui["card_att"].pack_forget()
                    firmware_ui["mostrado_att"] = False
            janela.after(1000, loop_atualizacao)
        except Exception:
            pass  # janela fechada no meio do caminho

    mostrar_pagina("Métricas")
    loop_atualizacao()

    _janela_config = janela
    return janela


# ---------------------------------------------------------------------
# BANDEJA (pystray) -- roda numa thread separada; qualquer coisa que
# precise abrir janela do tkinter e agendada de volta pro loop principal
# via root.after(...), porque widgets tkinter so podem ser mexidos pela
# thread que criou o root.
# ---------------------------------------------------------------------
def gerar_icone(cor_rgb):
    # anel colorido (status) sobre um bezel escuro -- mesma linguagem
    # visual do gabinete fisico (aro na cor de destaque em cima do
    # bezel escuro), em vez de um circulo solido generico
    from PIL import Image, ImageDraw
    tam = 64
    img = Image.new("RGBA", (tam, tam), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, tam - 4, tam - 4), fill=(26, 26, 26, 255))
    draw.ellipse((10, 10, tam - 10, tam - 10), outline=cor_rgb, width=7)
    return img


def cor_status():
    snap = estado.snapshot()
    if snap["pausado"]:
        return (154, 154, 154, 255)  # cinza
    if snap["conectado"]:
        return (29, 158, 117, 255)   # verde
    return (216, 90, 48, 255)        # laranja/coral -- aguardando


def montar_tray(root, parar_evento):
    import pystray
    from pystray import MenuItem as Item

    def abrir_configuracoes(icon=None, item=None):
        root.after(0, lambda: abrir_janela_configuracoes(root))

    def alternar_pausa(icon=None, item=None):
        snap = estado.snapshot()
        estado.atualizar(pausado=not snap["pausado"])

    def proxima_tela(icon=None, item=None):
        estado.atualizar(trocar_tela=True)  # a thread de monitoramento consome

    def esta_pausado(item=None):
        return estado.snapshot()["pausado"]

    def ver_log(icon=None, item=None):
        try:
            os.startfile(LOG_PATH)
        except Exception:
            log("Nao consegui abrir o log automaticamente.")

    def sair(icon=None, item=None):
        parar_evento.set()
        icon.stop()
        root.after(0, root.destroy)

    menu = pystray.Menu(
        Item("Configurações", abrir_configuracoes, default=True),
        Item("Próxima tela", proxima_tela),
        Item("Pausar envio", alternar_pausa, checked=esta_pausado),
        Item("Ver log", ver_log),
        pystray.Menu.SEPARATOR,
        Item("Sair", sair),
    )

    icon = pystray.Icon("OrbePC", gerar_icone(cor_status()), "OrbePC", menu)

    def atualizar_icone_periodicamente():
        ultimo = None
        while not parar_evento.is_set():
            cor = cor_status()
            if cor != ultimo:
                icon.icon = gerar_icone(cor)
                snap = estado.snapshot()
                if snap["pausado"]:
                    icon.title = "OrbePC — pausado"
                elif snap["conectado"]:
                    icon.title = "OrbePC — conectado, enviando dados"
                else:
                    icon.title = "OrbePC — aguardando dispositivo USB"
                ultimo = cor
            time.sleep(1)

    threading.Thread(target=atualizar_icone_periodicamente, daemon=True).start()
    icon.run()


# ---------------------------------------------------------------------
def main():
    # a leitura direta de sensores exige admin -- se nao estiver elevado,
    # relanca com UAC e encerra esta instancia (nao roda nada sem admin,
    # senao o app abriria com todos os sensores vazios)
    if not esta_elevado():
        elevar_e_reiniciar()
        return

    # so depois da elevacao (a instancia nao-elevada morre logo em seguida,
    # nao pode segurar o mutex e bloquear a copia elevada que ela mesma abriu)
    if ja_esta_rodando():
        log("OrbePC ja esta aberto -- encerrando esta segunda instancia.")
        return

    # driver de CPU (PawnIO) -- instala sozinho se faltar, antes de
    # qualquer leitura de sensor (ver comentario em garantir_pawnio())
    garantir_pawnio()

    # confere versao nova no GitHub Releases em segundo plano -- nunca
    # bloqueia o startup, e simplesmente nao acontece nada se der erro
    # (sem internet, repo sem releases ainda, etc, ver atualizacao_engine.py)
    atualizacao_engine.verificar_async(
        APP_VERSAO, lambda r: estado.atualizar(atualizacao_disponivel=r))
    atualizacao_engine.buscar_firmware_disponivel_async(
        lambda r: estado.atualizar(firmware_disponivel=r))

    import customtkinter as ctk
    ctk.set_appearance_mode("dark")  # inclusive a barra de titulo escura no Windows

    parar_evento = threading.Event()

    threading.Thread(target=thread_monitoramento, args=(parar_evento,), daemon=True).start()

    # atalho global salvo de execucoes anteriores (se houver)
    atalho_global.aplicar(config.get("atalhoTela") or "")

    # cidade do clima salva de execucoes anteriores (se houver)
    if config.get("climaLat") is not None:
        clima_engine.configurar(config.get("climaLat"), config.get("climaLon"))

    root = ctk.CTk()
    root.withdraw()  # a janela principal fica escondida -- so existe pra hospedar o mainloop

    threading.Thread(target=montar_tray, args=(root, parar_evento), daemon=True).start()

    root.mainloop()


if __name__ == "__main__":
    main()
