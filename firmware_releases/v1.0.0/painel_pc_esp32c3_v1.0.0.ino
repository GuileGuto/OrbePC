/*
  Painel de PC estilo automotivo — ESP32-C3 + TFT redondo 1.28" (GC9A01)
  Versao USB (sem WiFi) — alimentado e alimentado de dados pelo mesmo cabo USB.

  Um app no PC (orbepc_app.py, evolucao do antigo monitor_usb.py) le o
  LibreHardwareMonitor e manda os dados por Serial/USB nesse formato,
  uma linha a cada ~2s:

    CPU=45.0;CPULOAD=23.5;GPU=60.0;GPULOAD=12.0;CLK=3400.0;RAM=8.2

  Alem dos dados de sensor, o app tambem pode mandar (opcional, so
  quando o usuario muda algo nas configuracoes):

    COLORCPU=RRGGBB   -- cor do anel/texto da CPU, hex sem # (ex: 1D9E75)
    COLORGPU=RRGGBB   -- cor do anel/texto da GPU
    LIMITERAM=90      -- % de uso de RAM a partir do qual o numero fica vermelho

  BIBLIOTECAS (instalar pelo Library Manager da Arduino IDE):
    - Adafruit GFX Library      (Adafruit)
    - Adafruit GC9A01A          (Adafruit)
    (trocamos da Arduino_GFX_Library pra essa dupla porque a Arduino_GFX
    tinha um bug de incompatibilidade com o core novo do ESP32-C3.
    Adafruit usa a SPI padrao do Arduino, sem mexer direto no hardware,
    entao evita esse tipo de problema.)

  Placa (Tools/Ferramentas):
    - Board: ESP32C3 Dev Module
    - Se a placa usa USB nativo (a maioria dos "ESP32-C3 SuperMini"),
      ative "USB CDC On Boot: Enabled" pra Serial funcionar pela mesma
      porta USB.

  ATUALIZACAO DE FIRMWARE PELO APP (ver firmware_engine.py no orbepc_app.py):
  a aba "Firmware" da janela de configuracoes grava esse firmware no ESP32
  sozinho, via esptool, sem precisar do Arduino IDE no PC do cliente -- o
  usuario so aponta o .bin (botao Selecionar) e confirma (botao Aplicar).
  Depois de qualquer alteracao aqui:
    1) Suba a versao em FIRMWARE_VERSAO logo abaixo (aparece na aba
       Firmware como "versao instalada" assim que o display conecta).
    2) Arduino IDE: Sketch > Exportar Binario Compilado, com a opcao de
       gerar um unico arquivo combinado ("merged binary") se a versao do
       core Arduino-ESP32 tiver essa opcao -- e' esse .bin que o usuario
       vai selecionar no app.
    3) Distribua esse .bin pro usuario atualizar (e-mail, link, pendrive)
       -- ele seleciona o arquivo na aba Firmware e clica em Aplicar.
*/

// Versao deste firmware -- reportada no boot (DBG:versao=...), aparece
// na aba Firmware do app como "versao instalada". Formato livre
// (major.minor.patch sugerido).
#define FIRMWARE_VERSAO "1.0.0"

#include <Adafruit_GFX.h>
#include <Adafruit_GC9A01A.h>
#include <SPI.h>

// ---------------- PINOS DO DISPLAY ----------------
// Confira o pinout da sua placa ESP32-C3 mini/SuperMini, esses sao valores
// tipicos, mas podem variar de placa pra placa.
#define TFT_SCK  4
#define TFT_MOSI 6
#define TFT_CS   7
#define TFT_DC   2
#define TFT_RST  10
#define TFT_BL   3   // backlight (algumas placas ligam direto no 3.3V)

// SPI de HARDWARE (barramento FSPI do C3 roteado pros nossos pinos via
// GPIO matrix), no lugar do antigo construtor de SPI por software
// (bit-bang, ~1-2 MHz). E' isso que fazia a tela "varrer" visivelmente
// de cima pra baixo a cada limpeza: tela cheia levava ~0,5-1s. A 40 MHz
// a mesma operacao leva ~30-40ms -- na pratica, um corte seco.
Adafruit_GC9A01A *gfx = new Adafruit_GC9A01A(&SPI, TFT_DC, TFT_CS, TFT_RST);

// ---------------- DADOS RECEBIDOS ----------------
struct Sensores {
  float cpuTemp = -1, gpuTemp = -1;
  float cpuLoad = -1, gpuLoad = -1;
  float cpuClockMHz = -1;
  float ramUsadaGB = -1;
  float ramPct = -1;
  float vramUsadaGB = -1;
} dados;

// filtro de rejeicao de ruido nas temperaturas de CPU/GPU. A media movel
// simples nao funcionou bem: um unico valor esdruxulo (ex: "6" com o PC a
// 70C) entrava direto na conta e derrubava a media junto com os valores
// bons. A ideia agora e diferente -- um salto grande demais entre uma
// leitura e a proxima (mais do que qualquer CPU/GPU real mudaria de
// temperatura entre duas leituras, ~0.5s) e tratado como ruido e
// simplesmente DESCARTADO (mantem o ultimo valor bom na tela), a nao ser
// que o MESMO salto se repita (aí confirma que era uma mudanca real, tipo
// o PC realmente esfriando rapido, e nao um pico isolado do sensor).
const float SALTO_MAX_TEMP = 15.0; // graus, acima disso e suspeito

struct FiltroTemp {
  float valor = -1;     // ultimo valor confirmado (mostrado na tela)
  float candidato = -1; // valor suspeito aguardando confirmacao
  int repeticoes = 0;
};

FiltroTemp filtroCpuTemp, filtroGpuTemp;

float filtrarTemp(FiltroTemp &f, float novo) {
  if (f.valor < 0) { // primeira leitura -- aceita direto, nao ha com o que comparar
    f.valor = novo;
    return f.valor;
  }

  if (fabs(novo - f.valor) <= SALTO_MAX_TEMP) {
    // variacao normal, aceita e esquece qualquer candidato pendente
    f.valor = novo;
    f.candidato = -1;
    f.repeticoes = 0;
    return f.valor;
  }

  // salto grande -- so aceita se o MESMO valor aparecer de novo em seguida
  // (confirma que nao foi um pico passageiro do sensor)
  if (f.candidato >= 0 && fabs(novo - f.candidato) <= 2.0) {
    f.repeticoes++;
  } else {
    f.candidato = novo;
    f.repeticoes = 1;
  }

  if (f.repeticoes >= 2) {
    f.valor = novo;
    f.candidato = -1;
    f.repeticoes = 0;
  }
  // enquanto nao confirmado, mantem o ultimo valor bom
  return f.valor;
}

