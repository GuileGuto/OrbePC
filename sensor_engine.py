"""
sensor_engine.py -- le a arvore JSON do LibreHardwareMonitor e detecta os
sensores certos (CPU, GPU, RAM, VRAM) de forma resiliente a hardware
diferente (Intel/AMD, NVIDIA/AMD/Intel, com ou sem GPU integrada).

Sem essa camada, o jeito antigo (monitor_usb.py) procurava por nomes de
texto EXATOS tipo "CPU Package" ou "GPU Core" -- isso quebra em CPU AMD
(que usa outros nomes) ou em maquinas com GPU integrada + dedicada (que
podem ter sensores homonimos nos dois lugares). Aqui a logica e em
camadas:

  1. Acha os "ramos" de hardware pelo prefixo do SensorId (ex:
     /amdcpu/0, /intelcpu/0, /gpu-nvidia/0, /gpu-amd/0, /ram) -- isso e
     mais estavel que o texto, que pode variar por geracao/idioma.
  2. Dentro do ramo certo, tenta uma lista de nomes candidatos em ordem
     de prioridade (mais especifico primeiro).
  3. Se nenhum nome bater, cai num fallback generico (primeiro sensor
     daquela unidade -- Celsius, %, GB -- dentro do ramo).
  4. Se o usuario tiver fixado manualmente um SensorId (override, vindo
     da aba "Sensores" do app), esse override tem prioridade sobre tudo.

Cada resultado guarda TAMBEM a lista de candidatos encontrados, pra
alimentar os dropdowns de ajuste manual na interface.
"""

import time
import traceback

import requests


LHM_URL = "http://localhost:8085/data.json"

# prefixos de SensorId por tipo de hardware, em ordem de preferencia
# (usado sobretudo pra GPU: se tiver dedicada, prefere ela a integrada)
PREFIXOS_CPU = ("/amdcpu", "/intelcpu", "/cpu")
PREFIXOS_GPU_DEDICADA = ("/gpu-nvidia", "/gpu-amd")
PREFIXOS_GPU_TODAS = ("/gpu-nvidia", "/gpu-amd", "/gpu-intel")
PREFIXO_RAM = "/ram"
PREFIXOS_DISCO = ("/nvme", "/ssd", "/hdd", "/storage")
PREFIXO_NIC = "/nic"

CANDIDATOS_CPU_TEMP = [
    "CPU Package", "CPU Die (average)", "Core (Tctl/Tdie)",
    "Core Average", "Core Max", "CPU Die",
]
CANDIDATOS_CPU_LOAD = ["CPU Total"]
CANDIDATOS_GPU_TEMP = [
    "GPU Core", "GPU Hot Spot", "GPU Junction", "GPU Edge", "Core",
]
CANDIDATOS_GPU_LOAD = ["GPU Core", "D3D 3D", "GPU Video Engine"]
CANDIDATOS_VRAM = [
    "GPU Memory Used",            # GPU dedicada (VRAM propria)
    "D3D Dedicated Memory Used",  # via contadores do Windows (qualquer GPU)
    "D3D Shared Memory Used",     # GPU integrada usando RAM compartilhada
]
CANDIDATOS_RAM_GB = ["Memory Used"]
CANDIDATOS_RAM_PCT = ["Memory"]


class SensorLido:
    """Um sensor bruto encontrado na arvore do LHM."""

    __slots__ = ("texto", "valor_raw", "numero", "sensor_id", "caminho_hw")

    def __init__(self, texto, valor_raw, numero, sensor_id, caminho_hw):
        self.texto = texto
        self.valor_raw = valor_raw   # string original, ex: "45,3 °C"
        self.numero = numero         # float
        self.sensor_id = sensor_id
        self.caminho_hw = caminho_hw  # prefixo do ramo de hardware, ex: "/gpu-nvidia/0"

    def unidade(self):
        v = self.valor_raw
        if "°C" in v or (" C" in v and "MHz" not in v):
            return "C"
        if "%" in v:
            return "%"
        if "B/s" in v:
            return "B/s"   # Throughput (disco leitura/escrita, rede down/up)
        if "RPM" in v:
            return "RPM"
        if "GB" in v:
            return "GB"
        if "MB" in v:
            return "MB"
        if "MHz" in v:
            return "MHz"
        return "?"

    def to_dict(self):
        return {
            "texto": self.texto,
            "valor_raw": self.valor_raw,
            "sensor_id": self.sensor_id,
        }


