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
     '        t["exit_code"] in (None, 0) and not t["error"] for t in by_key[role]["tools"])',
     '        True for t in by_key[role]["tools"])',
     [f"{REPORT}::test_each_way_of_failing_the_criterion_is_seen"]),
    ("RR06 una aprobacion rechazada cuenta como registrada", SCRIPT,
     '        if d.get("outcome") != "approved":\n            return "sin decision aprobada"',
     '        if False:\n            return "sin decision aprobada"',
     [f"{REPORT}::test_each_way_of_failing_the_criterion_is_seen"]),
    ("RR07 el informe deja de comprobar la ruta contra la compuerta de costo", SCRIPT,
     '            if not is_zero_cost_endpoint(route, model):',
     '            if False:',
     [f"{REPORT}::test_a_step_on_a_route_the_cost_gate_refuses_fails_the_criterion"]),
    ("RR08 los cinco artefactos se dan por cumplidos siempre", SCRIPT,
     '"five_artifacts": len(artifacts) == 5,',
     '"five_artifacts": True,',
     [f"{REPORT}::test_each_way_of_failing_the_criterion_is_seen"]),
    ("RR09 el informe abre la base para escritura", SCRIPT,
     '    try:\n        con = sqlite3.connect(uri, uri=True)',
     '    try:\n        con = sqlite3.connect(str(db_path))',
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

    # --- added on 2026-09-29 after the independent review of revision-fase1-r6 ------
    ("RR13 la ruta se juzga por la fila de hoy y no por la URL congelada", SCRIPT,
     '    url = frozen.get("endpoint_url") or row.get("base_url") or (',
     '    url = row.get("base_url") or frozen.get("endpoint_url") or (',
     [f"{REPORT}::test_the_url_frozen_at_run_creation_decides_not_the_row_as_it_is_today"]),
    ("RR14 una ruta que no se pudo resolver se da por verificada", SCRIPT,
     '        elif status == "completed":\n            unverifiable.append(key)',
     '        elif status == "completed":\n            pass',
     [f"{REPORT}::test_a_route_that_cannot_be_resolved_is_unverifiable_and_fails_the_criterion"]),
    ("RR15 el criterio ignora las rutas que no se pudieron verificar", SCRIPT,
     'and criteria["human_approval_recorded"] and not paid and not unverifiable)',
     'and criteria["human_approval_recorded"] and not paid)',
     [f"{REPORT}::test_a_route_that_cannot_be_resolved_is_unverifiable_and_fails_the_criterion"]),
    ("RR16 un id que es una URL deja de leerse como ruta", SCRIPT,
     '        resolved if "://" in str(resolved) else None)',
     '        None)',
     [f"{REPORT}::test_an_id_that_is_itself_a_url_is_judged_as_that_url"]),
    ("RR17 sin ninguna compuerta la aprobacion se da por registrada", SCRIPT,
     '    if not gated:\n        approval_note = "ningun paso exige aprobacion humana"',
     '    if not gated:\n        approval_note = None',
     [f"{REPORT}::test_a_run_with_no_approval_gate_does_not_pass_the_approval_criterion"]),
    ("RR18 la compuerta puede estar en cualquier paso, no en el revisor", SCRIPT,
     "    elif REVIEW_STEP not in gated:",
     "    elif False:",
     [f"{REPORT}::test_the_gate_has_to_be_on_the_reviewer"]),
    ("RR19 una aprobacion posterior al inicio del paso se acepta", SCRIPT,
     "        if at > started:",
     "        if False:",
     [f"{REPORT}::test_an_approval_needs_who_when_and_to_come_first"]),
    ("RR20 una aprobacion sin autor se acepta", SCRIPT,
     '        if not d.get("by"):\n            return "sin autor"',
     '        if False:\n            return "sin autor"',
     [f"{REPORT}::test_an_approval_needs_who_when_and_to_come_first"]),
    ("RR21 una aprobacion sin fecha se acepta", SCRIPT,
     '        if at is None:\n            return "sin fecha"',
     '        if at is None:\n            return None',
     [f"{REPORT}::test_an_approval_needs_who_when_and_to_come_first"]),
    ("RR22 la hora de la aprobacion no se lleva a UTC", SCRIPT,
     "        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)",
     "        moment = moment.replace(tzinfo=None)",
     [f"{REPORT}::test_the_approval_time_is_compared_in_utc_whatever_offset_it_was_written_with"]),
    ("RR23 la evidencia se mide solo donde el config del paso la pide", SCRIPT,
     '        t["exit_code"] in (None, 0) and not t["error"] for t in by_key[role]["tools"])\n'
     "        for role in EVIDENCE_ROLES}",
     '        t["exit_code"] in (None, 0) and not t["error"] for t in by_key[role]["tools"])\n'
     '        for role in EVIDENCE_ROLES if by_key.get(role) and by_key[role]["requires_evidence"]}',
     [f"{REPORT}::test_the_evidence_criterion_covers_the_three_roles_even_if_a_config_switched_it_off"]),
    ("RR24 un rol de evidencia ausente se da por cumplido", SCRIPT,
     "    evidence = {role: bool(by_key.get(role)) and any(",
     "    evidence = {role: (not by_key.get(role)) or any(",
     [f"{REPORT}::test_a_missing_evidence_role_is_not_satisfied"]),
    ("RR25 un paso sin metricas se informa con tokens 0 / 0", SCRIPT,
     '    if not step["tokens_reported"]:',
     "    if False:",
     [f"{REPORT}::test_tokens_say_where_they_come_from_and_a_step_without_metrics_says_it_has_none"]),
    ("RR26 el origen de los tokens mezclado se informa como el primero", SCRIPT,
     '                        else sources[0] if len(set(sources)) == 1 else "mixed")',
     "                        else sources[0])",
     [f"{REPORT}::test_tokens_say_where_they_come_from_and_a_step_without_metrics_says_it_has_none"]),
    ("RR27 el evento de costo cero se imprime con su URL cruda", SCRIPT,
     '        blocked = [{"endpoint_url": _scheme_host(p.get("endpoint_url")),',
     '        blocked = [{"endpoint_url": p.get("endpoint_url"),',
     [f"{REPORT}::test_a_blocked_url_is_reported_as_scheme_and_host_only"]),
    ("RR28 la URI de la base se arma sin escapar la ruta", SCRIPT,
     '    uri = f"{db_path.resolve().as_uri()}?mode=ro"',
     '    uri = f"file:{db_path.as_posix()}?mode=ro"',
     [f"{REPORT}::test_a_path_with_a_hash_and_a_space_is_still_opened_read_only"]),
    ("RR29 un archivo que no es una base se sigue leyendo con traza", SCRIPT,
     '    except sqlite3.Error as exc:\n        print(f"La base {db_path} no se pudo leer: {exc}")',
     '    except KeyError as exc:\n        print(f"La base {db_path} no se pudo leer: {exc}")',
     [f"{REPORT}::test_a_file_that_is_not_a_database_is_reported_and_not_a_traceback"]),
    ("RR30 un paso sin evento de cierre pierde sus segundos", SCRIPT,
     '            "seconds": completed.get("duration_seconds") or _seconds(started, finished),',
     '            "seconds": completed.get("duration_seconds"),',
     [f"{REPORT}::test_the_seconds_of_the_run_and_of_a_step_without_a_completion_event"]),
    ("RR31 la ejecucion pierde sus segundos", SCRIPT,
     '"started_at": run[4], "finished_at": run[5], "seconds": _seconds(run[4], run[5])},',
     '"started_at": run[4], "finished_at": run[5], "seconds": None},',
     [f"{REPORT}::test_the_seconds_of_the_run_and_of_a_step_without_a_completion_event"]),
    ("RR32 un paso en error no cuenta para el criterio", SCRIPT,
     '        "no_step_in_error": not any(s["status"] == "error" for s in steps),',
     '        "no_step_in_error": True,',
     [f"{REPORT}::test_each_way_of_failing_the_criterion_is_seen"]),
]


if __name__ == "__main__":
    sys.exit(campaign(MUTANTS, REPO, PY))