// converte uma string hex tipo "1D9E75" (sem #) num uint16_t no formato
// RGB565 que a lib grafica usa. Se vier algo invalido/curto demais,
// devolve branco em vez de travar -- assim um valor mal formado do app
// so deixa a cor "errada" na tela, nunca trava o desenho.
// valida "exatamente 6 digitos hex" -- linha serial emendada/mutilada
// (bytes perdidos no USB) produzia coisas como "00PAGE=0", que o strtol
// lia como "00" = PRETO, disparando limpeza total da tela a cada
// ocorrencia (o famoso bug da "tela sendo recriada"). Cor invalida
// agora e simplesmente ignorada: mantem a cor atual, tela nem pisca.
bool hexValido6(const String &hex) {
  if (hex.length() != 6) return false;
  for (int i = 0; i < 6; i++) {
    char c = hex.charAt(i);
    bool ok = (c >= '0' && c <= '9') || (c >= 'A' && c <= 'F') || (c >= 'a' && c <= 'f');
    if (!ok) return false;
  }
  return true;
}

uint16_t corDeHex(String hex) {
  hex.trim();
  if (hex.length() < 6) return 0xFFFF;
  long valor = strtol(hex.c_str(), NULL, 16);
  uint8_t r = (valor >> 16) & 0xFF;
  uint8_t g = (valor >> 8) & 0xFF;
  uint8_t b = valor & 0xFF;
  return gfx->color565(r, g, b);
}

String bufferSerial = "";
unsigned long ultimoDadoRecebido = 0;
const unsigned long TIMEOUT_SEM_DADOS = 8000; // ms
const int CX = 120, CY = 120; // centro do display 240x240
bool mostrandoMensagem = false; // true enquanto uma mensagem de status ocupa a tela
uint16_t corCpuFixa, corGpuFixa, corLaranjaFixa; // cores definidas no setup(), ajustaveis via serial (COLORCPU/COLORGPU)
float limiteRamPct = 90.0; // % a partir do qual o numero de RAM fica vermelho, ajustavel via LIMITERAM
bool precisaRedesenhoTotal = false; // true quando uma cor muda -- forca redesenho limpo dos aneis na nova cor

// ---------------- TELAS PERSONALIZADAS ----------------
// O app manda PAGE=n a cada pacote: 0 = tela classica (tudo como sempre
// foi), >=1 = tela personalizada, generica -- 2 aneis (R1/R2, em %) + 4
// linhas de texto (L1..L4) JA formatadas pelo app. O firmware nao sabe
// o que esta mostrando, so desenha.
int paginaAtual = 0;
float anelCustom1 = -1, anelCustom2 = -1;  // % dos aneis (-1 = sem dado, anel parado)
String linhasCustom[4];       // textos recebidos (L1..L4)
String linhasDesenhadas[4];   // o que esta na tela agora (decide quando limpar a faixa)

// declaracao antecipada -- o Arduino normalmente gera isso sozinho, mas o
// parametro com valor padrao (denso = false) impede a geracao automatica,
// entao precisa declarar na mao antes do primeiro uso (a funcao em si fica
// mais pra baixo no arquivo)
void desenharArco(int raio, int espessura, float anguloIni, float anguloFim, uint16_t cor, bool denso = false);
void desenharMarcaEscala(int indice);
void restaurarMarcasNaFaixa(int inicio, int fim);
void aoTrocarDePagina();
void desenharPainelCustom();

// ---------------- SPLASH DE INICIALIZACAO ----------------
// arco laranja girando continuamente ao redor do logo "OrbePC", enquanto
// espera o primeiro pacote de dados chegar pela serial
bool mostrandoSplash = false;
int grauSpinner = 0;
const int SPINNER_RAIO = 104;
const int SPINNER_ESPESSURA = 6;
const int SPINNER_ARCO = 50;  // comprimento visivel do arco, em graus
const int SPINNER_PASSO = 5;  // graus por passo -- controla a velocidade do giro

// transicao de saida do splash: o spinner "encolhe" e vira os dois aneis do
// painel principal, em vez de a tela apagar e redesenhar tudo de uma vez
bool emTransicao = false;
int alvoAlinhamentoSpinner = 0; // angulo (sempre crescente) onde o spinner encontra o inicio do gauge

const float GAUGE_INICIO = 135;
const float GAUGE_FIM    = 405; // 270 graus de varredura

// grau ATUAL desenhado na tela e grau ALVO (pra onde o anel esta indo).
// A animacao move "grauAtual" um pouco por vez em direcao a "grauAlvo",
// em vez de saltar direto -- fica com um movimento mais suave/natural.
int grauCpuAtual = (int)round(GAUGE_INICIO);
int grauCpuAlvo  = (int)round(GAUGE_INICIO);
int grauGpuAtual = (int)round(GAUGE_INICIO);
int grauGpuAlvo  = (int)round(GAUGE_INICIO);

// velocidade ATUAL de cada anel (graus por passo de animacao) -- guardada
// entre os quadros pra dar acelerada/freada, tipo um carro: comeca devagar,
// ganha velocidade, e freia suave perto do alvo em vez de parar seco.
float velCpuAtual = 0;
float velGpuAtual = 0;

bool aneisPrecisamRedesenho = true; // forca reset na proxima vez
bool escalaDesenhada = false; // true depois que os tracinhos/numeros da escala ja foram desenhados

unsigned long ultimaAnimacao = 0;
const unsigned long INTERVALO_ANIMACAO = 20; // ms entre passos da animacao
const float ANEL_ACEL    = 0.35; // aceleracao dos aneis (graus/passo^2) -- "pisar fundo"
const float ANEL_VEL_MAX = 7.0;  // velocidade maxima dos aneis (graus por passo)
                                  // suba ANEL_ACEL pra acelerar/frear mais rapido,
                                  // suba ANEL_VEL_MAX pra ter uma velocidade de cruzeiro maior.