def _ramo_hw(sensor_id):
    """Extrai algo tipo '/gpu-nvidia/0' de '/gpu-nvidia/0/temperature/2'."""
    partes = [p for p in sensor_id.split("/") if p]
    if len(partes) >= 2:
        return "/" + "/".join(partes[:2])
    if len(partes) == 1:
        return "/" + partes[0]
    return sensor_id


def buscar_arvore(url=LHM_URL, timeout=(2, 3)):
    r = requests.get(url, timeout=timeout, headers={"Connection": "close"})
    r.raise_for_status()
    return r.json()


def listar_sensores(arvore):
    """Achata a arvore inteira numa lista de SensorLido."""
    resultado = []

    def percorrer(no):
        texto = no.get("Text", "")
        valor = no.get("Value", "")
        sensor_id = no.get("SensorId", "") or ""
        if texto and valor and sensor_id:
            v = valor.replace(",", ".")
            partes = v.split()
            numero = None
            if partes:
                try:
                    numero = float(partes[0])
                except ValueError:
                    numero = None
            if numero is not None:
                resultado.append(SensorLido(texto, v, numero, sensor_id, _ramo_hw(sensor_id)))
        for filho in no.get("Children", []):
            percorrer(filho)

    percorrer(arvore)
    return resultado


# ---------------------------------------------------------------------
# LEITURA DIRETA (sem depender do LibreHardwareMonitor aberto separado)
# -- usa a LibreHardwareMonitorLib (a mesma biblioteca por tras do LHM)
# direto via pythonnet, atraves do pacote "HardwareMonitor" do PyPI.
# Precisa rodar como administrador (mesma exigencia que o LHM.exe
# sempre teve pra ler os sensores de baixo nivel).
# ---------------------------------------------------------------------

# unidade que cada SensorType da LibreHardwareMonitorLib usa -- usado so
# pra montar uma string tipo "45.0 °C" equivalente a que vinha do JSON,
# assim SensorLido.unidade() e o resto da logica de deteccao (abaixo)
# funcionam identicos, sem precisar duplicar nada.
SENSOR_TYPE_UNIDADE = {
    "Temperature": "°C",
    "Load": "%",
    "Data": "GB",        # RAM usada, por ex.
    "SmallData": "MB",   # VRAM, por ex. -- LHM usa um tipo separado pra valores menores
    "Clock": "MHz",
    "Power": "W",
    "Voltage": "V",
    "Fan": "RPM",
    "Throughput": "B/s",  # disco leitura/escrita, rede down/up (bytes por segundo)
}


def abrir_computer_dotnet():
    """Abre e atualiza um Computer da LibreHardwareMonitorLib com CPU,
    GPU, memoria, placa-mae (fans), armazenamento e rede habilitados --
    os tres ultimos alimentam as telas personalizadas. Precisa ser
    chamado com o processo rodando como administrador -- senao a maioria
    dos sensores vem vazia (mesma limitacao que o LibreHardwareMonitor.exe
    sempre teve).

    Retorna o objeto computer ja aberto -- guarda essa referencia e
    chama computer.Update() a cada ciclo (nao abra um novo Computer toda
    hora, e mais pesado que so atualizar)."""
    from HardwareMonitor.Util import OpenComputer
    try:
        computer = OpenComputer(cpu=True, gpu=True, memory=True,
                                motherboard=True, storage=True, network=True)
    except TypeError:
        # versao mais antiga do pacote sem esses kwargs -- abre o basico
        # e liga o resto pelas propriedades do proprio Computer
        computer = OpenComputer(cpu=True, gpu=True, memory=True)
        for prop in ("IsMotherboardEnabled", "IsStorageEnabled", "IsNetworkEnabled"):
            try:
                setattr(computer, prop, True)
            except Exception:
                pass
    return computer


def listar_sensores_dotnet(computer):
    """Equivalente a listar_sensores(), mas lendo direto do objeto
    Computer da LibreHardwareMonitorLib (ja aberto e atualizado) em vez
    da arvore JSON do servidor web do LHM. Produz a MESMA lista de
    SensorLido, entao toda a logica de deteccao abaixo (camadas,
    candidatos, fallback) funciona sem nenhuma alteracao."""
    resultado = []

    def coletar(hardware):
        for sensor in hardware.Sensors:
            try:
                numero = float(sensor.Value)
            except (TypeError, ValueError):
                continue  # sensor sem leitura ainda (None) -- ignora nesse ciclo

            nome = str(sensor.Name)
            sensor_id = str(sensor.Identifier)
            tipo = str(sensor.SensorType)
            unidade = SENSOR_TYPE_UNIDADE.get(tipo, "")
            valor_raw = f"{numero} {unidade}".strip()

            resultado.append(SensorLido(nome, valor_raw, numero, sensor_id, _ramo_hw(sensor_id)))

        for sub in hardware.SubHardware:
            coletar(sub)

    for hw in computer.Hardware:
        coletar(hw)

    return resultado


