<#
.SYNOPSIS
    Deja el modelo local precargado y servido como 'cmh-local'.

.DESCRIPTION
    El endpoint de Odysseus pide un modelo por nombre. Si no hay nada cargado,
    LM Studio lo carga con los ajustes por defecto, que son los que crashean
    (0xC0000409, offload completo sobre una iGPU de 2,0 GB). Este guion lo deja
    cargado con el offload correcto, bajo el identificador que el router espera
    (config/cmh_free_quotas.json, "local.model").

    NO se pasa --ttl a proposito. Verificado en `lms load --help` el 2026-09-28:
    "--ttl <seconds>  TTL: If provided, when the model is not used for this
    number of seconds, it will be unloaded". Pasarlo produce exactamente lo
    contrario de dejarlo precargado. Omitirlo lo mantiene cargado.

    Descarga lo que haya cargado antes de cargar el modelo, porque compite por la
    misma memoria compartida, que es el cuello de botella medido en esta maquina.
    Dice cual descarga. Antes contaba las lineas de `lms ps` y exigia mas de 2:
    con un solo modelo cargado `lms ps` imprime el encabezado y UNA fila, o sea 2,
    asi que no descargaba nada justo en el caso que el guion existe para cubrir.

.EXAMPLE
    powershell -File scripts/cmh_local/start.ps1 -Model "openai/gpt-oss-20b"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $Model,
    [string] $Gpu = "0.5",
    [int]    $ContextLength = 16384,
    [string] $Identifier = "cmh-local",
    [string] $BaseUrl = "http://127.0.0.1:1234/v1",
    [string] $Lms = ""
)

$ErrorActionPreference = "Stop"
if (-not $Lms) { $Lms = Join-Path $env:USERPROFILE ".lmstudio\bin\lms.exe" }
if (-not (Test-Path $Lms)) { throw "No se encuentra lms en $Lms" }

function Invoke-Lms {
    # En Windows PowerShell 5.1, con ErrorActionPreference=Stop, la primera linea
    # de stderr de un ejecutable nativo capturada con 2>&1 es un error terminal.
    param([string[]] $Arguments)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $text = (& $Lms @Arguments 2>&1 | ForEach-Object { "$_" }) -join "`n"
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    [pscustomobject]@{ ExitCode = $code; Output = $text }
}

function Get-LoadedIdentifiers {
    # Filas de `lms ps` tras el encabezado; la primera columna es el identificador.
    $ps = (Invoke-Lms @("ps")).Output
    $ids = @()
    $seenHeader = $false
    foreach ($line in ($ps -split "`r?`n")) {
        if ($line -match '^\s*IDENTIFIER\b') { $seenHeader = $true; continue }
        if ($seenHeader -and $line.Trim()) { $ids += ($line.Trim() -split '\s+')[0] }
    }
    return $ids
}

try { Invoke-RestMethod -Uri "$BaseUrl/models" -TimeoutSec 5 | Out-Null }
catch { throw "LM Studio no responde en $BaseUrl. Abrelo y activa su servidor local." }

$loaded = @(Get-LoadedIdentifiers)
if ($loaded -contains $Identifier) {
    Write-Host "Ya esta cargado como '$Identifier'. Nada que hacer." -ForegroundColor Green
    Write-Host (Invoke-Lms @("ps")).Output
    return
}

$others = @($loaded | Where-Object { $_ -ne $Identifier })
if ($others.Count -gt 0) {
    Write-Host "Descargando lo que hay cargado para liberar memoria: $($others -join ', ')" -ForegroundColor Yellow
    [void](Invoke-Lms @("unload", "--all"))
}

Write-Host "Cargando $Model (offload $Gpu, contexto $ContextLength, sin TTL)..."
$load = Invoke-Lms @("load", $Model, "--gpu", $Gpu, "-c", "$ContextLength", "--identifier", $Identifier, "-y")
Write-Host $load.Output
if ($load.ExitCode -ne 0) { throw "La carga fallo con exit $($load.ExitCode). Baja -Gpu (0.3) o el contexto." }

Write-Host (Invoke-Lms @("ps")).Output
Write-Host "`nListo. El router lo alcanza como '$Identifier' en $BaseUrl." -ForegroundColor Green
Write-Host "Registralo en Settings > Add Models > Add API Models (Endpoint), tipo local, URL $BaseUrl."