// Diagnostico: se o ULTIMO reset foi anormal (crash, watchdog, queda de
// energia), avisa em vermelho por 2s antes do splash. Reset normal
// (power-on, gravacao de firmware, enumeracao USB) nao mostra nada --
// zero impacto no uso do dia a dia. Serve pra diferenciar "o ESP32 esta
// reiniciando sozinho" de "algum caminho de desenho esta limpando a tela".
void mostrarResetAnormal() {
  esp_reset_reason_t r = esp_reset_reason();
  const char* motivo = NULL;
  if (r == ESP_RST_PANIC) motivo = "PANIC (crash)";
  else if (r == ESP_RST_INT_WDT || r == ESP_RST_TASK_WDT || r == ESP_RST_WDT) motivo = "WATCHDOG";
  else if (r == ESP_RST_BROWNOUT) motivo = "BROWNOUT";
  if (motivo == NULL) return;

  gfx->fillScreen(0x0000);
  gfx->setTextSize(2);
  gfx->setTextColor(gfx->color565(255, 40, 40));
  gfx->setCursor(24, 100);
  gfx->print("Reset: ");
  gfx->println(motivo);
  delay(2000);
}

void setup() {
  Serial.begin(115200);
  // TX nao-bloqueante: sem ninguem lendo do outro lado (app fechado),
  // um print jamais pode travar o loop -- descarta e segue
  Serial.setTxTimeoutMs(0);

  // roteia o barramento SPI de hardware pros pinos do display ANTES do
  // begin(). 40 MHz funciona bem no GC9A01 (so escrita); se aparecer
  // ruido/artefato na tela, baixe pra 26000000 ou 20000000.
  SPI.begin(TFT_SCK, -1, TFT_MOSI, TFT_CS);
  gfx->begin(40000000);
  gfx->fillScreen(0x0000);
  pinMode(TFT_BL, OUTPUT);
  digitalWrite(TFT_BL, HIGH);

  corCpuFixa = gfx->color565(0, 220, 0);     // verde
  corGpuFixa = gfx->color565(0, 144, 255);   // azul
  corLaranjaFixa = gfx->color565(255, 122, 26); // laranja (marca OrbePC)

  // relatorio de boot: o app loga tudo que comeca com "DBG:" -- assim o
  // motivo de qualquer reinicio/limpeza aparece no log.txt do PC
  Serial.printf("DBG:boot reset=%d\n", (int)esp_reset_reason());
  Serial.printf("DBG:versao=%s\n", FIRMWARE_VERSAO);

  mostrarResetAnormal();
  mostrarSplash();
}

void loop() {
  lerSerial();

  if (millis() - ultimaAnimacao >= INTERVALO_ANIMACAO) {
    ultimaAnimacao = millis();
    if (mostrandoSplash) {
      animarSplash();
    } else if (emTransicao) {
      animarTransicaoSaidaSplash();
    } else {
      animarAneis();
    }
  }

  // App fechou / parou de mandar dados: volta pro MESMO visual do boot
  // (logo "OrbePC" + arco laranja girando), em vez da antiga mensagem de
  // texto "Sem dados do PC. Rode o monitor_usb.py". Quando os dados
  // voltarem, processarLinha() ve mostrandoSplash == true e sai pelo
  // mesmo caminho animado de sempre (spinner desliza e vira os aneis).
  if (millis() - ultimoDadoRecebido > TIMEOUT_SEM_DADOS) {
    if (!mostrandoSplash) {
      emTransicao = false; // cancela uma transicao no meio, por seguranca
      mostrarSplash();
    }
  }

  delay(5);
}

// Le a serial byte a byte e processa NO MAXIMO uma linha completa por
// chamada -- se ficasse processando todas as linhas disponiveis de uma vez
// (enquanto Serial.available() fosse verdadeiro), o loop() podia nunca
// voltar pra rodar a animacao dos aneis a tempo.
void lerSerial() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n') {
      processarLinha(bufferSerial);
      bufferSerial = "";
      return; // devolve o controle pro loop() logo depois de 1 linha
    } else if (c != '\r') {
      bufferSerial += c;
      // um '\n' perdido no USB emendaria linhas pra sempre -- linha
      // normal tem ~140 chars, entao acima de 300 e' lixo acumulado:
      // descarta e recomeca do zero no proximo pacote integro
      if (bufferSerial.length() > 300) {
        Serial.println("DBG:linha passou de 300 chars -- descartada");
        bufferSerial = "";
      }
    }
  }
}