def atualizar_computer_dotnet(computer, incluir_lentos=True):
    """Update() seletivo do Computer. O update de Storage le SMART do
    disco, e em varios modelos isso TRAVA o processo por varios segundos
    -- rodando a cada ciclo de 1s, o envio serial para, o display estoura
    o timeout de "sem dados" e recria a tela inteira (parece bug de tela
    piscando/recriada). Entao: todo o resto atualiza sempre, e Storage
    so quando incluir_lentos=True (o app passa True de tempos em tempos)."""
    for hw in computer.Hardware:
        try:
            if not incluir_lentos and str(hw.HardwareType) == "Storage":
                continue
            hw.Update()
            for sub in hw.SubHardware:
                sub.Update()
        except Exception:
            pass  # um hardware problematico nao pode derrubar o ciclo inteiro


def _filtra(sensores, prefixos=None, unidade=None, contem_texto=None, exclui_texto_substr=None):
    out = []
    for s in sensores:
        if prefixos is not None and not s.sensor_id.startswith(prefixos):
            continue
        if unidade is not None and s.unidade() != unidade:
            continue
        if contem_texto is not None and contem_texto not in s.texto:
            continue
        if exclui_texto_substr is not None and exclui_texto_substr in s.texto:
            continue
        out.append(s)
    return out


def _escolher(candidatos, nomes_prioritarios, override_sensor_id=None):
    """Retorna (escolhido, lista_candidatos_dict) -- escolhido pode ser None."""
    cand_dicts = [c.to_dict() for c in candidatos]

    if override_sensor_id:
        for c in candidatos:
            if c.sensor_id == override_sensor_id:
                return c, cand_dicts

    por_nome = {}
    for c in candidatos:
        por_nome.setdefault(c.texto, c)
    for nome in nomes_prioritarios:
        if nome in por_nome:
            return por_nome[nome], cand_dicts

    if candidatos:
        return candidatos[0], cand_dicts
    return None, cand_dicts


def _ramo_gpu_preferido(sensores):
    """Escolhe qual GPU usar: dedicada (nvidia/amd) antes de integrada
    (intel), e entre dedicadas, a que tiver mais sensores validos."""
    ramos = {}
    for s in sensores:
        for prefixo in PREFIXOS_GPU_TODAS:
            if s.sensor_id.startswith(prefixo):
                ramos.setdefault(s.caminho_hw, []).append(s)
                break

    if not ramos:
        return None, []

    def prioridade(caminho):
        if caminho.startswith("/gpu-nvidia"):
            return 0
        if caminho.startswith("/gpu-amd"):
            return 1
        return 2  # intel (normalmente integrada)

    melhor = sorted(ramos.keys(), key=lambda c: (prioridade(c), -len(ramos[c])))[0]
    return melhor, ramos[melhor]


def detectar_tudo(arvore, overrides=None):
    """Atalho pro caminho antigo (JSON via HTTP do LibreHardwareMonitor):
    achata a arvore e delega pra detectar_tudo_com_sensores(). Mantido
    por compatibilidade -- o caminho novo (leitura direta da lib, sem
    depender do LHM aberto) usa detectar_tudo_com_sensores() direto,
    passando a lista vinda de listar_sensores_dotnet()."""
    return detectar_tudo_com_sensores(listar_sensores(arvore), overrides)


