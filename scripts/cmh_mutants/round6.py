"""Mutants for step 3.4: the local bench and preload scripts (PowerShell 5.1).

Each mutant names the ONE test that must fall, by node id, so a campaign of 15
runs takes a minute or two instead of the two minutes each full pass of the module
costs. The test that is named is the one that claims to pin the behaviour; the
final pass runs the whole module once.

Run it against an EXPORT of a commit, never the live tree. The runner refuses a
directory that contains .git (see _target.py).

    git archive <commit> | tar -x -C /tmp/export
    CMH_MUTANT_REPO=/tmp/export python scripts/cmh_mutants/round6.py
"""

import pathlib
import sys

from _target import resolve_repo
from _target import campaign

REPO = resolve_repo(pathlib.Path(__file__).resolve().parents[2])
PY = pathlib.Path(sys.executable)
if not PY.exists() or "python" not in PY.name.lower():
    PY = REPO.parent.parent / ".venv" / "Scripts" / "python.exe"

MODULE = "tests/test_cmh_local_scripts.py"


def only(name):
    return [f"{MODULE}::{name}"]


BENCH = "scripts/cmh_local/bench.ps1"
START = "scripts/cmh_local/start.ps1"

RUNS_UNDER_PS51 = only("test_the_bench_runs_under_windows_powershell_51_and_measures_a_real_tool_loop")

#: (name, file, text to replace, replacement, test node ids that must fall)
MUTANTS = [
    # --- bench.ps1 --------------------------------------------------------------
    ("B01 lms se llama con ErrorActionPreference=Stop: el stderr aborta el guion", BENCH,
     '    $ErrorActionPreference = "Continue"\n    try {',
     '    $ErrorActionPreference = "Stop"\n    try {',
     RUNS_UNDER_PS51),
    ("B02 el resultado de la herramienta no vuelve al modelo", BENCH,
     '            $messages += @{ role = "tool"; tool_call_id = $call.Id; content = (Invoke-Tool -Name $call.Name -Path $path) }',
     '            $null = $call',
     only("test_the_tool_is_executed_and_its_result_goes_back_to_the_model")),
    ("B03 el primer token no se mide", BENCH,
     '            if (($hasText -or $hasCall) -and $null -eq $first) { $first = $watch.Elapsed.TotalSeconds }',
     '            if ($false) { $first = $watch.Elapsed.TotalSeconds }',
     RUNS_UNDER_PS51),
    ("B04 tok/s se calcula sobre el tiempo total y no el de generacion", BENCH,
     '            $tokens += $r.Tokens; $seconds += $r.GenerationSeconds',
     '            $tokens += $r.Tokens; $seconds += $r.TotalSeconds',
     RUNS_UNDER_PS51),
    ("B05 entre candidatos descarga todo, no solo lo que cargo", BENCH,
     '    [void](Invoke-Lms @("unload", $Identifier))\n    $loadWatch = ',
     '    [void](Invoke-Lms @("unload", "--all"))\n    $loadWatch = ',
     only("test_between_candidates_it_unloads_only_what_it_loaded_itself")),
    ("B06 descarga lo que el usuario tiene cargado sin -UnloadOthers", BENCH,
     '    if (-not $UnloadOthers) {',
     '    if ($false) {',
     only("test_it_refuses_to_unload_what_the_user_has_loaded")),
    ("B07 sin -Models mide todo el disco", BENCH,
     '} elseif ($All) {',
     '} elseif ($true) {',
     only("test_by_default_it_measures_the_three_blueprint_candidates_not_the_whole_disk")),
    ("B08 una llamada con argumentos que no son JSON se da por valida", BENCH,
     '            if (-not $call.Name -or -not ($call.Name -in @("ls", "read_file")) -or -not $path) { $valid = $false }',
     '            if ($false) { $valid = $false }',
     only("test_a_tool_call_whose_arguments_are_not_json_is_not_valid")),
    ("B09 un modelo que nunca llamo una herramienta cuenta como valido", BENCH,
     '        $toolOk = ($conversation.ToolCallCount -gt 0) -and $conversation.ToolCallsValid -and $answered',
     '        $toolOk = $conversation.ToolCallsValid -and $answered',
     only("test_a_model_that_never_calls_a_tool_is_not_a_winner")),
    ("B10 los candidatos por defecto ya no son los tres del blueprint", BENCH,
     '$Candidates = @("gemma-4-e4b", "qwen3.5-4b", "phi-4-mini")',
     '$Candidates = @("gemma-4-e4b", "qwen3.5-4b", "phi-4-mini", "gpt-oss")',
     only("test_by_default_it_measures_the_three_blueprint_candidates_not_the_whole_disk")),
    ("B11 la carga pasa un TTL y el modelo se descarga solo", BENCH,
     '"--identifier", $Identifier, "-y")',
     '"--identifier", $Identifier, "--ttl", "60", "-y")',
     only("test_the_offload_context_and_identifier_are_passed_and_ttl_never_is")),
    ("B12 el offload pedido se ignora", BENCH,
     '"--gpu", $Gpu, "-c", "$ContextLength", "--identifier", $Identifier, "-y")',
     '"--gpu", "max", "-c", "$ContextLength", "--identifier", $Identifier, "-y")',
     only("test_the_offload_context_and_identifier_are_passed_and_ttl_never_is")),

    # --- start.ps1 --------------------------------------------------------------
    ("S01 con un solo modelo cargado no descarga nada", START,
     '$others.Count -gt 0',
     '$others.Count -gt 1',
     only("test_start_unloads_a_single_loaded_model_before_loading")),
    ("S02 la carga pasa un TTL y el modelo se descarga solo", START,
     '"--identifier", $Identifier, "-y")',
     '"--identifier", $Identifier, "--ttl", "60", "-y")',
     only("test_start_loads_with_offload_context_and_identifier_and_without_a_ttl")),
    ("S03 vuelve a cargar aunque ya este cargado", START,
     '$loaded -contains $Identifier',
     '$false',
     only("test_start_does_nothing_when_the_identifier_is_already_loaded")),
    ("S04 lms se llama con ErrorActionPreference=Stop: el stderr aborta el guion", START,
     '    $ErrorActionPreference = "Continue"\n    try {',
     '    $ErrorActionPreference = "Stop"\n    try {',
     only("test_start_does_not_unload_when_nothing_is_loaded")),
    ("S05 sigue adelante aunque LM Studio no responda", START,
     'catch { throw "LM Studio no responde',
     'catch { Write-Host "LM Studio no responde',
     only("test_start_stops_cleanly_when_lm_studio_does_not_answer")),
]


if __name__ == "__main__":
    sys.exit(campaign(MUTANTS, REPO, PY))