// Formato esperado: CHAVE=valor;CHAVE=valor;...
void processarLinha(String linha) {
  if (linha.length() == 0) return;

  // a troca de pagina e' decidida so no FIM do pacote: PAGE != 0 sem
  // nenhum conteudo custom junto (R1/R2/L1..L4) e' tratado como pagina
  // classica -- blindagem contra um app antigo/config errada mandando
  // o display pra uma pagina vazia (ficava alternando tela em branco)
  int paginaPacote = -1;            // -1 = pacote nao trouxe PAGE
  bool conteudoCustomNoPacote = false;
  // aneis custom valem SO para a pagina DESTE pacote -- o app omite
  // R1/R2 em telas sem anel, e sem esse cuidado o valor da tela
  // anterior ficava "grudado" (anel fantasma congelado na tela nova)
  float r1Pacote = -1, r2Pacote = -1;

  int inicio = 0;
  while (inicio < (int)linha.length()) {
    int fimPar = linha.indexOf(';', inicio);
    if (fimPar < 0) fimPar = linha.length();
    String par = linha.substring(inicio, fimPar);

    int igual = par.indexOf('=');
    if (igual > 0) {
      String chave = par.substring(0, igual);
      String valorStr = par.substring(igual + 1);

      // COLORCPU/COLORGPU vem em hex ("1D9E75"), nao da pra passar por
      // toFloat() -- trata essas duas chaves separado, antes de converter
      // o resto pra numero.
      if (chave == "COLORCPU") {
        valorStr.trim();
        if (!hexValido6(valorStr)) {
          Serial.printf("DBG:corCPU invalida ignorada ('%s')\n", valorStr.c_str());
        } else {
          uint16_t nova = corDeHex(valorStr);
          if (nova != corCpuFixa) {
            Serial.printf("DBG:corCPU mudou %04X->%04X (recebido '%s')\n", corCpuFixa, nova, valorStr.c_str());
            corCpuFixa = nova;
            precisaRedesenhoTotal = true;
          }
        }
      } else if (chave == "COLORGPU") {
        valorStr.trim();
        if (!hexValido6(valorStr)) {
          Serial.printf("DBG:corGPU invalida ignorada ('%s')\n", valorStr.c_str());
        } else {
          uint16_t nova = corDeHex(valorStr);
          if (nova != corGpuFixa) {
            Serial.printf("DBG:corGPU mudou %04X->%04X (recebido '%s')\n", corGpuFixa, nova, valorStr.c_str());
            corGpuFixa = nova;
            precisaRedesenhoTotal = true;
          }
        }
      } else if (chave.length() == 2 && chave.charAt(0) == 'L'
                 && chave.charAt(1) >= '1' && chave.charAt(1) <= '4') {
        // linhas de texto das telas personalizadas -- string, nao numero.
        // '~' e o marcador que o app usa pro simbolo de grau (char 248
        // na fonte padrao do Adafruit_GFX)
        int idx = chave.charAt(1) - '1';
        valorStr.replace('~', (char)248);
        linhasCustom[idx] = valorStr;
        if (valorStr.length() > 0) conteudoCustomNoPacote = true;
      } else {
        float valor = valorStr.toFloat();

        // ignora leitura de temperatura zerada (ou negativa) -- normalmente
        // e ruido/corte no dado (ex: linha serial corrompida virando "0" no
        // toFloat(), ou instante de atualizacao do sensor) e nao uma
        // temperatura real. O filtro no app ja tenta barrar isso na
        // origem, mas aqui e uma segunda trava direto no ESP32: se vier
        // zerado, simplesmente mantem o ultimo valor valido na tela.
        if (chave == "CPU") { if (valor > 0) dados.cpuTemp = filtrarTemp(filtroCpuTemp, valor); }
        else if (chave == "PAGE") paginaPacote = (int)valor; // aplicada no fim do pacote
        else if (chave == "R1") { r1Pacote = valor; conteudoCustomNoPacote = true; }
        else if (chave == "R2") { r2Pacote = valor; conteudoCustomNoPacote = true; }
        else if (chave == "CPULOAD") dados.cpuLoad = valor;
        else if (chave == "GPU") { if (valor > 0) dados.gpuTemp = filtrarTemp(filtroGpuTemp, valor); }
        else if (chave == "GPULOAD") dados.gpuLoad = valor;
        else if (chave == "CLK") dados.cpuClockMHz = valor;
        else if (chave == "RAM") dados.ramUsadaGB = valor;
        else if (chave == "RAMPCT") dados.ramPct = valor;
        else if (chave == "VRAM") dados.vramUsadaGB = valor;
        else if (chave == "LIMITERAM") limiteRamPct = valor;
      }
    }

    inicio = fimPar + 1;
  }

  // aplica a troca de pagina decidida durante o parse (ver comentario
  // no topo da funcao) -- pagina custom sem conteudo vira classica
  if (paginaPacote >= 0) {
    int p = (paginaPacote != 0 && !conteudoCustomNoPacote) ? 0 : paginaPacote;
    if (p != paginaAtual) {
      paginaAtual = p;
      aoTrocarDePagina(); // zera anelCustom1/2 -- pagina nova comeca sem anel
    }
  }

  // liga os aneis SO com o que ESTE pacote trouxe (depois da troca de
  // pagina, de proposito: os R1/R2 do pacote pertencem a pagina nova)
  if (r1Pacote >= 0) anelCustom1 = r1Pacote;
  if (r2Pacote >= 0) anelCustom2 = r2Pacote;

  // uma cor mudou nesse pacote -- limpa e redesenha do zero na cor nova
  // em vez de deixar o anel velho "manchado" com a cor antiga ate a
  // proxima variacao de uso. So faz isso fora do splash/transicao pra
  // nao interferir na animacao de abertura.
  if (precisaRedesenhoTotal && !mostrandoSplash && !emTransicao) {
    precisaRedesenhoTotal = false;
    gfx->fillScreen(0x0000);
    escalaDesenhada = false;
    grauCpuAtual = (int)round(GAUGE_INICIO);
    grauGpuAtual = (int)round(GAUGE_INICIO);
    velCpuAtual = 0;
    velGpuAtual = 0;
    for (int i = 0; i < 4; i++) linhasDesenhadas[i] = ""; // tela limpa -- linhas custom precisam redesenhar
  }

  ultimoDadoRecebido = millis();

  if (mostrandoSplash) {
    iniciarTransicaoSaidaSplash(); // primeiro dado chegou -- sai do splash animado
  } else if (!emTransicao) {
    desenharPainel(); // durante a transicao, so atualiza "dados" e espera ela terminar
  }
}

// ---------------- DESENHO ----------------
void mensagemCentral(String msg) {
  mostrandoMensagem = true;
  mostrandoSplash = false; // qualquer mensagem de texto encerra o spinner de boot
  emTransicao = false;     // e cancela uma transicao em andamento, por seguranca
  escalaDesenhada = false; // a tela vai ser limpa, a escala precisa ser redesenhada depois
  gfx->fillScreen(0x0000);
  gfx->setTextColor(0xFFFF);
  gfx->setTextSize(2);
  gfx->setCursor(15, 90);
  gfx->println(msg);
}

// tela de abertura: logo "OrbePC" parado no centro + arco laranja girando
// ao redor -- fica assim ate o primeiro pacote de dados chegar pela serial
void mostrarSplash() {
  Serial.println("DBG:splash (ficou sem dados ou boot)");
  mostrandoMensagem = true; // avisa desenharPainel() pra limpar a tela quando os dados chegarem
  mostrandoSplash = true;
  escalaDesenhada = false; // a tela vai ser limpa, a escala precisa ser redesenhada depois
  for (int i = 0; i < 4; i++) linhasDesenhadas[i] = ""; // tela limpa -- linhas custom redesenham depois
  grauSpinner = 0;
  gfx->fillScreen(0x0000);
  textoCentralizado("OrbePC", CY - 12, 3, corLaranjaFixa);

  // desenha o arco inicial completo uma unica vez -- dai em diante
  // animarSplash() so mexe na pontinha da frente/de tras a cada passo
  gfx->startWrite();
  desenharArco(SPINNER_RAIO, SPINNER_ESPESSURA, grauSpinner, grauSpinner + SPINNER_ARCO, corLaranjaFixa);
  gfx->endWrite();
}

