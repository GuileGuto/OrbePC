<#
publicar_app.ps1 -- automatiza o "deploy" de uma versao nova do OrbePC.exe
pro GitHub Releases, sem precisar abrir o site e criar tudo na mao.

O que faz, em ordem:
  1. Atualiza APP_VERSAO em orbepc_app.py pro valor pedido (assim o codigo
     e a tag do GitHub nunca ficam dessincronizados -- bug comum de
     esquecer de bater os dois).
  2. Reinstala dependencias e recompila (python -m PyInstaller OrbePC.spec).
  3. Assina o .exe (Authenticode), SE houver um certificado de assinatura
     de codigo instalado no Windows -- ver ASSINATURA DE CODIGO abaixo.
     Sem certificado configurado, esse passo so avisa e segue o deploy
     normalmente (nao quebra quem ainda nao comprou um certificado).
  4. Commita, cria a tag "vX.Y.Z" e da push (codigo + tag).
  5. Cria a Release no GitHub via GitHub CLI, ja com o dist\OrbePC.exe
     anexado (ja assinado, se o passo 3 rodou).

PRE-REQUISITOS (uma vez so):
  - GitHub CLI instalado:  winget install --id GitHub.cli
  - Autenticado:           gh auth login   (segue o fluxo no navegador)
  - git ja configurado (voce ja fez isso nesse projeto).

ASSINATURA DE CODIGO (opcional, mas recomendado antes de vender pra
clientes -- sem isso o Windows/SmartScreen mostra "Editor desconhecido"
no instalador e nas atualizacoes):
  1. Compra um certificado OV (Individual Validation) de uma CA tipo
     Sectigo ou Certum (~US$200-250/ano, verificacao de identidade leva
     alguns dias). Vem obrigatoriamente num token USB desde 2023 (regra
     do setor, nao da CA) -- nao e' mais um arquivo .pfx solto.
  2. Instala o software da CA/token (ex: SafeNet Authentication Client) e
     conecta o token -- isso registra o certificado no Windows sozinho
     (Cert:\CurrentUser\My ou Cert:\LocalMachine\My).
  3. Instala o "Windows SDK" (so' precisa do signtool.exe, pode marcar so'
     "Windows SDK Signing Tools" no instalador) se ainda nao tiver.
  4. So' rodar o script normalmente -- ele acha o certificado sozinho e
     assina. Se tiver mais de um certificado de assinatura de codigo
     instalado, passe -CertSubject "Nome exato do titular" pra escolher
     qual usar.

USO:
  .\publicar_app.ps1 -Versao 1.4.0
  .\publicar_app.ps1 -Versao 1.4.0 -Notas "Corrige tal coisa, adiciona tal outra"
  .\publicar_app.ps1 -Versao 1.4.0 -CertSubject "Guilherme Fulano de Tal"
#>

param(
    [Parameter(Mandatory = $true)][string]$Versao,
    [string]$Notas = "",
    [string]$CertSubject = ""
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

# 3) assina o .exe (Authenticode), se houver certificado de assinatura de
# codigo instalado -- ver comentario "ASSINATURA DE CODIGO" no topo do
# arquivo. Sem certificado, so avisa e segue (nao quebra o deploy de quem
# ainda nao comprou um).
Write-Host "--> Verificando certificado de assinatura de codigo..."
$signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if (-not $signtool) {
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match "x64" } | Select-Object -First 1 -ExpandProperty FullName
}

$certs = Get-ChildItem Cert:\CurrentUser\My, Cert:\LocalMachine\My -CodeSigningCert -ErrorAction SilentlyContinue
if ($CertSubject) { $certs = $certs | Where-Object { $_.Subject -match [regex]::Escape($CertSubject) } }

if (-not $signtool) {
    Write-Host "    Signtool.exe nao encontrado -- pulando assinatura (.exe vai sair sem assinar)." -ForegroundColor Yellow
    Write-Host "    Instale o 'Windows SDK Signing Tools' se ja tiver certificado. Ver ASSINATURA DE CODIGO no topo do script." -ForegroundColor Yellow
} elseif (-not $certs) {
    Write-Host "    Nenhum certificado de assinatura de codigo instalado -- pulando assinatura (.exe vai sair sem assinar)." -ForegroundColor Yellow
    Write-Host "    Ver comentario ASSINATURA DE CODIGO no topo deste script pra configurar." -ForegroundColor Yellow
} else {
    $cert = $certs | Select-Object -First 1
    Write-Host "--> Assinando $exe com certificado de '$($cert.Subject)'..."
    & $signtool sign /sha1 $cert.Thumbprint /fd sha256 /tr http://timestamp.digicert.com /td sha256 $exe
    if ($LASTEXITCODE -ne 0) { throw "signtool falhou ao assinar $exe" }
    Write-Host "    Assinado com sucesso." -ForegroundColor Green
}

# 4) commit + tag + push
Write-Host "--> Commitando e criando a tag $tag..."
git add -A
git commit -m "Release $tag" --allow-empty
git tag $tag
git push origin main
git push origin $tag

# 5) cria a Release no GitHub, ja com o executavel anexado
if ([string]::IsNullOrWhiteSpace($Notas)) { $Notas = "Release $tag" }

Write-Host "--> Publicando a Release no GitHub..."
gh release create $tag $exe --title $tag --notes $Notas

Write-Host "==> Pronto! $tag publicada com $exe anexado." -ForegroundColor Green
