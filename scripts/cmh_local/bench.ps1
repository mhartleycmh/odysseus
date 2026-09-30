<#
.SYNOPSIS
    Mide los candidatos locales con la MISMA conversacion, y reporta numeros.

.DESCRIPTION
    Con LM Studio corriendo, carga cada candidato con el mismo offload y el
    mismo contexto y le hace una conversacion de hasta N rondas con tool
    calling REAL: el guion ejecuta cada herramienta que el modelo pide
    (ls, read_file, con resultados sinteticos) y le devuelve el resultado, hasta
    que el modelo responde con texto. Mide, por modelo:

      - segundos al primer token (streaming), el de la PRIMERA ronda,
      - tok/s de generacion: tokens (menos el primero) sobre el tiempo posterior
        al primer token, y solo de las rondas que llegaron en al menos 3 trozos.
        Una ronda que el servidor entrega de un golpe (una llamada a herramienta
        en un solo fragmento) mete sus tokens en el numerador y deja su tiempo en
        el "primer token": no se cuenta. TotalTokensPerSec, sobre el tiempo total
        incluido el prompt, se muestra para comparar y NO decide nada,
      - si CADA llamada a herramienta trae un nombre valido y argumentos JSON
        con 'path', y si el modelo llego a una respuesta final (finish_reason
        'stop' y texto no vacio; un flujo cortado o una ronda que agoto max_tokens
        razonando NO es una respuesta),
      - memoria del runtime (aproximada).

    Que NO hace, por lo que costo descubrirlo (auditoria del 2026-09-29):
      - No toca lo que el usuario tenga cargado, NI SIQUIERA 'cmh-local', que es
        lo que start.ps1 deja cargado como respaldo del router. Mide bajo el
        identificador 'cmh-bench' y solo descarga ese. Si hay otra cosa cargada se
        detiene y lo dice, salvo que se pase -UnloadOthers.
      - No mide todo el disco. Por defecto mide los tres candidatos del
        blueprint (11.2), buscados por nombre; -All mide todos los LLM.
      - No usa `2>&1` sobre lms.exe con ErrorActionPreference=Stop: en Windows
        PowerShell 5.1, la primera linea de stderr de un ejecutable nativo se
        vuelve un error terminal y el guion abortaba en su primera llamada.
      - No infiere. Si `lms ls`, `lms ps` o `lms unload` devuelven un codigo
        distinto de cero, se detiene con lo que lms dijo: antes declaraba los tres
        candidatos "no esta en disco" o media con el modelo del usuario aun cargado.

    Por que --gpu 0.5 y no el valor por defecto: la carga automatica intenta
    offload completo sobre una iGPU de 2,0 GB y crashea con 0xC0000409
    (stack buffer overrun), reproducido 2 de 2 el 2026-09-27.

    Por que NO se pasa --ttl: verificado en `lms load --help`, --ttl descarga
    el modelo tras N segundos sin uso. Para dejarlo cargado hay que omitirlo.

    El ganador es el candidato local del router. Un modelo que falle el tool
    calling queda descartado aunque sea el mas rapido: un paso de flujo que no
    puede llamar herramientas no pasa la guardia de evidencia. Para servirlo al
    router hay que cargarlo como 'cmh-local' con start.ps1.

    Sale con codigo 0 si hay un ganador y 1 si ningun candidato paso.

    En esta maquina la politica de ejecucion es Restricted: sin
    -ExecutionPolicy Bypass el .ps1 ni empieza. Con -File una lista llega como una
    sola cadena: usa comas, -Models "a,b".

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/cmh_local/bench.ps1 -UnloadOthers
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/cmh_local/bench.ps1 -Models "google/gemma-4-e4b,openai/gpt-oss-20b" -UnloadOthers
#>
[CmdletBinding()]
param(
    [string[]] $Models = @(),
    [switch]   $All,
    [switch]   $UnloadOthers,
    [string]   $Gpu = "0.5",
    [int]      $ContextLength = 16384,
    [int]      $Rounds = 3,
    [int]      $MaxTokens = 1024,
    [string]   $Identifier = "cmh-bench",
    [string]   $BaseUrl = "http://127.0.0.1:1234/v1",
    [string]   $Lms = "",
    [string]   $OutFile = ""
)