// chamada com frequencia pelo loop() (mesmo intervalo da animacao dos aneis)
// -- em vez de apagar o arco inteiro e redesenhar ele inteiro na posicao
// nova (que pisca e fica "pulando"), desenha so a ponta que entra na frente
// e apaga so a ponta que sai atras -- mesma tecnica usada nos aneis do
// painel principal, resultado fica bem mais fluido
void animarSplash() {
  if (!mostrandoSplash) return;

  gfx->startWrite();
  // apaga a pontinha de tras que esta saindo do arco
  desenharArco(SPINNER_RAIO, SPINNER_ESPESSURA, grauSpinner, grauSpinner + SPINNER_PASSO - 1, 0x0000);
  // desenha a pontinha da frente que esta entrando no arco
  desenharArco(SPINNER_RAIO, SPINNER_ESPESSURA, grauSpinner + SPINNER_ARCO, grauSpinner + SPINNER_ARCO + SPINNER_PASSO - 1, corLaranjaFixa);
  grauSpinner += SPINNER_PASSO;
  // mantem o angulo sempre entre 0 e 360 -- se o app demorar pra conectar,
  // o spinner fica girando por bastante tempo, e sem esse ajuste o angulo
  // cresceria indefinidamente.
  if (grauSpinner >= 360) grauSpinner -= 360;
  gfx->endWrite();
}

// ---------------- TRANSICAO: SPLASH -> PAINEL ----------------
// Em vez de "gfx->fillScreen(preto)" (que apaga e redesenha tudo de cima pra
// baixo, feio e sempre na mesma direcao), o spinner do splash desliza ate
// encontrar o angulo onde os aneis do gauge comecam, "planta" um tico dos
// dois aneis exatamente ali, e a partir dai a MESMA animarAneis() que ja
// atualiza o painel no dia a dia assume o resto do crescimento -- ou seja,
// nao existe nenhum codigo de animacao novo pra essa parte final, so
// reaproveita o que ja esta testado e fluido.

// calcula o proximo angulo (sempre >= grauSpinner, que so cresce) em que o
// spinner coincide com o inicio do gauge -- o modulo 360 e necessario porque
// grauSpinner gira livremente e pode estar em qualquer volta
int calcularAlvoAlinhamentoSpinner() {
  int base = (int)round(GAUGE_INICIO);
  int resto = grauSpinner % 360;
  if (resto < 0) resto += 360;
  int diferenca = base - resto;
  if (diferenca <= 0) diferenca += 360;
  return grauSpinner + diferenca;
}

void iniciarTransicaoSaidaSplash() {
  mostrandoSplash = false;
  emTransicao = true;
  alvoAlinhamentoSpinner = calcularAlvoAlinhamentoSpinner();
}

// chamada com frequencia pelo loop() enquanto emTransicao == true -- desliza
// o spinner ate alinhar com o inicio do gauge, dai planta os aneis e encerra
// a transicao. Usa o MESMO passo fixo (SPINNER_PASSO) do giro normal do
// spinner -- de proposito nao acelera pra distancias grandes: um passo maior
// que SPINNER_ARCO quebra a conta de "apaga so a ponta de tras / desenha so
// a ponta da frente" (sobra pedaco pintado que nunca mais e apagado) e ainda
// fica com salto grande demais pra parecer fluido. Pior caso (quase 360 graus
// de distancia) demora ~1.4s, mas so acontece uma vez, no boot -- preferi
// isso a arriscar sujeira na tela.
void animarTransicaoSaidaSplash() {
  int distancia = alvoAlinhamentoSpinner - grauSpinner;
  if (distancia <= 0) {
    plantarAneisEEncerrarTransicao();
    return;
  }

  int passo = (distancia < SPINNER_PASSO) ? distancia : SPINNER_PASSO;

  gfx->startWrite();
  desenharArco(SPINNER_RAIO, SPINNER_ESPESSURA, grauSpinner, grauSpinner + passo - 1, 0x0000);
  desenharArco(SPINNER_RAIO, SPINNER_ESPESSURA, grauSpinner + SPINNER_ARCO, grauSpinner + SPINNER_ARCO + passo - 1, corLaranjaFixa);
  grauSpinner += passo;
  gfx->endWrite();
}

// o spinner acabou de alinhar com o inicio do gauge -- apaga ele e o logo, e
// zera os aneis exatamente nesse ponto (mesmo angulo onde o spinner sumiu),
// entregando o crescimento pra animarAneis() (a mesma usada no dia a dia).
// Importante: zera pra GAUGE_INICIO puro, sem nenhum "toco" inicial -- um
// toco de tamanho fixo fazia o anel comecar sempre num valor arbitrario
// (~18% de carga) e, se a carga real fosse menor que isso, o anel tinha que
// ENCOLHER ate o valor certo em vez de crescer, o que ficava estranho.
void plantarAneisEEncerrarTransicao() {
  gfx->startWrite();
  desenharArco(SPINNER_RAIO, SPINNER_ESPESSURA, grauSpinner, grauSpinner + SPINNER_ARCO, 0x0000);
  gfx->endWrite();

  gfx->fillRect(10, CY - 24, 220, 34, 0x0000); // apaga o "OrbePC" grande do splash

  int inicio = (int)round(GAUGE_INICIO);
  grauCpuAtual = grauCpuAlvo = inicio;
  grauGpuAtual = grauGpuAlvo = inicio;
  velCpuAtual = 0;
  velGpuAtual = 0;

  emTransicao = false;
  mostrandoMensagem = false;
  aneisPrecisamRedesenho = false; // os aneis ja foram plantados aqui -- nao deixa desenharPainel() resetar
  desenharPainel(); // desenha o resto (textos) com os ultimos dados recebidos
}

// centraliza um texto horizontalmente em torno de CX, na altura Y
void textoCentralizado(String texto, int y, int tamanho, uint16_t cor) {
  gfx->setTextSize(tamanho);
  int16_t x1, y1;
  uint16_t w, h;
  gfx->getTextBounds(texto, 0, 0, &x1, &y1, &w, &h);
  gfx->setTextColor(cor, 0x0000);
  gfx->setCursor(CX - w / 2, y);
  gfx->print(texto);
}

