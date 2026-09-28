<#
.SYNOPSIS
    Mide los candidatos locales con la MISMA peticion, y reporta numeros.

.DESCRIPTION
    Con LM Studio corriendo, carga cada candidato con el mismo offload y el
    mismo contexto, le hace 3 rondas identicas con tool calling, y mide:
    tok/s de generacion, segundos al primer token, si finish_reason fue
    'tool_calls' en las 3 rondas, y memoria residente del runtime.

    Por que --gpu 0.5 y no el valor por defecto: la carga automatica intenta
    offload completo sobre una iGPU de 2,0 GB y crashea con 0xC0000409
    (stack buffer overrun), reproducido 2 de 2 el 2026-09-27.

    Por que NO se pasa --ttl: verificado en `lms load --help`, --ttl descarga
    el modelo tras N segundos sin uso. Para dejarlo cargado hay que omitirlo.

    El ganador es el candidato local del router. Un modelo que falle el tool
    calling queda descartado aunque sea el mas rapido: un paso de flujo que no
    puede llamar herramientas no pasa la guardia de evidencia.

.EXAMPLE
    pwsh -File scripts/cmh_local/bench.ps1
    pwsh -File scripts/cmh_local/bench.ps1 -Models "google/gemma-4-e4b","openai/gpt-oss-20b"
#>
[CmdletBinding()]
param(
    [string[]] $Models = @(),
    [double]   $Gpu = 0.5,
    [int]      $ContextLength = 16384,
    [int]      $Rounds = 3,
    [string]   $BaseUrl = "http://127.0.0.1:1234/v1",
    [string]   $OutFile = ""
)

$ErrorActionPreference = "Stop"
$lms = Join-Path $env:USERPROFILE ".lmstudio\bin\lms.exe"
if (-not (Test-Path $lms)) { throw "No se encuentra lms.exe en $lms" }

# Una sola peticion para todos, o la comparacion no compara nada.
$tools = @(
    @{ type = "function"; function = @{
        name = "ls"; description = "Lista archivos de una carpeta"
        parameters = @{ type = "object"
                        properties = @{ path = @{ type = "string" } }
                        required = @("path") } } },
    @{ type = "function"; function = @{
        name = "read_file"; description = "Lee un archivo de texto"
        parameters = @{ type = "object"
                        properties = @{ path = @{ type = "string" } }
                        required = @("path") } } }
)
$prompt = "Lista la carpeta 'input', lee el archivo que encuentres y resume su contenido en 150 palabras. Usa las herramientas antes de responder."

