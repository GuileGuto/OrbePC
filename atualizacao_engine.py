"""
atualizacao_engine.py -- confere se ha uma versao mais nova do proprio
OrbePC.exe publicada no GitHub Releases, e devolve os dados pro app avisar
o usuario. NAO baixa nem substitui o executavel sozinho -- um app tentando
se auto-substituir enquanto esta rodando no Windows e' fragil (arquivo em
uso, precisa reiniciar, etc.); e' bem mais simples e seguro so abrir a
pagina de download no navegador e deixar o usuario baixar/trocar na mao.

Repositorio: https://github.com/GuileGuto/OrbePC
Pra publicar uma versao nova: cria uma Release no GitHub com uma tag tipo
"v1.1.0" (o "v" na frente e' opcional, ignorado na comparacao) e anexa o
OrbePC.exe novo nela -- o app confere a tag mais recente e compara com
APP_VERSAO (definida em orbepc_app.py).
"""

import threading

import requests

REPO = "GuileGuto/OrbePC"
URL_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"


def _versao_tupla(v):
    """'v1.10.2' -> (1, 10, 2). Tolerante a sufixos tipo '-beta' (ignora
    tudo que nao for digito dentro de cada parte)."""
    v = (v or "").strip()
    if v[:1] in ("v", "V"):
        v = v[1:]
    partes = []
    for p in v.split("."):
        num = ""
        for c in p:
            if c.isdigit():
                num += c
            else:
                break
        partes.append(int(num) if num else 0)
    while len(partes) < 3:
        partes.append(0)
    return tuple(partes[:3])


def verificar(versao_atual, timeout=(3, 5)):
    """Retorna {"versao": "1.1.0", "url": "https://github.com/.../releases/tag/v1.1.0"}
    se a release mais recente do repo for mais nova que `versao_atual`, ou
    None (sem atualizacao, sem internet, repo sem releases ainda, GitHub
    fora do ar, etc. -- nunca levanta excecao, so retorna None)."""
    try:
        r = requests.get(URL_LATEST, timeout=timeout,
                          headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        dados = r.json()
        tag = dados.get("tag_name") or ""
        if not tag or _versao_tupla(tag) <= _versao_tupla(versao_atual):
            return None
        url = dados.get("html_url") or f"https://github.com/{REPO}/releases/latest"
        return {"versao": tag.lstrip("vV"), "url": url}
    except Exception:
        return None


def verificar_async(versao_atual, callback):
    """Versao nao-bloqueante de verificar() -- roda numa thread daemon e
    chama callback(resultado) (resultado = dict ou None) quando terminar.
    Uso tipico: dispara uma vez no startup do app, sem travar a UI."""

    def _alvo():
        resultado = verificar(versao_atual)
        try:
            callback(resultado)
        except Exception:
            pass

    threading.Thread(target=_alvo, daemon=True).start()