// desenha um pequeno icone de termometro (haste + bulbo) -- usado pra deixar
// claro que os valores de CPU/GPU ali do lado sao temperatura
const int ICONE_TERMOMETRO_LARGURA = 11; // espaco reservado (icone + respiro ate o texto)
void desenharIconeTermometro(int x, int yTopo, int alturaLinha, uint16_t cor) {
  int larguraHaste = 3;
  int xHaste = x + 2;
  int alturaHaste = alturaLinha - 5;
  gfx->fillRoundRect(xHaste, yTopo + 1, larguraHaste, alturaHaste, 1, cor);
  gfx->fillCircle(xHaste + larguraHaste / 2, yTopo + alturaLinha - 3, 4, cor);
}

// como textoCentralizado(), mas com um iconzinho de termometro colado antes
// do texto -- o bloco inteiro (icone + texto) fica centralizado em CX
void linhaTemperatura(String texto, int y, int tamanho, uint16_t cor) {
  gfx->setTextSize(tamanho);
  int16_t x1, y1;
  uint16_t w, h;
  gfx->getTextBounds(texto, 0, 0, &x1, &y1, &w, &h);
  int larguraTotal = ICONE_TERMOMETRO_LARGURA + w;
  int xInicio = CX - larguraTotal / 2;
  desenharIconeTermometro(xInicio, y, 8 * tamanho, cor);
  gfx->setTextColor(cor, 0x0000);
  gfx->setCursor(xInicio + ICONE_TERMOMETRO_LARGURA, y);
  gfx->print(texto);
}

// completa a string com espaços a esquerda ate um tamanho fixo -- assim a
// largura do texto nunca muda de um update pro outro, e a cor de fundo do
// texto (setTextColor com 2 parametros) apaga o valor antigo sozinha, sem
// precisar limpar um retangulo toda vez (que era lento)
String largFixa(String s, int tamanho) {
  while ((int)s.length() < tamanho) s = " " + s;
  return s;
}

// Desenha um arco (anel) de startAngle a endAngle (graus, 0 = direita, sentido horario)
// ATENCAO: usa writePixel(), que EXIGE ser chamado dentro de um
// startWrite()/endWrite() ja aberto pelo chamador -- todos os call sites
// fazem isso. NAO trocar por drawPixel(): ele abre a propria transacao
// SPI, e transacao aninhada trava o SPI de hardware do ESP32 pra sempre
// (mutex nao-recursivo). No SPI por software antigo isso passava batido
// porque transacao era no-op -- foi a causa do "travado no splash".
// "denso" controla o passo da amostragem angular: false (padrao) = 1 grau
// inteiro, igual sempre foi -- usado pelo spinner, que depende de um passo
// previsivel pro truque de "apaga so a cauda / desenha so a cabeca" (passo
// de 0.5 grau quebrava essa conta e deixava o arco esfiapado). true = 0.5
// grau, mais denso, usado só pelos aneis do painel (que so crescem/encolhem
// a partir de uma ponta fixa, sem esse truque de janela deslizante) pra
// tapar os buraquinhos que sobravam com raio grande e espessura fina.
void desenharArco(int raio, int espessura, float anguloIni, float anguloFim, uint16_t cor, bool denso) {
  // arredonda pra grau inteiro antes de tudo -- assim qualquer chamada que
  // passe pelo mesmo grau (mesmo vindo de outra atualizacao incremental)
  // calcula exatamente os mesmos pixels, sem sobra ao "apagar" depois
  int ini = (int)round(anguloIni);
  int fim = (int)round(anguloFim);
  float passo = denso ? 0.5 : 1.0;
  for (float a = ini; a <= fim; a += passo) {
    float rad = a * DEG_TO_RAD;
    float cosA = cos(rad), sinA = sin(rad);
    for (int r = raio - espessura; r <= raio; r++) {
      int x = CX + (int)round(r * cosA);
      int y = CY + (int)round(r * sinA);
      gfx->writePixel(x, y, cor);
    }
  }
}

// faixas apagadas neste quadro cujas marcas de escala (0/50/100) precisam
// ser restauradas -- anotadas durante animarUmAnel() e processadas DEPOIS
// do endWrite() em animarAneis(), porque desenharMarcaEscala() usa
// drawLine/print (abrem transacao SPI propria; aninhada = deadlock)
int restauraIni[2], restauraFim[2];
int restauraPendentes = 0;

// move um anel 1 passo em direcao ao alvo com aceleracao tipo carro: comeca
// devagar (parado -> acelerando), ganha velocidade ate ANEL_VEL_MAX e, perto
// do alvo, freia (desacelera) pra chegar suave em vez de bater seco. Recebe
// a velocidade atual por referencia pra lembrar dela entre os quadros.
// So desenha o pedacinho que mudou nesse passo.
void animarUmAnel(int raio, int espessura, int &grauAtual, int grauAlvo, uint16_t cor, float &velAtual) {
  if (grauAtual == grauAlvo) {
    velAtual = 0; // parado -- proxima vez que sair do lugar, comeca do zero de novo
    return;
  }

  int diferenca = grauAlvo - grauAtual;
  int dir = (diferenca > 0) ? 1 : -1;
  float distancia = (float)abs(diferenca);

  // distancia que essa velocidade precisaria pra freiar ate zero (fisica de
  // MRUV: d = v^2 / (2*a)) -- se ja estamos dentro dessa distancia do alvo,
  // comeca a frear; senao, continua acelerando
  float distanciaFreio = (velAtual * velAtual) / (2.0 * ANEL_ACEL);
  if (distanciaFreio >= distancia) {
    velAtual -= ANEL_ACEL;
  } else {
    velAtual += ANEL_ACEL;
  }
  velAtual = constrain(velAtual, 0.0, ANEL_VEL_MAX);

  int passo = (int)round(velAtual);
  if (passo < 1) passo = 1;       // nunca trava parado enquanto houver distancia a percorrer
  if (passo > distancia) passo = (int)distancia; // nao ultrapassa o alvo
  passo *= dir;

  int novoGrau = grauAtual + passo;
  if ((passo > 0 && novoGrau > grauAlvo) || (passo < 0 && novoGrau < grauAlvo)) {
    novoGrau = grauAlvo; // nao ultrapassa o alvo
  }

  if (novoGrau > grauAtual) {
    desenharArco(raio, espessura, grauAtual, novoGrau, cor, true);
  } else {
    desenharArco(raio, espessura, novoGrau, grauAtual, 0x0000, true);
    // o trecho que acabou de ser apagado (virar preto) pode ter engolido
    // um tracinho/numero da escala (0, 50 ou 100) que estava por baixo do
    // anel. SO ANOTA a faixa aqui -- a restauracao em si roda depois do
    // endWrite() (ver animarAneis), porque desenha com drawLine/print,
    // que nao podem rodar dentro desta transacao SPI.
    if (restauraPendentes < 2) {
      restauraIni[restauraPendentes] = novoGrau;
      restauraFim[restauraPendentes] = grauAtual;
      restauraPendentes++;
    }
  }
  grauAtual = novoGrau;
}

