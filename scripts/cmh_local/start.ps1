<#
.SYNOPSIS
    Deja el modelo local precargado y servido como 'cmh-local'.

.DESCRIPTION
    El endpoint de Odysseus pide un modelo por nombre. Si no hay nada cargado,
    LM Studio lo carga con los ajustes por defecto, que son los que crashean
    (0xC0000409, offload completo sobre una iGPU de 2,0 GB). Este guion lo deja
    cargado con el offload correcto, bajo el identificador que el router espera.

    NO se pasa --ttl a proposito. Verificado en `lms load --help` el 2026-09-28:
    "--ttl <seconds>  TTL: If provided, when the model is not used for this
    number of seconds, it will be unloaded". Pasarlo produce exactamente lo
    contrario de dejarlo precargado. Omitirlo lo mantiene cargado.

.EXAMPLE
    pwsh -File scripts/cmh_local/start.ps1 -Model "openai/gpt-oss-20b"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $Model,
    [double] $Gpu = 0.5,
    [int]    $ContextLength = 16384,
    [string] $Identifier = "cmh-local",
    [string] $BaseUrl = "http://127.0.0.1:1234/v1"
)

$ErrorActionPreference = "Stop"
$lms = Join-Path $env:USERPROFILE ".lmstudio\bin\lms.exe"
if (-not (Test-Path $lms)) { throw "No se encuentra lms.exe en $lms" }

try { Invoke-RestMethod -Uri "$BaseUrl/models" -TimeoutSec 5 | Out-Null }
catch { throw "LM Studio no responde en $BaseUrl. Abrelo y activa su servidor local." }

$loaded = (& $lms ps 2>&1 | Out-String)
if ($loaded -match [regex]::Escape($Identifier)) {
    Write-Host "Ya esta cargado como '$Identifier'. Nada que hacer." -ForegroundColor Green
    & $lms ps
    return
}

# Cualquier otro modelo cargado compite por la misma memoria compartida, que es
# el cuello de botella medido en esta maquina.
$others = (& $lms ps 2>&1 | Out-String)
if ($others -match 'IDENTIFIER' -and $others.Trim().Split("`n").Count -gt 2) {
    Write-Host "Descargando lo que hay cargado para liberar memoria..." -ForegroundColor Yellow
    & $lms unload --all 2>&1 | Out-Null
}

Write-Host "Cargando $Model (offload $Gpu, contexto $ContextLength, sin TTL)..."
& $lms load $Model --gpu $Gpu -c $ContextLength --identifier $Identifier -y
if ($LASTEXITCODE -ne 0) { throw "La carga fallo con exit $LASTEXITCODE. Baja --gpu (0.3) o el contexto." }

& $lms ps
Write-Host "`nListo. El router lo alcanza como '$Identifier' en $BaseUrl." -ForegroundColor Green
Write-Host "Registra ese endpoint en Settings -> Model Endpoints con tipo 'local' y supports_tools marcado."
