"""Mutants for step 3.6 (preparation): the run record and the two event fields it needs.

Each mutant names the ONE test that must fall, by node id.

Run it against an EXPORT of a commit, never the live tree. The runner refuses a
directory that contains .git (see _target.py).

    git archive <commit> | tar -x -C /tmp/export
    CMH_MUTANT_REPO=/tmp/export python scripts/cmh_mutants/round8.py
"""

import pathlib
import sys

from _target import resolve_repo
from _target import campaign

REPO = resolve_repo(pathlib.Path(__file__).resolve().parents[2])
PY = pathlib.Path(sys.executable)
if not PY.exists() or "python" not in PY.name.lower():
    PY = REPO.parent.parent / ".venv" / "Scripts" / "python.exe"

REPORT = "tests/test_cmh_run_report.py"
SCHED = "src/task_scheduler.py"
FLOW = "src/cmh_workflows.py"
SCRIPT = "scripts/cmh_ops/run_report.py"

#: (name, file, text to replace, replacement, test node ids that must fall)
MUTANTS = [
    ("RR01 tool_finished deja de llevar el exit_code numerico", SCHED,
     '                                   exit_code=observed.get("exit_code"),\n',
     '',
     ["tests/test_cmh_restricted_loop.py::test_tool_finished_carries_the_numeric_exit_code"]),
    ("RR02 step_completed deja de llevar el tamano del artefacto", FLOW,
     '                  artifact_chars=len(output),\n',
     '',
     ["tests/test_cmh_workflows.py::test_step_completed_records_the_size_of_the_artifact"]),
    ("RR03 los tokens de un paso no se suman entre intentos", SCRIPT,
     '                tokens_in += int(metrics.get("input_tokens") or 0)',
     '                tokens_in = int(metrics.get("input_tokens") or 0)',
     [f"{REPORT}::test_the_record_has_what_step_36_asks_for_per_step"]),
    ("RR04 un salto por cuota se cuenta como fallback", SCRIPT,
     '"fallbacks": [f for f in fallbacks if not str(f["reason"]).startswith("quota:")],',
     '"fallbacks": [f for f in fallbacks],',
     [f"{REPORT}::test_the_record_has_what_step_36_asks_for_per_step"]),
    ("RR05 cualquier llamada a herramienta cuenta como evidencia, aunque fallara", SCRIPT,
     'evidence = {s["key"]: any(t["exit_code"] in (None, 0) and not t["error"] for t in s["tools"])',
     'evidence = {s["key"]: any(True for t in s["tools"])',
     [f"{REPORT}::test_each_way_of_failing_the_criterion_is_seen"]),
    ("RR06 una aprobacion rechazada cuenta como registrada", SCRIPT,
     '"human_approval_recorded": all(bool(d) and d.get("outcome") == "approved"\n'
     '                                       and d.get("by") and d.get("at")',
     '"human_approval_recorded": all(bool(d) and d.get("by") and d.get("at")',
     [f"{REPORT}::test_each_way_of_failing_the_criterion_is_seen"]),
    ("RR07 el informe deja de comprobar la ruta contra la compuerta de costo", SCRIPT,
     '        if endpoint and not is_zero_cost_endpoint(endpoint, model):',
     '        if False:',
     [f"{REPORT}::test_a_step_on_a_route_the_cost_gate_refuses_fails_the_criterion"]),
    ("RR08 los cinco artefactos se dan por cumplidos siempre", SCRIPT,
     '"five_artifacts": len(artifacts) == 5,',
     '"five_artifacts": True,',
     [f"{REPORT}::test_each_way_of_failing_the_criterion_is_seen"]),
    ("RR09 el informe abre la base para escritura", SCRIPT,
     '    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)',
     '    con = sqlite3.connect(str(db_path))',
     [f"{REPORT}::test_the_command_opens_the_database_read_only"]),
    ("RR10 --latest elige la ejecucion mas antigua", SCRIPT,
     'ORDER BY COALESCE(started_at, created_at) DESC LIMIT 1',
     'ORDER BY COALESCE(started_at, created_at) ASC LIMIT 1',
     [f"{REPORT}::test_latest_picks_the_most_recent_run"]),
    ("RR11 el codigo de salida no distingue un criterio incumplido", SCRIPT,
     '    return 0 if report["criteria"]["all_met"] else 3',
     '    return 0',
     [f"{REPORT}::test_the_command_reports_and_signals_with_its_exit_code"]),
    ("RR12 el informe empieza a leer la clave de los endpoints", SCRIPT,
     '"SELECT id, base_url, endpoint_kind FROM model_endpoints"',
     '"SELECT id, base_url, endpoint_kind, api_key FROM model_endpoints"',
     [f"{REPORT}::test_the_report_is_read_only_and_never_selects_the_key"]),
]


if __name__ == "__main__":
    sys.exit(campaign(MUTANTS, REPO, PY))