$ErrorActionPreference = "Stop"
if (-not $Lms) { $Lms = Join-Path $env:USERPROFILE ".lmstudio\bin\lms.exe" }
if (-not (Test-Path -LiteralPath $Lms)) { throw "No se encuentra lms en $Lms" }

# Con -File una lista llega como una sola cadena 'a,b': se parte por comas.
$Models = @($Models | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })

# El identificador del respaldo local del router (config local.model). Este banco no mide
# bajo ese nombre: descargaria justo lo que start.ps1 deja cargado. Antes bastaba pasar
# -Identifier cmh-local para reabrir ese defecto por otra puerta.
$RouterIdentifier = "cmh-local"
$ConfigPath = Join-Path $PSScriptRoot "..\..\config\cmh_free_quotas.json"
if (Test-Path -LiteralPath $ConfigPath) {
    try {
        $fromConfig = ([System.IO.File]::ReadAllText($ConfigPath, [System.Text.Encoding]::UTF8) |
                       ConvertFrom-Json).local.model
        if ($fromConfig) { $RouterIdentifier = [string]$fromConfig }
    } catch { }
}
if ($Identifier -eq $RouterIdentifier) {
    throw ("-Identifier '$Identifier' es el identificador del respaldo local del router " +
           "(config local.model). Este banco no mide bajo ese nombre: descargaria lo que " +
           "start.ps1 deja cargado. Usa otro, por ejemplo cmh-bench.")
}

# Los tres candidatos del blueprint (11.2), por nombre. Se buscan en `lms ls`.
$Candidates = @("gemma-4-e4b", "qwen3.5-4b", "phi-4-mini")

# Una ronda cuenta para tok/s solo si llego en al menos tantos trozos.
$MinDeltasForRate = 3

function Invoke-Lms {
    # Llama a lms sin que su stderr aborte el guion. En Windows PowerShell 5.1,
    # con ErrorActionPreference=Stop, `2>&1` sobre un nativo convierte la primera
    # linea de stderr en un error terminal. Aqui se relaja solo alrededor de la
    # llamada, y se conserva el codigo de salida.
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
    # Un codigo de salida distinto de cero NO es "no hay nada cargado".
    $ps = Invoke-Lms @("ps")
    if ($ps.ExitCode -ne 0) { throw "lms ps fallo (exit $($ps.ExitCode)): $($ps.Output)" }
    $ids = @()
    $seenHeader = $false
    foreach ($line in ($ps.Output -split "`r?`n")) {
        if ($line -match '^\s*IDENTIFIER\b') { $seenHeader = $true; continue }
        if ($seenHeader -and $line.Trim()) { $ids += ($line.Trim() -split '\s+')[0] }
    }
    return $ids
}

function Remove-Own {
    # Descarga lo que ESTE guion cargo y comprueba que se fue. No se fia del codigo de salida:
    # el lms real sale con 0 ante "Model Not Found", y una descarga que falla dejaria al
    # candidato anterior en la memoria compartida bajo el mismo identificador. Devuelve $true
    # si el identificador SIGUE cargado.
    [void](Invoke-Lms @("unload", $Identifier))
    return (@(Get-LoadedIdentifiers) -contains $Identifier)
}

# La misma conversacion para todos, o la comparacion no compara nada.
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
$fileText = ("La empresa ficticia Minera Ejemplo produjo 1200 toneladas en marzo y 1350 en abril. " * 6).Trim()

function Invoke-Tool {
    param([string] $Name, [string] $Path)
    if ($Name -eq "ls") { return "piloto_sintetico.txt" }
    if ($Name -eq "read_file") { return $fileText }
    return "herramienta desconocida"
}