def detectar_tudo_com_sensores(sensores, overrides=None):
    """Mesma logica de deteccao em camadas de detectar_tudo(), mas
    recebendo a lista de SensorLido ja pronta -- assim funciona tanto
    com sensores vindos do JSON do LHM quanto direto da
    LibreHardwareMonitorLib (via pythonnet), sem duplicar a logica de
    prioridade/candidatos/fallback.

    overrides: dict opcional {"cpuTemp": "sensor_id_fixado", ...}
    """
    overrides = overrides or {}
    resultado = {}

    def registrar(chave, valor_sensor, candidatos_dict, conversor=lambda s: s.numero):
        if valor_sensor is not None:
            resultado[chave] = {
                "valor": conversor(valor_sensor),
                "texto": valor_sensor.texto,
                "sensor_id": valor_sensor.sensor_id,
                "candidatos": candidatos_dict,
            }
        else:
            resultado[chave] = {"valor": None, "texto": None, "sensor_id": None, "candidatos": candidatos_dict}

    # ---- CPU ----
    cpu_temp_cand = _filtra(sensores, prefixos=PREFIXOS_CPU, unidade="C")
    cpu_temp_cand = [c for c in cpu_temp_cand if c.numero > 5]
    escolhido, cands = _escolher(cpu_temp_cand, CANDIDATOS_CPU_TEMP, overrides.get("cpuTemp"))

    # camada extra: maquinas onde o ramo da CPU nao expoe temperatura
    # nenhuma (comum em PCs simples/antigos) mas a placa-mae expoe via
    # SuperIO -- procura ali qualquer temperatura com "CPU" no nome
    if escolhido is None:
        superio_cand = [s for s in _filtra(sensores, unidade="C")
                        if s.sensor_id.startswith(("/lpc", "/motherboard"))
                        and "cpu" in s.texto.lower() and s.numero > 5]
        escolhido, cands_superio = _escolher(
            superio_cand, ["CPU", "CPU Package", "CPU Socket", "CPUTIN", "CPU Core"],
            overrides.get("cpuTemp"))
        if escolhido is not None:
            cands = cands_superio

    registrar("cpuTemp", escolhido, cands)

    cpu_load_cand = _filtra(sensores, prefixos=PREFIXOS_CPU, unidade="%")
    escolhido, cands = _escolher(cpu_load_cand, CANDIDATOS_CPU_LOAD, overrides.get("cpuLoad"))
    registrar("cpuLoad", escolhido, cands)

    # ---- GPU (dedicada de preferencia) ----
    ramo_gpu, sensores_gpu = _ramo_gpu_preferido(sensores)

    gpu_temp_cand = _filtra(sensores_gpu, unidade="C")
    gpu_temp_cand = [c for c in gpu_temp_cand if c.numero > 5]
    escolhido, cands = _escolher(gpu_temp_cand, CANDIDATOS_GPU_TEMP, overrides.get("gpuTemp"))
    registrar("gpuTemp", escolhido, cands)

    gpu_load_cand = _filtra(sensores_gpu, unidade="%")
    escolhido, cands = _escolher(gpu_load_cand, CANDIDATOS_GPU_LOAD, overrides.get("gpuLoad"))
    registrar("gpuLoad", escolhido, cands)

    vram_cand = _filtra(sensores_gpu, contem_texto="Memory Used")
    vram_cand = [c for c in vram_cand if c.unidade() in ("GB", "MB")]
    escolhido, cands = _escolher(vram_cand, CANDIDATOS_VRAM, overrides.get("vram"))

    def conv_vram(s):
        return s.numero if s.unidade() == "GB" else s.numero / 1024.0

    registrar("vram", escolhido, cands, conv_vram)

    # ---- RAM ----
    ram_gb_cand = _filtra(sensores, prefixos=(PREFIXO_RAM,), unidade="GB", contem_texto="Memory Used")
    escolhido, cands = _escolher(ram_gb_cand, CANDIDATOS_RAM_GB, overrides.get("ram"))
    registrar("ram", escolhido, cands)

    ram_pct_cand = _filtra(sensores, prefixos=(PREFIXO_RAM,), unidade="%")
    escolhido, cands = _escolher(ram_pct_cand, CANDIDATOS_RAM_PCT, overrides.get("ramPct"))
    registrar("ramPct", escolhido, cands)

    # ---- GPU INTEGRADA SEM SENSOR DE TEMPERATURA ----
    # iGPU Intel nao tem sensor termico proprio na LibreHardwareMonitorLib
    # -- e fisicamente ela E' o mesmo chip da CPU. Pra nao deixar "GPU --"
    # eterno em PCs sem placa dedicada, usa a temperatura da CPU como
    # aproximacao honesta (o texto deixa claro que e' isso).
    if (resultado["gpuTemp"]["valor"] is None
            and ramo_gpu is not None and ramo_gpu.startswith("/gpu-intel")
            and resultado["cpuTemp"]["valor"] is not None):
        resultado["gpuTemp"] = {
            "valor": resultado["cpuTemp"]["valor"],
            "texto": "≈ temperatura da CPU (GPU integrada, mesmo chip)",
            "sensor_id": None,
            "candidatos": resultado["gpuTemp"]["candidatos"],
        }

    # ---- CLOCK (informativo, mantido do formato antigo) ----
    clk_cand = _filtra(sensores, prefixos=PREFIXOS_CPU, unidade="MHz")
    escolhido, cands = _escolher(clk_cand, ["CPU Core #1", "P-Core #1", "Core #1"], overrides.get("cpuClock"))
    registrar("cpuClock", escolhido, cands)

    # ---- METRICAS EXTRAS (telas personalizadas) ----
    conv_mbs = lambda s: s.numero / 1048576.0  # Throughput vem em bytes/s

    # VRAM em % ("GPU Memory" tipo Load) e clock da GPU
    vram_pct_cand = _filtra(sensores_gpu, unidade="%", contem_texto="Memory")
    escolhido, cands = _escolher(vram_pct_cand, ["GPU Memory"], overrides.get("vramPct"))
    registrar("vramPct", escolhido, cands)

    gpu_clk_cand = _filtra(sensores_gpu, unidade="MHz")
    escolhido, cands = _escolher(gpu_clk_cand, ["GPU Core"], overrides.get("gpuClock"))
    registrar("gpuClock", escolhido, cands)

    # Disco: escolhe o ramo de armazenamento com mais sensores (via de
    # regra o disco do sistema) e tira dele uso/temp/leitura/escrita
    ramos_disco = {}
    for s in sensores:
        if s.sensor_id.startswith(PREFIXOS_DISCO):
            ramos_disco.setdefault(s.caminho_hw, []).append(s)
    sensores_disco = max(ramos_disco.values(), key=len) if ramos_disco else []

    # "Used Space" = % do ESPACO ocupado (capacidade). NAO confundir com
    # atividade (% do tempo ocupado lendo/escrevendo -- o "uso de disco"
    # que o Gerenciador de Tarefas mostra). Sao metricas diferentes e a
    # lib expoe as duas -- registradas separadas pro usuario escolher.
    escolhido, cands = _escolher(_filtra(sensores_disco, unidade="%", exclui_texto_substr="Activity"),
                                 ["Used Space"], overrides.get("discoPct"))
    registrar("discoPct", escolhido, cands)
    escolhido, cands = _escolher(_filtra(sensores_disco, unidade="%", contem_texto="Activity"),
                                 ["Total Activity", "Write Activity"], overrides.get("discoAtividade"))
    registrar("discoAtividade", escolhido, cands)
    escolhido, cands = _escolher(_filtra(sensores_disco, unidade="C"),
                                 ["Temperature"], overrides.get("discoTemp"))
    registrar("discoTemp", escolhido, cands)
    escolhido, cands = _escolher(_filtra(sensores_disco, unidade="B/s", contem_texto="Read"),
                                 ["Read Rate"], overrides.get("discoRead"))
    registrar("discoRead", escolhido, cands, conv_mbs)
    escolhido, cands = _escolher(_filtra(sensores_disco, unidade="B/s", contem_texto="Write"),
                                 ["Write Rate"], overrides.get("discoWrite"))
    registrar("discoWrite", escolhido, cands, conv_mbs)

    # Rede: escolhe a placa com mais dados baixados acumulados (a NIC
    # "principal" -- as outras normalmente estao ociosas/virtuais)
    ramos_nic = {}
    for s in sensores:
        if s.sensor_id.startswith(PREFIXO_NIC):
            ramos_nic.setdefault(s.caminho_hw, []).append(s)

    def _baixado(ramo):
        for s in ramos_nic[ramo]:
            if s.texto == "Data Downloaded":
                return s.numero
        return 0.0

    sensores_nic = ramos_nic[max(ramos_nic, key=_baixado)] if ramos_nic else []

    escolhido, cands = _escolher(_filtra(sensores_nic, unidade="B/s", contem_texto="Download"),
                                 ["Download Speed"], overrides.get("netDown"))
    registrar("netDown", escolhido, cands, conv_mbs)
    escolhido, cands = _escolher(_filtra(sensores_nic, unidade="B/s", contem_texto="Upload"),
                                 ["Upload Speed"], overrides.get("netUp"))
    registrar("netUp", escolhido, cands, conv_mbs)

    # Fan (primeiro cooler com leitura valida; prioriza o da CPU)
    fan_cand = [s for s in _filtra(sensores, unidade="RPM") if s.numero > 0]
    escolhido, cands = _escolher(fan_cand, ["CPU Fan", "Fan #1", "GPU Fan"], overrides.get("fan"))
    registrar("fan", escolhido, cands)

    resultado["_ramo_gpu"] = ramo_gpu
    return resultado


def resumo_deteccao(resultado):
    """Quantas de quantas metricas essenciais foram detectadas -- usado
    pro contador tipo '6 de 6 sensores detectados' na aba Sensores."""
    chaves_essenciais = ["cpuTemp", "cpuLoad", "gpuTemp", "gpuLoad", "vram", "ram"]
    total = len(chaves_essenciais)
    achados = sum(1 for k in chaves_essenciais if resultado.get(k, {}).get("valor") is not None)
    return achados, total
