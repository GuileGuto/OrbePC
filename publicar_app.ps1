<#
publicar_app.ps1 -- automatiza o "deploy" de uma versao nova do OrbePC.exe
pro GitHub Releases, sem precisar abrir o site e criar tudo na mao.

O que faz, em ordem:
  1. Atualiza APP_VERSAO em orbepc_app.py pro valor pedido (assim o codigo
     e a tag do GitHub nunca ficam dessincronizados -- bug comum de
     esquecer de bater os dois).
  2. Reinstala dependencias e recompila (python -m PyInstaller OrbePC.spec).
  3. Commita, cria a tag "vX.Y.Z" e da push (codigo + tag).
  4. Cria a Release no GitHub via GitHub CLI, ja com o dist\OrbePC.exe
     anexado.

PRE-REQUISITOS (uma vez so):
  - GitHub CLI instalado:  winget install --id GitHub.cli
  - Autenticado:           gh auth login   (segue o fluxo no navegador)
  - git ja configurado (voce ja fez isso nesse projeto).

USO:
  .\publicar_app.ps1 -Versao 1.4.0
  .\publicar_app.ps1 -Versao 1.4.0 -Notas "Corrige tal coisa, adiciona tal outra"
#>

param(
    [Parameter(Mandatory = $true)][string]$Versao,
    [string]$Notas = ""
)

$ErrorActionPreference = "Stop"

$tag = "v$Versao"
$exe = "dist\OrbePC.exe"

Write-Host "==> Publicando OrbePC $tag" -ForegroundColor Cyan

# 1) sincroniza APP_VERSAO no codigo com a versao pedida aqui
Write-Host "--> Atualizando APP_VERSAO em orbepc_app.py..."
(Get-Content orbepc_app.py -Raw) -replace 'APP_VERSAO = "[^"]*"', "APP_VERSAO = `"$Versao`"" |
    Set-Content orbepc_app.py -NoNewline

# 2) fecha qualquer OrbePC.exe rodando -- o PyInstaller nao consegue
# sobrescrever o .exe se o processo (bandeja, ou autostart) estiver aberto
# segurando o arquivo (erro "Acesso negado" no os.remove()). --onefile as
# vezes aparece como 2 processos (bootloader + real), Stop-Process pega
# os dois pelo nome mesmo assim.
Write-Host "--> Fechando OrbePC.exe (se estiver rodando)..."
Stop-Process -Name "OrbePC" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

Write-Host "--> Instalando dependencias..."
python -m pip install -r requirements_app.txt
if ($LASTEXITCODE -ne 0) { throw "pip install falhou" }

Write-Host "--> Compilando (PyInstaller)..."
python -m PyInstaller OrbePC.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou" }

if (-not (Test-Path $exe)) {
    throw "Nao encontrei $exe depois do build -- confira os erros do PyInstaller acima."
}

# 3) commit + tag + push
Write-Host "--> Commitando e criando a tag $tag..."
git add -A
git commit -m "Release $tag" --allow-empty
git tag $tag
git push origin main
git push origin $tag

# 4) cria a Release no GitHub, ja com o executavel anexado
if ([string]::IsNullOrWhiteSpace($Notas)) { $Notas = "Release $tag" }

Write-Host "--> Publicando a Release no GitHub..."
gh release create $tag $exe --title $tag --notes $Notas

Write-Host "==> Pronto! $tag publicada com $exe anexado." -ForegroundColor Green
