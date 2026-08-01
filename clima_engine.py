"""
clima_engine.py -- clima da cidade escolhida, via Open-Meteo (gratis,
sem chave de API, sem cadastro).

Duas APIs publicas:
  - Geocoding (busca de cidade por nome, em portugues):
    https://geocoding-api.open-meteo.com/v1/search
  - Tempo atual (temperatura, condicao WMO, umidade):
    https://api.open-meteo.com/v1/forecast

O tempo e' buscado em segundo plano a cada 15 minutos (1 requisicao) e
fica em cache -- o display le do cache no ciclo normal de 1s. Sem
internet ou sem cidade configurada, as metricas so mostram "--".

Nota comercial: o plano gratuito da Open-Meteo e' para uso nao-comercial.
Quando o OrbePC virar produto em escala, contratar o plano da API
(barato) ou trocar a URL por outra fonte -- o resto do codigo fica igual.
"""

import threading
import time

import requests

URL_GEO = "https://geocoding-api.open-meteo.com/v1/search"
URL_TEMPO = "https://api.open-meteo.com/v1/forecast"
INTERVALO = 15 * 60  # segundos entre atualizacoes do tempo

# codigos WMO -> condicao curta em PT (max 10 chars -- largura da linha
# no display). Referencia: doc da Open-Meteo, campo weather_code.
_WMO = {
    0: "SOL", 1: "QUASE SOL", 2: "P.NUBLADO", 3: "NUBLADO",
    45: "NEVOEIRO", 48: "NEVOEIRO",
    51: "GAROA", 53: "GAROA", 55: "GAROA", 56: "GAROA", 57: "GAROA",
    61: "CHUVA", 63: "CHUVA", 65: "CHUVA FORT", 66: "CHUVA", 67: "CHUVA",
    71: "NEVE", 73: "NEVE", 75: "NEVE", 77: "NEVE", 85: "NEVE", 86: "NEVE",
    80: "PANCADAS", 81: "PANCADAS", 82: "PANCADAS",
    95: "TEMPESTADE", 96: "TEMPESTADE", 99: "TEMPESTADE",
}

_lock = threading.Lock()
_cfg = {"lat": None, "lon": None}
_cache = {"dados": None, "quando": 0.0}
_iniciado = False


def buscar_cidades(nome, quantidade=5):
    """Busca cidades por nome (em portugues). Retorna lista de dicts
    {"rotulo", "lat", "lon"} -- rotulo tipo "Ourinhos, São Paulo, Brasil".
    Chamada direta (bloqueante, ~1s) -- usar so na UI, no clique de Buscar."""
    r = requests.get(URL_GEO, params={"name": nome, "count": quantidade,
                                      "language": "pt", "format": "json"},
                     timeout=(3, 5))
    r.raise_for_status()
    resultados = []
    for c in (r.json().get("results") or []):
        partes = [c.get("name", "?")]
        if c.get("admin1"):
            partes.append(c["admin1"])
        if c.get("country"):
            partes.append(c["country"])
        resultados.append({"rotulo": ", ".join(partes),
                           "lat": c["latitude"], "lon": c["longitude"]})
    return resultados


def configurar(lat, lon):
    """Define as coordenadas e forca atualizacao no proximo ciclo."""
    with _lock:
        _cfg["lat"], _cfg["lon"] = lat, lon
        _cache["quando"] = 0.0  # invalida o cache -- busca ja no proximo giro


def _buscar_tempo(lat, lon):
    r = requests.get(URL_TEMPO, params={
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,weather_code,is_day",
        "timezone": "auto",
    }, timeout=(3, 8))
    r.raise_for_status()
    atual = r.json().get("current") or {}
    if "temperature_2m" not in atual:
        return None
    cond = _WMO.get(int(atual.get("weather_code", -1)), "?")
    # "ceu limpo" a noite nao e' SOL -- a API informa se e' dia (is_day)
    if not bool(atual.get("is_day", 1)):
        cond = {"SOL": "CEU LIMPO", "QUASE SOL": "CEU LIMPO"}.get(cond, cond)
    return {
        "temp": float(atual["temperature_2m"]),
        "umid": float(atual.get("relative_humidity_2m", -1)),
        "cond": cond,
    }


def _thread_atualizacao():
    while True:
        with _lock:
            lat, lon = _cfg["lat"], _cfg["lon"]
            vencido = time.time() - _cache["quando"] >= INTERVALO
        if lat is not None and vencido:
            try:
                dados = _buscar_tempo(lat, lon)
                with _lock:
                    _cache["dados"] = dados
                    _cache["quando"] = time.time()
            except Exception:
                # sem internet/API fora: mantem o ultimo dado por ate 1h,
                # depois assume que esta velho demais e mostra "--"
                with _lock:
                    if time.time() - _cache["quando"] > 3600:
                        _cache["dados"] = None
                    _cache["quando"] = time.time() - INTERVALO + 120  # tenta de novo em 2min
        time.sleep(15)


def atual():
    """Dict {"temp", "umid", "cond"} do cache, ou None. Primeira chamada
    liga a thread de atualizacao (lazy -- sem tela de clima, zero rede)."""
    global _iniciado
    with _lock:
        if not _iniciado:
            _iniciado = True
            threading.Thread(target=_thread_atualizacao, daemon=True).start()
        return dict(_cache["dados"]) if _cache["dados"] else None
