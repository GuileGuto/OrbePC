"""
firmware_engine.py -- grava um firmware .bin no ESP32-C3 pela mesma porta
USB que o OrbePC ja usa pra ler os sensores, sem precisar do Arduino IDE no
PC do cliente. Por baixo dos panos usa o `esptool` (biblioteca oficial da
Espressif, MIT, e' o mesmo motor que o Arduino IDE chama quando voce clica
em "Carregar" -- aqui e' so chamado direto em Python, embutido no app).

FLUXO (aba Firmware da janela de configuracoes): o proprio usuario aponta
o arquivo .bin na hora, pelo botao "Selecionar" (dialogo de arquivo comum),
e confirma a gravacao no botao "Aplicar" -- nao existe firmware embutido
no .exe nem pasta com deteccao automatica. Isso deixa a distribuicao de
atualizacoes simples: manda o .bin novo pro cliente por qualquer canal
(e-mail, link, pendrive) e ele so aponta o arquivo no app.

O ARQUIVO ESPERADO E' UM "MERGED BINARY" (bootloader + tabela de particoes
+ aplicativo ja combinados num unico .bin, gravado inteiro no offset 0x0)
-- e' a opcao "Export merged binary" do Arduino IDE (Sketch > Exportar
Binario Compilado, ou no menu de export dependendo da versao do core
Arduino-ESP32). Isso evita ter que lidar com 3-4 arquivos separados e
seus offsets na hora de selecionar.

FLUXO PRA GERAR O .bin (dev), depois de editar o painel_pc_esp32c3.ino:
  1. Sobe o numero em FIRMWARE_VERSAO (perto do topo do .ino) -- e' o que
     aparece pro usuario como "versao instalada" depois de conectado
     (reportado no boot via Serial, ver DBG:versao= no .ino).
  2. Arduino IDE: Sketch > Exportar Binario Compilado (com "merged binary"
     habilitado, se a versao do core tiver essa opcao).
  3. Manda o .bin resultante pro usuario atualizar -- ele seleciona esse
     arquivo na aba Firmware do app e clica em Aplicar.
"""

import os
import sys
import threading
import traceback

BAUD_FLASH = 460800
OFFSET_MERGED = 0x0


class _SaidaCapturada:
    """Arquivo-like que fica no lugar do stdout durante o esptool.main() --
    ele imprime progresso com '\\r' (barra que fica se atualizando na mesma
    linha) e '\\n' misturados; aqui separa em "linhas logicas" e repassa
    cada uma pro callback do chamador (pra UI atualizar um label/log)."""

    def __init__(self, callback):
        self._callback = callback
        self._buffer = ""

    def write(self, texto):
        self._buffer += texto
        while "\r" in self._buffer or "\n" in self._buffer:
            for sep in ("\r", "\n"):
                if sep in self._buffer:
                    linha, self._buffer = self._buffer.split(sep, 1)
                    if linha.strip() and self._callback:
                        try:
                            self._callback(linha.strip())
                        except Exception:
                            pass
                    break

    def flush(self):
        pass


def _rodar_esptool(esptool_mod, args, callback):
    """Roda esptool.main(args) com o stdout redirecionado pro callback de
    progresso, convertendo qualquer forma de erro (SystemExit com codigo
    != 0, ou excecao normal) em RuntimeError. Retorna (ok, codigo) --
    ok=True so quando o processo terminou limpo (SystemExit 0/None ou sem
    excecao nenhuma)."""
    saida = _SaidaCapturada(callback)
    stdout_original = sys.stdout
    sys.stdout = saida
    try:
        esptool_mod.main(args)
        return True, None
    except SystemExit as e:
        return (e.code in (0, None)), e.code
    finally:
        sys.stdout = stdout_original


def _verificar_gravacao(esptool_mod, porta, caminho_bin, callback):
    """Confere, byte a byte, que o que esta na flash bate com o arquivo
    gravado (write_flash ja confere hash MD5 sozinho durante a gravacao,
    mas essa segunda leitura independente e' a garantia extra que decidimos
    ter antes de considerar uma atualizacao de firmware "concluida com
    sucesso" -- ver task de verificacao pos-gravacao). Tenta os dois nomes
    de subcomando (esptool trocou "verify_flash" por "verify-flash" entre
    versoes; aceitar os dois evita depender de uma versao exata instalada)."""
    args_comuns = ["--chip", "esp32c3", "--port", porta, "--baud", str(BAUD_FLASH)]
    for subcomando in ("verify-flash", "verify_flash"):
        if callback:
            callback(f"Conferindo gravacao ({subcomando})...")
        args = args_comuns + [subcomando, hex(OFFSET_MERGED), caminho_bin]
        ok, codigo = _rodar_esptool(esptool_mod, args, callback)
        if ok:
            return True
        # codigo 2 tipicamente = esptool nao reconheceu o subcomando (versao
        # com nomenclatura diferente) -- tenta a outra grafia antes de desistir
        if codigo != 2:
            return False
    return False


