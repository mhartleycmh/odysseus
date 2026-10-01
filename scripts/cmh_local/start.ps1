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

    Cargar un segundo modelo compite por la misma memoria compartida, que es el
    cuello de botella medido en esta maquina. Por eso, si hay OTRA cosa cargada, el
    guion se detiene y dice cual, y solo la descarga con -UnloadOthers: lo que el
    usuario tiene cargado es suyo (igual que en bench.ps1). Antes la descargaba
    avisando, sin preguntar, y el titulo de ADR-033 ("no tocan lo que no cargaron")
    no valia para este guion.

    Si 'cmh-local' ya esta cargado, comprueba que el modelo de atras sea el que se
    pidio con -Model: comparar solo el identificador daba por bueno cualquier modelo.
    Y no dice "Listo" sin releer `lms ps` y ver 'cmh-local' presente y nada mas.

    Un codigo de salida distinto de cero de `lms ps` o `lms unload` detiene el guion.

    En esta maquina la politica de ejecucion es Restricted: sin
    -ExecutionPolicy Bypass el .ps1 ni empieza.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/cmh_local/start.ps1 -Model "google/gemma-4-e4b"
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/cmh_local/start.ps1 -Model "google/gemma-4-e4b" -UnloadOthers
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $Model,
    [switch] $UnloadOthers,
    [string] $Gpu = "0.5",
    [int]    $ContextLength = 16384,
    [string] $Identifier = "cmh-local",
    [string] $BaseUrl = "http://127.0.0.1:1234/v1",
    [string] $Lms = ""
)

$ErrorActionPreference = "Stop"
if (-not $Lms) { $Lms = Join-Path $env:USERPROFILE ".lmstudio\bin\lms.exe" }
if (-not (Test-Path -LiteralPath $Lms)) { throw "No se encuentra lms en $Lms" }

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

function Test-SameModel {
    # lms acepta una clave parcial ("gemma-4-e4b" por "google/gemma-4-e4b") y `lms ps` imprime
    # la completa; una clave con espacios llega partida por celdas. Igualdad estricta daba por
    # fallida una carga que habia salido bien. Dos reglas exactas, y solo esas:
    #   1. la misma clave, sin distinguir mayusculas;
    #   2. la misma clave sin su publicador en uno de los dos lados (termina en "/" + la otra).
    # NUNCA una contencion libre: "phi-4-mini" esta contenida en "microsoft/phi-4-mini-reasoning"
    # y son modelos distintos; darlos por iguales dejaba el guion diciendo "Ya esta cargado"
    # sin cargar nada (revision de r8). Tampoco una tercera regla para claves con espacios:
    # `lms ps` se lee por espacios, asi que de "my-org/My Model Q8" solo llega la primera
    # palabra, y aceptar "la primera palabra" daba por igual el Q8 y el Q4 (revision de r9).
    # La clave con espacios no se reconoce al REPETIR el guion (pide -UnloadOthers); tras una
    # carga propia se acepta lo que lms puso bajo el identificador (ver mas abajo).
    # Con un lado vacio nada coincide: una fila de `lms ps` de una sola celda no es un modelo.
    param([string] $Loaded, [string] $Asked)
    if (-not $Loaded -or -not $Asked) { return $false }
    $ic = [StringComparison]::OrdinalIgnoreCase
    if ($Loaded.Equals($Asked, $ic)) { return $true }
    return ($Loaded.EndsWith("/" + $Asked, $ic) -or $Asked.EndsWith("/" + $Loaded, $ic))
}

function Get-Loaded {
    # Filas de `lms ps` tras el encabezado: identificador y modelo (columnas 1 y 2).
    # Un codigo de salida distinto de cero NO es "no hay nada cargado".
    $ps = Invoke-Lms @("ps")
    if ($ps.ExitCode -ne 0) { throw "lms ps fallo (exit $($ps.ExitCode)): $($ps.Output)" }
    $rows = @()
    $seenHeader = $false
    foreach ($line in ($ps.Output -split "`r?`n")) {
        if ($line -match '^\s*IDENTIFIER\b') { $seenHeader = $true; continue }
        if ($seenHeader -and $line.Trim()) {
            $cells = $line.Trim() -split '\s+'
            $rows += [pscustomobject]@{ Identifier = $cells[0]; Model = $(if ($cells.Count -gt 1) { $cells[1] } else { "" }) }
        }
    }
    return $rows
}