// chamada com frequencia pelo loop() -- anima os dois aneis em direcao
// ao ultimo valor recebido
void animarAneis() {
  if (mostrandoMensagem) return;
  if (grauCpuAtual == grauCpuAlvo && grauGpuAtual == grauGpuAlvo) return;

  gfx->startWrite();
  animarUmAnel(114, 8, grauCpuAtual, grauCpuAlvo, corCpuFixa, velCpuAtual);
  animarUmAnel(94, 7, grauGpuAtual, grauGpuAlvo, corGpuFixa, velGpuAtual);
  gfx->endWrite();

  // restaura marcas de escala engolidas por anel encolhendo -- FORA da
  // transacao acima (desenharMarcaEscala abre transacao propria)
  for (int i = 0; i < restauraPendentes; i++) {
    restaurarMarcasNaFaixa(restauraIni[i], restauraFim[i]);
  }
  restauraPendentes = 0;
}

// tracinhos + numeros de referencia (0/50/100) por fora do anel de CPU --
// estatico, desenhado uma unica vez (ver "escalaDesenhada"). Vale tanto pro
// anel de CPU quanto o de GPU, ja que os dois usam o mesmo mapeamento de
// angulo (GAUGE_INICIO a GAUGE_FIM = 0% a 100%).
const float ESCALA_ANGULOS[3] = { GAUGE_INICIO, 270, GAUGE_FIM };

// desenha SO a marca de indice 0 ("0"), 1 ("50") ou 2 ("100") -- tracinho
// + numero. Existe separado de desenharEscala() pra poder redesenhar uma
// unica marca quando um anel passa por cima e "come" ela (ver
// restaurarMarcasNaFaixa), sem precisar redesenhar a escala inteira.
void desenharMarcaEscala(int indice) {
  uint16_t corEscala = gfx->color565(110, 110, 110);
  float rad = ESCALA_ANGULOS[indice] * DEG_TO_RAD;
  float cosA = cos(rad), sinA = sin(rad);

  // SEM startWrite() aqui: drawLine() (e o print() logo abaixo) abrem a
  // PROPRIA transacao SPI -- embrulhar numa transacao externa aninharia
  // transacoes e travaria o SPI de hardware. Por isso essa funcao so
  // pode ser chamada FORA de qualquer startWrite()/endWrite().
  int x1 = CX + (int)round(114 * cosA);
  int y1 = CY + (int)round(114 * sinA);
  int x2 = CX + (int)round(117 * cosA);
  int y2 = CY + (int)round(117 * sinA);
  gfx->drawLine(x1, y1, x2, y2, corEscala);

  gfx->setTextSize(1);
  gfx->setTextColor(corEscala, 0x0000);
  int16_t bx, by;
  uint16_t bw, bh;

  if (indice == 0) {
    // "0" (canto inferior esquerdo) -- fica mais perto do centro do que a
    // borda redonda da tela, entao alinhar pela esquerda (crescendo em
    // direcao ao centro) sobra espaco de sobra
    gfx->setCursor(34, 190);
    gfx->print("0");
  } else if (indice == 1) {
    // "50" (topo) -- centralizado, tem bastante espaco livre em volta
    gfx->getTextBounds("50", 0, 0, &bx, &by, &bw, &bh);
    gfx->setCursor(CX - bw / 2, 12);
    gfx->print("50");
  } else {
    // "100" (canto inferior direito) -- alinhado pela DIREITA, terminando
    // antes da borda redonda -- se alinhasse pela esquerda (como as
    // outras), o texto cresceria pra fora e estourava a curva da tela
    // nesse canto
    gfx->getTextBounds("100", 0, 0, &bx, &by, &bw, &bh);
    gfx->setCursor(206 - (int)bw, 190);
    gfx->print("100");
  }
}

void desenharEscala() {
  for (int i = 0; i < 3; i++) desenharMarcaEscala(i);
}

// verifica se alguma das 3 marcas (0/50/100) cai dentro de uma faixa de
// graus que acabou de ser apagada (virar preto) por um anel encolhendo,
// e redesenha so essa(s) marca(s) -- e o que faz o numero "voltar"
// depois que a barra passa por cima e se afasta dali.
void restaurarMarcasNaFaixa(int inicio, int fim) {
  for (int i = 0; i < 3; i++) {
    int marca = (int)round(ESCALA_ANGULOS[i]);
    if (marca >= inicio && marca <= fim) {
      desenharMarcaEscala(i);
    }
  }
}

// pagina mudou: limpa a tela pro layout novo. Durante o splash/transicao
// nao mexe em nada -- essas fases ja limpam tudo sozinhas ao terminar.
void aoTrocarDePagina() {
  Serial.printf("DBG:pagina trocou para %d\n", paginaAtual);
  for (int i = 0; i < 4; i++) linhasDesenhadas[i] = "";
  anelCustom1 = anelCustom2 = -1; // pagina nova comeca sem anel, ate o pacote DELA mandar R1/R2
  if (mostrandoSplash || emTransicao) return;
  gfx->fillScreen(0x0000);
  escalaDesenhada = false;
  aneisPrecisamRedesenho = true;
}