def gravar_firmware(porta, caminho_bin, callback=None):
    """Grava `caminho_bin` (arquivo .bin unico, "merged binary") no ESP32
    conectado em `porta` (ex: "COM3") e CONFERE a gravacao logo em seguida
    (leitura independente, byte a byte -- ver _verificar_gravacao()) antes
    de considerar sucesso. BLOQUEANTE -- chame numa thread separada da
    interface. `callback(str)` e' chamado a cada linha de progresso do
    esptool (opcional).

    Levanta RuntimeError com uma mensagem legivel em caso de falha (arquivo
    invalido, porta ocupada, chip nao respondeu, gravacao nao confere,
    etc.) -- o chamador decide como mostrar isso na UI. NUNCA deixa uma
    excecao do esptool (que as vezes usa SystemExit em vez de Exception
    normal) escapar sem virar RuntimeError, pra quem chamar nao precisar
    tratar SystemExit separado.

    IMPORTANTE: se a verificacao falhar, o ESP32 pode ter ficado com um
    firmware incompleto/corrompido na flash (ex: cabo instavel no meio da
    gravacao) -- a mensagem de erro deixa isso explicito e recomenda
    tentar de novo, sem desconectar o cabo, em vez de so dizer "falhou"."""
    if not caminho_bin or not os.path.isfile(caminho_bin):
        raise RuntimeError(f"Arquivo de firmware nao encontrado: {caminho_bin}")
    if not caminho_bin.lower().endswith(".bin"):
        raise RuntimeError("O arquivo selecionado nao parece ser um .bin de firmware.")

    try:
        import esptool
    except ImportError:
        raise RuntimeError(
            "Pacote 'esptool' nao instalado (pip install esptool). "
            "Sem ele o app nao consegue gravar o firmware sozinho."
        )

    args_gravar = ["--chip", "esp32c3", "--port", porta, "--baud", str(BAUD_FLASH),
                   "--before", "default_reset", "--after", "hard_reset",
                   "write_flash", "-z", hex(OFFSET_MERGED), caminho_bin]

    try:
        ok, codigo = _rodar_esptool(esptool, args_gravar, callback)
    except Exception:
        raise RuntimeError(f"Erro ao gravar firmware:\n{traceback.format_exc()}")
    if not ok:
        raise RuntimeError(f"esptool terminou com codigo {codigo} -- "
                            "confira se o cabo/porta estao ok e se nenhum "
                            "outro programa esta com a porta serial aberta.")

    try:
        confere = _verificar_gravacao(esptool, porta, caminho_bin, callback)
    except Exception:
        confere = False
        if callback:
            callback(f"Erro durante a verificacao:\n{traceback.format_exc()}")

    if not confere:
        raise RuntimeError(
            "A gravacao terminou mas a verificacao pos-gravacao falhou -- "
            "o firmware no ESP32 pode estar incompleto ou corrompido. NAO "
            "desconecte o cabo: tente gravar de novo (Selecionar/Aplicar) "
            "antes de fechar o app."
        )


def gravar_firmware_async(porta, caminho_bin, callback=None, ao_terminar=None):
    """Versao nao-bloqueante de gravar_firmware() -- roda numa thread daemon
    e chama ao_terminar(erro) no final (erro=None se deu tudo certo, ou a
    RuntimeError levantada). Uso tipico na UI: desabilita o botao, mostra
    log ao vivo via `callback`, e reabilita/mostra resultado em
    `ao_terminar`."""

    def _alvo():
        erro = None
        try:
            gravar_firmware(porta, caminho_bin, callback=callback)
        except Exception as e:
            erro = e
        if ao_terminar:
            try:
                ao_terminar(erro)
            except Exception:
                pass

    threading.Thread(target=_alvo, daemon=True).start()
