"""
atualizacao_engine.py -- confere se ha uma versao mais nova do OrbePC.exe
OU do firmware do display publicada no GitHub Releases, e devolve os dados
pro app avisar o usuario.

APP: NAO baixa nem substitui o executavel sozinho -- um app tentando se
auto-substituir enquanto esta rodando no Windows e' fragil (arquivo em
uso, precisa reiniciar, etc.); e' bem mais simples e seguro so abrir a
pagina de download no navegador e deixar o usuario baixar/trocar na mao.

FIRMWARE: like o app ja tem o fluxo de Selecionar/Aplicar (esptool) pronto,
aqui vale mais baixar o .bin sozinho (dado que e' so um arquivo, nao um
executavel em uso) e deixar ja pre-selecionado na aba Firmware -- o
usuario so confirma no botao Aplicar (a gravacao continua manual/com
confirmacao, so a etapa de "achar e baixar o arquivo certo" fica automatica).

Repositorio (mesmo pros dois): https://github.com/GuileGuto/OrbePC -- as
releases de app e de firmware convivem no mesmo repo, diferenciadas pelo
PREFIXO da tag:
  - App:      tag sem prefixo, tipo "v1.1.0" (o "v" e' opcional)
  - Firmware: tag com prefixo "firmware-", tipo "firmware-v1.2.0"
(a API "latest" do GitHub so' devolve UMA release mais recente no total,
misturando os dois tipos -- por isso o firmware usa a lista completa de
releases e filtra pelo prefixo, em vez do atalho /releases/latest.)
"""

import os
import threading

import requests

REPO = "GuileGuto/OrbePC"
URL_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
URL_LISTA = f"https://api.github.com/repos/{REPO}/releases"
PREFIXO_FIRMWARE = "firmware-"


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


def eh_mais_nova(candidata, atual):
    """True se a versao `candidata` (string, ex: '1.2.0') for mais nova que
    `atual`. Exposta pra quem importa este modulo poder comparar sem
    duplicar a logica de parsing de versao (ex: a aba Firmware compara a
    release mais recente disponivel com a versao conectada NO MOMENTO,
    que so se sabe depois que o display conecta -- por isso essa
    comparacao acontece na UI, nao aqui dentro)."""
    return _versao_tupla(candidata) > _versao_tupla(atual)


def buscar_firmware_disponivel(timeout=(5, 8)):
    """Acha a release de FIRMWARE mais recente (tag comecando com
    PREFIXO_FIRMWARE) entre as releases do repo, e retorna
    {"versao": "1.2.0", "url": "https://.../algo.bin", "nome_arquivo": "algo.bin"}
    -- ou None se nao achar nenhuma (repo sem release de firmware ainda,
    sem internet, etc). NUNCA levanta excecao.

    Diferente de verificar() (app), esta funcao NAO recebe uma versao pra
    comparar -- so devolve "qual e' a mais nova disponivel". A comparacao
    com o firmware realmente instalado no display conectado acontece na
    UI (ver eh_mais_nova()), porque so' se sabe a versao instalada depois
    que o display conecta e manda DBG:versao=."""
    try:
        r = requests.get(URL_LISTA, timeout=timeout,
                          headers={"Accept": "application/vnd.github+json"},
                          params={"per_page": 30})
        r.raise_for_status()
        releases = r.json()
        if not isinstance(releases, list):
            return None

        for rel in releases:
            tag = (rel.get("tag_name") or "")
            if not tag.lower().startswith(PREFIXO_FIRMWARE):
                continue
            # tira o prefixo "firmware-" e tambem um "v"/"V" que tenha sobrado
            # logo depois (tag tipo "firmware-v1.2.0") -- versao fica limpa
            # ("1.2.0"), do mesmo jeito que a versao do app (ver verificar()),
            # pra quem exibe na UI poder escolher formatar com ou sem "v" na
            # frente sem risco de duplicar
            versao = tag[len(PREFIXO_FIRMWARE):].lstrip("vV")
            bin_asset = next(
                (a for a in (rel.get("assets") or [])
                 if (a.get("name") or "").lower().endswith(".bin")),
                None,
            )
            if not bin_asset:
                continue  # release de firmware sem .bin anexado -- pula, nao serve
            return {
                "versao": versao,
                "url": bin_asset.get("browser_download_url"),
                "nome_arquivo": bin_asset.get("name"),
            }
        return None
    except Exception:
        return None


def buscar_firmware_disponivel_async(callback):
    """Versao nao-bloqueante de buscar_firmware_disponivel()."""

    def _alvo():
        resultado = buscar_firmware_disponivel()
        try:
            callback(resultado)
        except Exception:
            pass

    threading.Thread(target=_alvo, daemon=True).start()


def baixar_arquivo(url, destino, callback=None):
    """Baixa `url` (streaming, em pedacos) pra `destino`, chamando
    callback(str) com o progresso a cada ~1MB (opcional). BLOQUEANTE --
    chame numa thread separada da interface. Levanta RuntimeError com
    mensagem legivel em caso de falha (sem internet, URL invalida, disco
    cheio, etc.) -- o chamador decide como mostrar isso na UI."""
    try:
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        with requests.get(url, stream=True, timeout=(5, 30)) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            baixado = 0
            with open(destino, "wb") as f:
                for pedaco in r.iter_content(chunk_size=1024 * 256):
                    if not pedaco:
                        continue
                    f.write(pedaco)
                    baixado += len(pedaco)
                    if callback:
                        if total:
                            callback(f"Baixando... {baixado / 1048576:.1f}/{total / 1048576:.1f} MB "
                                      f"({100 * baixado / total:.0f}%)")
                        else:
                            callback(f"Baixando... {baixado / 1048576:.1f} MB")
    except Exception as e:
        raise RuntimeError(f"Falha ao baixar o firmware: {e}")


def baixar_arquivo_async(url, destino, callback=None, ao_terminar=None):
    """Versao nao-bloqueante de baixar_arquivo() -- roda numa thread
    daemon e chama ao_terminar(erro) no final (erro=None se deu certo)."""

    def _alvo():
        erro = None
        try:
            baixar_arquivo(url, destino, callback=callback)
        except Exception as e:
            erro = e
        if ao_terminar:
            try:
                ao_terminar(erro)
            except Exception:
                pass

    threading.Thread(target=_alvo, daemon=True).start()