function Invoke-Chat {
    # Una ronda con streaming, para medir el primer token.
    param([object[]] $Messages, [string] $Model)
    $body = @{ model = $Model; messages = $Messages; tools = $tools; stream = $true
               stream_options = @{ include_usage = $true }; max_tokens = $MaxTokens } | ConvertTo-Json -Depth 12
    $request = [System.Net.HttpWebRequest]::Create("$BaseUrl/chat/completions")
    $request.Method = "POST"
    $request.ContentType = "application/json"
    $request.Timeout = 900000
    $request.ReadWriteTimeout = 900000
    # Trafico a un runtime local: nunca por el proxy del sistema.
    $request.Proxy = $null
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
    $out = $request.GetRequestStream()
    $out.Write($bytes, 0, $bytes.Length)
    $out.Close()

    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $response = $request.GetResponse()
    $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
    $first = $null
    $content = New-Object System.Text.StringBuilder
    $calls = @{}
    $finish = ""
    $usageTokens = $null
    $deltas = 0
    try {
        while ($true) {
            $line = $reader.ReadLine()
            if ($null -eq $line) { break }
            if (-not $line.StartsWith("data:")) { continue }
            $data = $line.Substring(5).Trim()
            if ($data -eq "[DONE]") { break }
            $chunk = $data | ConvertFrom-Json
            if ($chunk.usage -and $chunk.usage.completion_tokens) {
                $usageTokens = [int]$chunk.usage.completion_tokens
            }
            if (-not $chunk.choices -or $chunk.choices.Count -eq 0) { continue }
            $choice = $chunk.choices[0]
            $delta = $choice.delta
            $hasText = $delta -and ($delta.content -or $delta.reasoning_content)
            $hasCall = $delta -and $delta.tool_calls
            if (($hasText -or $hasCall) -and $null -eq $first) { $first = $watch.Elapsed.TotalSeconds }
            if ($hasText -or $hasCall) { $deltas++ }
            if ($delta -and $delta.content) { [void]$content.Append([string]$delta.content) }
            if ($hasCall) {
                foreach ($piece in @($delta.tool_calls)) {
                    $index = if ($null -ne $piece.index) { [int]$piece.index } else { 0 }
                    if (-not $calls.ContainsKey($index)) {
                        $calls[$index] = @{ Id = ""; Name = ""; Args = (New-Object System.Text.StringBuilder) }
                    }
                    if ($piece.id) { $calls[$index].Id = [string]$piece.id }
                    if ($piece.function.name) { $calls[$index].Name += [string]$piece.function.name }
                    if ($piece.function.arguments) { [void]$calls[$index].Args.Append([string]$piece.function.arguments) }
                }
            }
            if ($choice.finish_reason) { $finish = [string]$choice.finish_reason }
        }
    } finally {
        $reader.Close()
        $response.Close()
    }
    $watch.Stop()
    $total = $watch.Elapsed.TotalSeconds
    $generation = if ($null -ne $first) { $total - $first } else { $total }
    $tokens = if ($null -ne $usageTokens) { $usageTokens } else { $deltas }
    $ordered = @()
    foreach ($key in ($calls.Keys | Sort-Object)) {
        $ordered += [pscustomobject]@{ Id = $calls[$key].Id; Name = $calls[$key].Name
                                       Arguments = $calls[$key].Args.ToString() }
    }
    [pscustomobject]@{
        TotalSeconds = [math]::Round($total, 2)
        FirstTokenSeconds = if ($null -ne $first) { [math]::Round($first, 2) } else { $null }
        GenerationSeconds = [math]::Round($generation, 2)
        Tokens = $tokens
        TokensEstimated = ($null -eq $usageTokens)
        Deltas = $deltas
        FinishReason = $finish
        Content = $content.ToString()
        ToolCalls = $ordered
    }
}

