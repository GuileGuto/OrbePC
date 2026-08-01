# Pasta `firmware/`

Não é mais lida automaticamente pelo build nem pelo app — serve só como
lugar sugerido pra você guardar os `.bin` exportados, organizados por
versão, se quiser. A atualização de firmware agora é 100% manual pela
própria aba **Firmware** do app: o usuário clica em **Selecionar** e
aponta o arquivo `.bin` onde quer que ele esteja no computador (não
precisa ser esta pasta).

## Como gerar o `.bin`

1. Abra `painel_pc_esp32c3/painel_pc_esp32c3.ino` no Arduino IDE.
2. Se alterou o firmware, suba o número em `FIRMWARE_VERSAO` no topo do
   arquivo (aparece na aba Firmware do app como "versão instalada").
3. Menu **Sketch → Exportar Binário Compilado**, com a opção de gerar um
   **único arquivo combinado** ("merged binary"), se a versão do core
   Arduino-ESP32 que você usa tiver essa opção — é esse arquivo que o
   usuário vai selecionar no app (contém bootloader + tabela de partições
   + aplicativo já combinados, gravado inteiro no offset `0x0`).
4. Distribua esse `.bin` pra quem for atualizar. Duas formas:
   - **Manual:** e-mail, link, pendrive — a pessoa abre o OrbePC, vai na
     aba Firmware, clica em **Selecionar**, escolhe o arquivo, e clica em
     **Aplicar**.
   - **Automática (recomendado):** cria uma Release no GitHub
     (`github.com/GuileGuto/OrbePC/releases/new`) com a tag no formato
     **`firmware-vX.Y.Z`** (ex: `firmware-v1.2.0` — o prefixo `firmware-`
     é obrigatório, é o que diferencia de uma release do app) e anexa o
     `.bin`. O app confere isso sozinho no startup e mostra um aviso "Novo
     firmware disponível" na própria aba Firmware, com botão **Baixar e
     preparar** — baixa o `.bin` e já deixa selecionado, só falta clicar
     em Aplicar. Ver `atualizacao_engine.py` pros detalhes.
