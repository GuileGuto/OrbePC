<#
publicar_firmware.ps1 -- automatiza o "deploy" de um firmware novo do
ESP32-C3 pro GitHub Releases (mesmo repo do app, tag com prefixo
"firmware-" -- ver atualizacao_engine.py), sem precisar abrir o site.

O que faz, em ordem:
  1. Atualiza FIRMWARE_VERSAO no painel_pc_esp32c3.ino pro valor pedido.
  2. Compila o sketch via arduino-cli (headless, sem abrir a IDE) e
     exporta o merged binary.
  3. Commita, cria a tag "firmware-vX.Y.Z" e da push.
  4. Cria a Release no GitHub via GitHub CLI, ja com o .bin anexado.

PRE-REQUISITOS (uma vez so):
  - GitHub CLI instalado e autenticado (mesmo do publicar_app.ps1).
  - arduino-cli instalado:  winget install --id ArduinoSA.CLI
    Depois, uma vez so, instala o core e as libs (mesmas do Arduino IDE):
      arduino-cli core update-index
      arduino-cli core install esp32:esp32
      arduino-cli lib install "Adafruit GFX Library" "Adafruit GC9A01A"
  Se preferir continuar exportando pelo Arduino IDE manualmente (Sketch >
  Exportar Binario Compilado), pule a compilacao automatica com
  -PularBuild e so' aponta o arquivo com -Bin.

USO:
  .\publicar_firmware.ps1 -Versao 1.4.0
  .\publicar_firmware.ps1 -Versao 1.4.0 -PularBuild -Bin "caminho\pro\arquivo.merged.bin"
#>

param(
    [Parameter(Mandatory = $true)][string]$Versao,
    [string]$Notas = "",
    [string]$Bin = "",
    [switch]$PularBuild
)

$ErrorActionPreference = "Stop"

$tag = "firmware-v$Versao"
$fqbn = "esp32:esp32:esp32c3"
$pastaSketch = "painel_pc_esp32c3"
$pastaBuild = Join-Path $pastaSketch "build\esp32.esp32.esp32c3"

Write-Host "==> Publicando firmware $tag" -ForegroundColor Cyan

# 1) sincroniza FIRMWARE_VERSAO no .ino com a versao pedida aqui
$inoPath = Join-Path $pastaSketch "painel_pc_esp32c3.ino"
Write-Host "--> Atualizando FIRMWARE_VERSAO em $inoPath..."
(Get-Content $inoPath -Raw) -replace '#define FIRMWARE_VERSAO "[^"]*"', "#define FIRMWARE_VERSAO `"$Versao`"" |
    Set-Content $inoPath -NoNewline

# 2) compila via arduino-cli (a menos que -PularBuild tenha sido passado)
if (-not $PularBuild) {
    Write-Host "--> Compilando com arduino-cli..."
    arduino-cli compile --fqbn $fqbn --export-binaries $pastaSketch
    if ($LASTEXITCODE -ne 0) { throw "arduino-cli compile falhou" }

    $Bin = Join-Path $pastaBuild "painel_pc_esp32c3.ino.merged.bin"
} elseif ([string]::IsNullOrWhiteSpace($Bin)) {
    throw "Com -PularBuild, precisa passar -Bin apontando pro .merged.bin exportado."
}

if (-not (Test-Path $Bin)) {
    throw "Nao encontrei o binario em '$Bin'. Se compilou pelo Arduino IDE, confira o caminho exato (Sketch > Show Sketch Folder > build\...)."
}

# 3) commit + tag + push
Write-Host "--> Commitando e criando a tag $tag..."
git add -A
git commit -m "Firmware $tag" --allow-empty
git tag $tag
git push origin main
git push origin $tag

# 4) cria a Release no GitHub, ja com o .bin anexado
if ([string]::IsNullOrWhiteSpace($Notas)) { $Notas = "Firmware $tag" }

Write-Host "--> Publicando a Release no GitHub..."
gh release create $tag $Bin --title $tag --notes $Notas

Write-Host "==> Pronto! $tag publicada com $(Split-Path $Bin -Leaf) anexado." -ForegroundColor Green