function Invoke-Conversation {
    param([string] $Model)
    $messages = @(@{ role = "user"; content = $prompt })
    # NOT named $rounds: PowerShell variables ignore case, so a local $rounds would
    # shadow the -Rounds parameter and `$i -le $Rounds` would compare a number
    # with an empty array.
    $turns = @()
    $valid = $true
    $answered = $false
    $note = "rondas agotadas ($Rounds) sin una respuesta final"
    $toolCallCount = 0
    for ($i = 1; $i -le $Rounds; $i++) {
        $round = Invoke-Chat -Messages $messages -Model $Model
        $turns += $round
        Write-Host ("   ronda {0}: primer token {1} s, {2} tokens, finish={3}, herramientas={4}" -f `
                    $i, $round.FirstTokenSeconds, $round.Tokens, $round.FinishReason, $round.ToolCalls.Count)
        if ($round.ToolCalls.Count -eq 0) {
            # A round with no tool call is the final answer only if the model SAID it was
            # done (finish_reason 'stop') and wrote something. A stream cut in half, or a
            # round that spent max_tokens reasoning and wrote nothing, used to count.
            $length = $round.Content.Trim().Length
            if ($round.FinishReason -eq "stop" -and $length -gt 0) { $answered = $true }
            else { $note = "la ronda $i termino sin respuesta final (finish='$($round.FinishReason)', $length caracteres de texto)" }
            break
        }
        $assistantCalls = @()
        foreach ($call in $round.ToolCalls) {
            $toolCallCount++
            $path = $null
            try { $path = ($call.Arguments | ConvertFrom-Json).path } catch { $path = $null }
            if (-not $call.Name -or -not ($call.Name -in @("ls", "read_file")) -or -not $path) { $valid = $false }
            $assistantCalls += @{ id = $call.Id; type = "function"
                                  function = @{ name = $call.Name; arguments = $call.Arguments } }
        }
        $messages += @{ role = "assistant"; content = $round.Content; tool_calls = $assistantCalls }
        foreach ($call in $round.ToolCalls) {
            $path = $null
            try { $path = ($call.Arguments | ConvertFrom-Json).path } catch { $path = $null }
            $messages += @{ role = "tool"; tool_call_id = $call.Id; content = (Invoke-Tool -Name $call.Name -Path $path) }
        }
    }
    [pscustomobject]@{ Rounds = $turns; ToolCallCount = $toolCallCount; ToolCallsValid = $valid
                       Answered = $answered; Note = $(if ($answered) { $null } else { $note }) }
}

# --- que se mide -------------------------------------------------------------
$listing = Invoke-Lms @("ls")
if ($listing.ExitCode -ne 0) { throw "lms ls fallo (exit $($listing.ExitCode)): $($listing.Output)" }
$onDisk = @()
foreach ($line in ($listing.Output -split "`r?`n")) {
    if ($line -match '^(\S+/\S+)') { $key = $Matches[1]; if ($key -notmatch 'embed') { $onDisk += $key } }
}
if ($Models -and $Models.Count -gt 0) {
    $wanted = @($Models)
} elseif ($All) {
    Write-Host "-All: se miden todos los LLM del disco." -ForegroundColor Yellow
    $wanted = @($onDisk | Select-Object -Unique)
} else {
    $wanted = @()
    foreach ($name in $Candidates) {
        $hit = @($onDisk | Where-Object { $_ -like "*$name*" } | Select-Object -First 1)
        $wanted += if ($hit.Count -gt 0) { $hit[0] } else { "NO-DESCARGADO:$name" }
    }
}
if (-not $wanted -or $wanted.Count -eq 0) { throw "No hay modelos que medir." }

# --- no tocar lo que el usuario tiene cargado --------------------------------
# Solo el identificador de este banco es nuestro. 'cmh-local' es lo que start.ps1 dejo
# como respaldo del router: descargarlo lo deja respondiendo 404 hasta repetir start.ps1.
$loadedNow = @(Get-LoadedIdentifiers)
if ($loadedNow -contains $Identifier) {
    Write-Host "Habia un '$Identifier' de una corrida anterior (caida o interrumpida): es de este banco y se descarga." -ForegroundColor Yellow
}
$others = @($loadedNow | Where-Object { $_ -ne $Identifier })
if ($others.Count -gt 0) {
    if (-not $UnloadOthers) {
        throw ("Hay modelos cargados que este banco descargaria: $($others -join ', '). " +
               "Cargar un candidato encima compite por la memoria compartida y puede fallar. " +
               "Vuelve a correrlo con -UnloadOthers si aceptas descargarlos.")
    }
    Write-Host "Descargando lo que hay cargado ($($others -join ', ')): lo pediste con -UnloadOthers." -ForegroundColor Yellow
    $unloaded = Invoke-Lms @("unload", "--all")
    if ($unloaded.ExitCode -ne 0) { throw "lms unload --all fallo (exit $($unloaded.ExitCode)): $($unloaded.Output)" }
    $left = @(Get-LoadedIdentifiers | Where-Object { $_ -ne $Identifier })
    if ($left.Count -gt 0) { throw "Tras descargar siguen cargados: $($left -join ', '). Medir con eso en memoria contaminaria el resultado." }
}

Write-Host "Candidatos: $($wanted -join ', ')"
Write-Host "Offload $Gpu | contexto $ContextLength | hasta $Rounds rondas por modelo | max_tokens $MaxTokens | identificador $Identifier`n"

$results = foreach ($model in $wanted) {
    Write-Host "== $model ==" -ForegroundColor Cyan
    if ($model -like "NO-DESCARGADO:*") {
        Write-Host "   no esta en disco: falta descargarlo (U4)" -ForegroundColor Yellow
        [pscustomobject]@{ Model = $model -replace '^NO-DESCARGADO:', ''; Loaded = $false
                           Error = "no esta en disco (accion U4)"; EstimatedGiB = $null
                           LoadSeconds = $null; Rounds = 0; Answered = $false; ToolCallsOk = $false
                           FirstTokenSeconds = $null; TokensPerSec = $null; TotalTokensPerSec = $null
                           TokensEstimated = $null; ResidentMB = $null }
        continue
    }
    $estimate = (Invoke-Lms @("load", $model, "--estimate-only", "-c", "$ContextLength", "-y")).Output
    $estimated = if ($estimate -match 'Estimated Total Memory:\s*([\d.]+)\s*GiB') { [double]$Matches[1] } else { $null }
    Write-Host "   memoria estimada: $estimated GiB"

    # Solo lo que este guion cargo: la vez anterior, bajo su propio identificador.
    if (Remove-Own) {
        throw "lms unload $Identifier no lo descargo: sigue cargado y medir encima del candidato anterior contaminaria el resultado."
    }
    $loadWatch = [System.Diagnostics.Stopwatch]::StartNew()
    # Sin --ttl a proposito: --ttl DESCARGA tras N segundos sin uso.
    $load = Invoke-Lms @("load", $model, "--gpu", $Gpu, "-c", "$ContextLength", "--identifier", $Identifier, "-y")
    $loadWatch.Stop()
    if ($load.ExitCode -ne 0) {
        Write-Host "   NO CARGA (exit $($load.ExitCode))" -ForegroundColor Red
        [pscustomobject]@{ Model = $model; Loaded = $false; Error = $load.Output.Trim()
                           EstimatedGiB = $estimated; LoadSeconds = $null; Rounds = 0
                           Answered = $false; ToolCallsOk = $false; FirstTokenSeconds = $null
                           TokensPerSec = $null; TotalTokensPerSec = $null; TokensEstimated = $null
                           ResidentMB = $null }
        continue
    }

    $failure = $null
    $conversation = $null
    try { $conversation = Invoke-Conversation -Model $Identifier }
    catch { $failure = $_.Exception.Message; Write-Host "   la conversacion FALLA: $failure" -ForegroundColor Red }
    $resident = (Get-Process -Name "*llama*", "*lms*", "*LM Studio*" -ErrorAction SilentlyContinue |
                 Measure-Object WorkingSet64 -Sum).Sum

    $allTokens = 0; $allSeconds = 0.0
    $rateTokens = 0; $rateSeconds = 0.0
    $first = $null; $estimatedTokens = $false; $count = 0
    $toolOk = $false; $answered = $false
    if ($conversation) {
        foreach ($r in $conversation.Rounds) {
            $allTokens += $r.Tokens; $allSeconds += $r.TotalSeconds
            if ($r.Deltas -ge $MinDeltasForRate -and $r.GenerationSeconds -gt 0) {
                # The first token is what the wait before it produced: not part of the rate.
                $rateTokens += ($r.Tokens - 1); $rateSeconds += $r.GenerationSeconds
            }
            if ($r.TokensEstimated) { $estimatedTokens = $true }
        }
        $count = $conversation.Rounds.Count
        $first = $conversation.Rounds[0].FirstTokenSeconds
        $answered = $conversation.Answered
        if (-not $answered -and -not $failure) { $failure = $conversation.Note; Write-Host "   $failure" -ForegroundColor Yellow }
        # Herramientas usadas, todas validas y con respuesta final: es lo que exige la
        # guardia de evidencia, y el defecto intermitente se escapa midiendo una sola vez.
        $toolOk = ($conversation.ToolCallCount -gt 0) -and $conversation.ToolCallsValid -and $answered
    }
    [pscustomobject]@{
        Model = $model; Loaded = $true; Error = $failure
        EstimatedGiB = $estimated
        LoadSeconds = [math]::Round($loadWatch.Elapsed.TotalSeconds, 1)
        Rounds = $count; Answered = $answered; ToolCallsOk = $toolOk
        FirstTokenSeconds = $first
        TokensPerSec = if ($rateSeconds -gt 0) { [math]::Round($rateTokens / $rateSeconds, 2) } else { $null }
        TotalTokensPerSec = if ($allSeconds -gt 0) { [math]::Round($allTokens / $allSeconds, 2) } else { $null }
        TokensEstimated = $estimatedTokens
        RateTokens = $rateTokens
        RateSeconds = [math]::Round($rateSeconds, 3)
        ResidentMB = if ($resident) { [math]::Round($resident / 1MB, 0) } else { $null }
    }
}

# Solo el identificador de este banco.
if (Remove-Own) {
    Write-Host "AVISO: '$Identifier' sigue cargado tras el banco. Descargalo a mano con: lms unload $Identifier" -ForegroundColor Yellow
}

Write-Host "`n=== RESULTADO ===" -ForegroundColor Green
$results | Format-Table Model, Loaded, EstimatedGiB, FirstTokenSeconds, TokensPerSec, TotalTokensPerSec, Rounds, Answered, ToolCallsOk, ResidentMB -AutoSize

# Un modelo sin velocidad medible (ninguna ronda llego en trozos) puede ganar solo si no hay otro.
$winner = $results | Where-Object { $_.Loaded -and $_.ToolCallsOk } |
          Sort-Object @{ Expression = { if ($null -eq $_.TokensPerSec) { -1 } else { $_.TokensPerSec } }; Descending = $true } |
          Select-Object -First 1

if ($OutFile) { $results | ConvertTo-Json -Depth 5 | Set-Content -Path $OutFile -Encoding utf8
                Write-Host "Medicion guardada en $OutFile" }

if ($winner) {
    $speed = if ($null -eq $winner.TokensPerSec) {
        "velocidad no medible (ninguna ronda llego en al menos $MinDeltasForRate trozos; ordena ultimo)"
    } else { "$($winner.TokensPerSec) tok/s" }
    Write-Host "Ganador: $($winner.Model) - $speed, primer token en $($winner.FirstTokenSeconds) s, tool calling valido y respuesta final." -ForegroundColor Green
    Write-Host "Es el candidato local del router. Cargalo como 'cmh-local' con scripts/cmh_local/start.ps1 -Model '$($winner.Model)'."
    exit 0
}
Write-Host "NINGUN candidato pasa: sin tool calling valido y una respuesta final no sirve para un paso de flujo." -ForegroundColor Red
exit 1