// renderizador generico das telas personalizadas: mesma escala e mesmos
// aneis animados da tela classica (reaproveita grauCpu*/grauGpu* e a
// animarAneis() -- "CPU" = anel externo, "GPU" = anel interno, so muda
// de onde vem o alvo: R1/R2 em vez de cpuLoad/gpuLoad), com ate 4
// linhas de texto ja formatadas pelo app.
void desenharPainelCustom() {
  if (!escalaDesenhada) {
    desenharEscala();
    escalaDesenhada = true;
  }

  if (aneisPrecisamRedesenho) {
    grauCpuAtual = grauCpuAlvo = (int)round(GAUGE_INICIO);
    grauGpuAtual = grauGpuAlvo = (int)round(GAUGE_INICIO);
    velCpuAtual = 0;
    velGpuAtual = 0;
    aneisPrecisamRedesenho = false;
  }

  if (anelCustom1 >= 0) {
    grauCpuAlvo = (int)round(GAUGE_INICIO + (anelCustom1 / 100.0) * (GAUGE_FIM - GAUGE_INICIO));
  }
  if (anelCustom2 >= 0) {
    grauGpuAlvo = (int)round(GAUGE_INICIO + (anelCustom2 / 100.0) * (GAUGE_FIM - GAUGE_INICIO));
  }

  // sem startWrite() externo -- textoCentralizado (print), fillRect e
  // drawFastHLine abrem transacao SPI propria (aninhar = deadlock)
  const int alturasLinha[4] = { CY - 51, CY - 26, CY + 6, CY + 28 };
  uint16_t corCinza = gfx->color565(180, 180, 180);
  uint16_t coresLinha[4] = { corCpuFixa, corGpuFixa, corCinza, corCinza };

  for (int i = 0; i < 4; i++) {
    if (linhasCustom[i] == linhasDesenhadas[i]) continue;
    // largura mudou (usuario trocou a metrica da vaga)? limpa a faixa.
    // Com a mesma largura, o fundo do proprio texto apaga o valor antigo
    // -- mesma tecnica sem-piscar da tela classica.
    if (linhasCustom[i].length() != linhasDesenhadas[i].length()) {
      gfx->fillRect(14, alturasLinha[i] - 1, 212, 18, 0x0000);
    }
    if (linhasCustom[i].length() > 0) {
      textoCentralizado(linhasCustom[i], alturasLinha[i], 2, coresLinha[i]);
    }
    linhasDesenhadas[i] = linhasCustom[i];
  }

  gfx->drawFastHLine(CX - 45, CY - 3, 90, gfx->color565(50, 50, 50));

  // marca do produto, mesma posicao da tela classica
  textoCentralizado("OrbePC", CY + 82, 2, corLaranjaFixa);
}

void desenharPainel() {
  // se a tela anterior era uma mensagem de status ("Sem dados do PC" etc),
  // limpa tudo uma vez pra nao ficar mensagem velha atras do painel
  if (mostrandoMensagem) {
    gfx->fillScreen(0x0000);
    mostrandoMensagem = false;
    mostrandoSplash = false;
    aneisPrecisamRedesenho = true;
    escalaDesenhada = false; // a tela foi limpa, a escala precisa ser redesenhada
    for (int i = 0; i < 4; i++) linhasDesenhadas[i] = "";
  }

  // tela personalizada? o renderizador generico assume daqui
  if (paginaAtual != 0) {
    desenharPainelCustom();
    return;
  }

  if (!escalaDesenhada) {
    desenharEscala();
    escalaDesenhada = true;
  }

  if (aneisPrecisamRedesenho) {
    grauCpuAtual = grauCpuAlvo = (int)round(GAUGE_INICIO);
    grauGpuAtual = grauGpuAlvo = (int)round(GAUGE_INICIO);
    velCpuAtual = 0;
    velGpuAtual = 0;
    aneisPrecisamRedesenho = false;
  }

  // so atualiza o ALVO aqui -- quem realmente desenha o anel e a
  // animarAneis(), chamada com frequencia pelo loop()
  if (dados.cpuLoad >= 0) {
    float fimCpu = GAUGE_INICIO + (dados.cpuLoad / 100.0) * (GAUGE_FIM - GAUGE_INICIO);
    grauCpuAlvo = (int)round(fimCpu);
  }
  if (dados.gpuLoad >= 0) {
    float fimGpu = GAUGE_INICIO + (dados.gpuLoad / 100.0) * (GAUGE_FIM - GAUGE_INICIO);
    grauGpuAlvo = (int)round(fimGpu);
  }

  // NAO abrir startWrite() aqui: tudo abaixo (print via linhaTemperatura/
  // textoCentralizado, drawFastHLine) abre a PROPRIA transacao SPI por
  // dentro -- embrulhar numa transacao externa aninharia transacoes e
  // travaria o SPI de hardware do ESP32 (mutex nao-recursivo)

  // bloco de texto centralizado no meio do circulo -- largura sempre fixa
  // (com espacos), entao a cor de fundo do proprio texto apaga o valor
  // antigo, sem precisar limpar retangulo nenhum (rapido, sem "piscar")
  // (char)248 = simbolo de grau na fonte padrao do Adafruit_GFX -- junto com
  // o icone de termometro, deixa bem claro que esses dois valores sao temperatura
  String linhaCpu = "CPU " + (dados.cpuTemp >= 0 ? largFixa(String(dados.cpuTemp, 0), 3) + String((char)248) + "C" : String(" --"));
  String linhaGpu = "GPU " + (dados.gpuTemp >= 0 ? largFixa(String(dados.gpuTemp, 0), 3) + String((char)248) + "C" : String(" --"));
  String linhaRam = "RAM " + (dados.ramUsadaGB >= 0 ? largFixa(String(dados.ramUsadaGB, 1), 4) : String("  --")) + " GB";
  // sem espaco depois de "VRAM" de proposito -- "RAM " e "VRAM" ficam com
  // exatamente 4 caracteres cada, entao as duas linhas tem a mesma largura
  // total e o textoCentralizado() (que centraliza cada uma independente)
  // acaba alinhando os rotulos e os valores na mesma coluna sozinho
  String linhaVram = "VRAM" + (dados.vramUsadaGB >= 0 ? largFixa(String(dados.vramUsadaGB, 1), 4) : String("  --")) + " GB";

  // bloco centralizado verticalmente em torno de CY (deslocado um pouco
  // pra cima em relacao ao centro exato)
  linhaTemperatura(linhaCpu, CY - 51, 2, corCpuFixa);
  linhaTemperatura(linhaGpu, CY - 26, 2, corGpuFixa);

  gfx->drawFastHLine(CX - 45, CY - 3, 90, gfx->color565(50, 50, 50));

  uint16_t corCinza = gfx->color565(180, 180, 180);
  uint16_t corVermelha = gfx->color565(255, 40, 40);
  uint16_t corRam = (dados.ramPct >= limiteRamPct) ? corVermelha : corCinza;

  textoCentralizado(linhaRam, CY + 6, 2, corRam);
  textoCentralizado(linhaVram, CY + 28, 2, corGpuFixa);

  // marca do produto, bem perto da borda inferior da tela (area sem anel)
  textoCentralizado("OrbePC", CY + 82, 2, corLaranjaFixa);
}