function Invoke-Round {
    param([string] $Model)
    $body = @{ model = $Model
               messages = @(@{ role = "user"; content = $prompt })
               tools = $tools
               stream = $false
               max_tokens = 400 } | ConvertTo-Json -Depth 12
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $response = Invoke-RestMethod -Uri "$BaseUrl/chat/completions" -Method Post `
        -ContentType "application/json" -Body $body -TimeoutSec 900
    $watch.Stop()
    $choice = $response.choices[0]
    $completion = if ($response.usage) { [int]$response.usage.completion_tokens } else { 0 }
    [pscustomobject]@{
        Seconds      = [math]::Round($watch.Elapsed.TotalSeconds, 2)
        Tokens       = $completion
        TokensPerSec = if ($watch.Elapsed.TotalSeconds -gt 0) {
                           [math]::Round($completion / $watch.Elapsed.TotalSeconds, 2) } else { 0 }
        FinishReason = [string]$choice.finish_reason
        ToolCalls    = if ($choice.message.tool_calls) { $choice.message.tool_calls.Count } else { 0 }
    }
}

if (-not $Models -or $Models.Count -eq 0) {
    Write-Host "Sin -Models: se miden los LLM que ya estan en disco." -ForegroundColor Yellow
    $Models = & $lms ls 2>$null |
        Select-String -Pattern '^(\S+/\S+)' |
        ForEach-Object { $_.Matches[0].Groups[1].Value } |
        Where-Object { $_ -notmatch 'embed' } | Select-Object -Unique
}
if (-not $Models) { throw "No hay modelos que medir." }

Write-Host "Candidatos: $($Models -join ', ')"
Write-Host "Offload $Gpu | contexto $ContextLength | $Rounds rondas por modelo`n"

$results = foreach ($model in $Models) {
    Write-Host "== $model ==" -ForegroundColor Cyan
    $estimate = (& $lms load $model --estimate-only -c $ContextLength -y 2>&1 | Out-String)
    $estimated = if ($estimate -match 'Estimated Total Memory:\s*([\d.]+)\s*GiB') { [double]$Matches[1] } else { $null }
    Write-Host "   memoria estimada: $estimated GiB"

    & $lms unload --all 2>&1 | Out-Null
    $loadWatch = [System.Diagnostics.Stopwatch]::StartNew()
    # Sin --ttl a proposito: --ttl DESCARGA tras N segundos sin uso.
    $load = (& $lms load $model --gpu $Gpu -c $ContextLength --identifier cmh-local -y 2>&1 | Out-String)
    $loadWatch.Stop()
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   NO CARGA (exit $LASTEXITCODE)" -ForegroundColor Red
        [pscustomobject]@{ Model = $model; Loaded = $false; Error = $load.Trim()
                           EstimatedGiB = $estimated; LoadSeconds = $null
                           TokensPerSec = $null; FirstRoundSeconds = $null
                           ToolCallsOk = $false; ResidentMB = $null }
        continue
    }

    $rounds = @()
    $failure = $null
    for ($i = 1; $i -le $Rounds; $i++) {
        try { $round = Invoke-Round -Model "cmh-local"; $rounds += $round
              Write-Host ("   ronda {0}: {1} tok/s, {2} s, finish={3}, tool_calls={4}" -f `
                          $i, $round.TokensPerSec, $round.Seconds, $round.FinishReason, $round.ToolCalls) }
        catch { $failure = $_.Exception.Message; Write-Host "   ronda $i FALLA: $failure" -ForegroundColor Red; break }
    }
    $resident = (Get-Process -Name "*llama*","*lms*" -ErrorAction SilentlyContinue |
                 Measure-Object WorkingSet64 -Sum).Sum
    $toolOk = ($rounds.Count -eq $Rounds) -and
              (($rounds | Where-Object { $_.FinishReason -eq 'tool_calls' -and $_.ToolCalls -gt 0 }).Count -eq $Rounds)

    [pscustomobject]@{
        Model = $model; Loaded = $true; Error = $failure
        EstimatedGiB = $estimated
        LoadSeconds = [math]::Round($loadWatch.Elapsed.TotalSeconds, 1)
        TokensPerSec = if ($rounds) { [math]::Round(($rounds | Measure-Object TokensPerSec -Average).Average, 2) } else { $null }
        FirstRoundSeconds = if ($rounds) { $rounds[0].Seconds } else { $null }
        # Las 3 rondas, no una: el tool calling intermitente es el defecto que
        # se escapa midiendo una sola vez.
        ToolCallsOk = $toolOk
        ResidentMB = if ($resident) { [math]::Round($resident / 1MB, 0) } else { $null }
    }
}

& $lms unload --all 2>&1 | Out-Null

Write-Host "`n=== RESULTADO ===" -ForegroundColor Green
$results | Format-Table Model, Loaded, EstimatedGiB, TokensPerSec, FirstRoundSeconds, ToolCallsOk, ResidentMB -AutoSize

$winner = $results | Where-Object { $_.Loaded -and $_.ToolCallsOk } |
          Sort-Object TokensPerSec -Descending | Select-Object -First 1
if ($winner) {
    Write-Host "Ganador: $($winner.Model) - $($winner.TokensPerSec) tok/s con tool calling en $Rounds de $Rounds rondas." -ForegroundColor Green
    Write-Host "Es el candidato local del router. Precargalo con scripts/cmh_local/start.ps1."
} else {
    Write-Host "NINGUN candidato pasa: sin tool calling en las $Rounds rondas no sirve para un paso de flujo." -ForegroundColor Red
}

if ($OutFile) { $results | ConvertTo-Json -Depth 5 | Set-Content -Path $OutFile -Encoding utf8
                Write-Host "Medicion guardada en $OutFile" }