try { Invoke-RestMethod -Uri "$BaseUrl/models" -TimeoutSec 5 | Out-Null }
catch { throw "LM Studio no responde en $BaseUrl. Abrelo y activa su servidor local." }

$loaded = @(Get-Loaded)
$mine = @($loaded | Where-Object { $_.Identifier -eq $Identifier })
if ($mine.Count -gt 0 -and (Test-SameModel $mine[0].Model $Model)) {
    $extra = @($loaded | Where-Object { $_.Identifier -ne $Identifier })
    if ($extra.Count -eq 0) {
        Write-Host "Ya esta cargado como '$Identifier' ($Model). Nada que hacer." -ForegroundColor Green
        Write-Host (Invoke-Lms @("ps")).Output
        return
    }
}

# Todo lo cargado que no sea ya el modelo pedido bajo el identificador pedido.
$others = @($loaded | Where-Object { -not ($_.Identifier -eq $Identifier -and (Test-SameModel $_.Model $Model)) })
if ($others.Count -gt 0) {
    $names = ($others | ForEach-Object { "$($_.Identifier) ($($_.Model))" }) -join ', '
    if (-not $UnloadOthers) {
        throw ("Hay modelos cargados que este guion descargaria: $names. " +
               "Cargar otro encima compite por la memoria compartida y puede fallar. " +
               "Vuelve a correrlo con -UnloadOthers si aceptas descargarlos.")
    }
    Write-Host "Descargando lo que hay cargado para liberar memoria: $names (lo pediste con -UnloadOthers)" -ForegroundColor Yellow
    $unloaded = Invoke-Lms @("unload", "--all")
    if ($unloaded.ExitCode -ne 0) { throw "lms unload --all fallo (exit $($unloaded.ExitCode)): $($unloaded.Output)" }
}

Write-Host "Cargando $Model (offload $Gpu, contexto $ContextLength, sin TTL)..."
$load = Invoke-Lms @("load", $Model, "--gpu", $Gpu, "-c", "$ContextLength", "--identifier", $Identifier, "-y")
Write-Host $load.Output
if ($load.ExitCode -ne 0) { throw "La carga fallo con exit $($load.ExitCode). Baja -Gpu (0.3) o el contexto." }

# No se dice "Listo" sin verlo: 'cmh-local' presente y nada mas. `lms load` resuelve una clave
# parcial ("gemma-4" -> google/gemma-4-e4b, "qwen3.5" -> qwen/qwen3.5-9b) y carga "el primero":
# esta llamada acaba de crear la fila bajo $Identifier, asi que lo que muestra ES lo que se cargo.
# No se compara por nombre (un prefijo no es una igualdad): se IMPRIME, y si no se parece a lo
# pedido se avisa.
$after = @(Get-Loaded)
$serving = @($after | Where-Object { $_.Identifier -eq $Identifier })
if ($serving.Count -eq 0) {
    throw "La carga termino sin error pero '$Identifier' no aparece en 'lms ps' (se pidio $Model)."
}
if (-not (Test-SameModel $serving[0].Model $Model)) {
    Write-Host ("AVISO: lms cargo '$($serving[0].Model)' al pedirle '$Model'. Comprueba que es el modelo " +
                "que querias; con la clave completa de 'lms ls' no se depende de como lms resuelve un nombre parcial.") -ForegroundColor Yellow
}
$left = @($after | Where-Object { $_.Identifier -ne $Identifier })
if ($left.Count -gt 0) {
    throw "Quedaron cargados otros modelos: $(($left | ForEach-Object { $_.Identifier }) -join ', '). Comparten la memoria con '$Identifier'."
}

Write-Host (Invoke-Lms @("ps")).Output
Write-Host "`nListo. El router lo alcanza como '$Identifier' en $BaseUrl." -ForegroundColor Green
Write-Host "Registralo en Settings > Add Models > Add API Models (Endpoint), tipo local, URL $BaseUrl."
