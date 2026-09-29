"""The record of one workflow run, read from the database, read-only (step 3.6).

Step 3.6 asks for, per step: the agent, the provider and model that answered, the
fallbacks, tokens in and out, seconds, the exit of every tool call and the size of
the artifact; plus who approved before the reviewer and when. It also asks for a
closing criterion measured, not narrated. This script computes all of it from the
run's rows and events so that the punto limpio quotes numbers, not impressions.

Read-only by construction: it opens the file with ``mode=ro``, imports neither
``core.database`` (which migrates whatever it is pointed at) nor anything that
does, and selects only the columns it reports. It never reads ``api_key``.

    python scripts/cmh_ops/run_report.py --latest
    python scripts/cmh_ops/run_report.py <run_id> --json
"""

import argparse
import importlib.util
import json
import pathlib
import sqlite3
import sys
from datetime import datetime
from urllib.parse import urlparse

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

#: The steps whose artifact is built from files, so a run that made no successful
#: tool call there did not look at anything (ADR-023). The definition decides per
#: step; this is the fallback when a frozen config predates the field.
DEFAULT_EVIDENCE = {"investigador", "constructor", "verificador"}


def _seed_module():
    """The seed script owns the rule for where the live database is. Importing it
    is safe: it imports nothing from the application at module level."""
    spec = importlib.util.spec_from_file_location("cmh_seed_agents_for_report",
                                                  REPO / "scripts" / "cmh_seed_agents.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse(value):
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _seconds(start, finish):
    a, b = _parse(start), _parse(finish)
    return round((b - a).total_seconds(), 1) if a and b else None


def _json(text, default):
    try:
        return json.loads(text) if text else default
    except ValueError:
        return default


def latest_run_id(con):
    row = con.execute("SELECT id FROM cmh_workflow_runs "
                      "ORDER BY COALESCE(started_at, created_at) DESC LIMIT 1").fetchone()
    return row[0] if row else None


def build_report(con, run_id: str) -> dict:
    """Everything step 3.6 asks to record, and the closing criterion evaluated."""
    from src.cmh_cost_policy import is_zero_cost_endpoint

    run = con.execute("SELECT id, status, definition_id, project_id, started_at, finished_at "
                      "FROM cmh_workflow_runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        raise LookupError(f"No hay una ejecucion con id {run_id}")
    endpoints = {r[0]: {"base_url": r[1], "endpoint_kind": r[2]} for r in con.execute(
        "SELECT id, base_url, endpoint_kind FROM model_endpoints")}
    agents = {r[0]: r[1] for r in con.execute("SELECT id, name FROM cmh_agents")}
    artifacts = {r[0]: {"model": r[1], "chars": r[2]} for r in con.execute(
        "SELECT step_key, model, LENGTH(content) FROM cmh_workflow_artifacts WHERE run_id = ?",
        (run_id,))}
    events = {}
    for step_key, kind, payload in con.execute(
            "SELECT step_key, kind, payload FROM cmh_workflow_events WHERE run_id = ? "
            "ORDER BY seq", (run_id,)):
        events.setdefault(step_key, []).append((kind, _json(payload, {})))

    steps, paid = [], []
    for row in con.execute(
            "SELECT step_key, agent_id, status, config, started_at, finished_at, error, decision "
            "FROM cmh_workflow_steps WHERE run_id = ? ORDER BY COALESCE(started_at, ?)",
            (run_id, "9999")):
        key, agent_id, status, config_text, started, finished, error, decision = row
        config = _json(config_text, {})
        step_events = events.get(key, [])
        endpoint_id = config.get("resolved_endpoint_id")
        endpoint = endpoints.get(endpoint_id) or {}
        model = config.get("resolved_model") or config.get("model")
        host = urlparse(endpoint.get("base_url") or "").hostname
        tools = [{"tool": p.get("tool"), "exit_code": p.get("exit_code"),
                  "error": p.get("error"), "seconds": p.get("duration_seconds")}
                 for kind, p in step_events if kind == "tool_finished"]
        tokens_in = tokens_out = 0
        for kind, p in step_events:
            if kind == "model_metrics":
                metrics = p.get("metrics") or {}
                tokens_in += int(metrics.get("input_tokens") or 0)
                tokens_out += int(metrics.get("output_tokens") or 0)
        completed = next((p for kind, p in step_events if kind == "step_completed"), {})
        fallbacks = [{"from": p.get("from"), "to": p.get("to"), "reason": p.get("reason")}
                     for kind, p in step_events if kind == "provider_fallback"]
        blocked = [{"endpoint_url": p.get("endpoint_url"), "model": p.get("candidate_model")}
                   for kind, p in step_events if kind == "zero_cost_blocked"]
        if endpoint and not is_zero_cost_endpoint(endpoint, model):
            paid.append(key)
        needs_evidence = config.get("require_tool_evidence")
        needs_evidence = (key in DEFAULT_EVIDENCE) if needs_evidence is None else bool(needs_evidence)
        steps.append({
            "key": key, "agent": agents.get(agent_id, agent_id), "status": status,
            "model": model, "endpoint_id": endpoint_id, "host": host,
            "fallbacks": [f for f in fallbacks if not str(f["reason"]).startswith("quota:")],
            "quota_skips": [f for f in fallbacks if str(f["reason"]).startswith("quota:")],
            "zero_cost_blocked": blocked,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "seconds": completed.get("duration_seconds") or _seconds(started, finished),
            "tools": tools,
            "artifact_chars": artifacts.get(key, {}).get("chars"),
            "artifact_model": artifacts.get(key, {}).get("model"),
            "requires_evidence": needs_evidence,
            "requires_approval": bool(config.get("requires_approval")),
            "decision": _json(decision, None), "error": error,
        })

    discovery = [p for p in (pl for kind, pl in events.get(None, []) if kind == "provider_discovery")]
    evidence = {s["key"]: any(t["exit_code"] in (None, 0) and not t["error"] for t in s["tools"])
                for s in steps if s["requires_evidence"]}
    approvals = {s["key"]: s["decision"] for s in steps if s["requires_approval"]}
    criteria = {
        "run_completed": run[1] == "completed",
        "five_artifacts": len(artifacts) == 5,
        "no_step_in_error": not any(s["status"] == "error" for s in steps),
        "evidence": evidence,
        "evidence_satisfied": all(evidence.values()) if evidence else False,
        "human_approval": approvals,
        "human_approval_recorded": all(bool(d) and d.get("outcome") == "approved"
                                       and d.get("by") and d.get("at")
                                       for d in approvals.values()) if approvals else True,
        "steps_on_a_route_that_fails_the_gate": paid,
        "zero_cost_blocked_events": sum(len(s["zero_cost_blocked"]) for s in steps),
    }
    criteria["all_met"] = bool(
        criteria["run_completed"] and criteria["five_artifacts"]
        and criteria["no_step_in_error"] and criteria["evidence_satisfied"]
        and criteria["human_approval_recorded"] and not paid)
    return {
        "run": {"id": run[0], "status": run[1], "definition_id": run[2], "project_id": run[3],
                "started_at": run[4], "finished_at": run[5], "seconds": _seconds(run[4], run[5])},
        "steps": steps, "discovery": discovery, "criteria": criteria,
    }


def render(report: dict) -> str:
    run, crit = report["run"], report["criteria"]
    lines = [f"Ejecucion {run['id']} - estado {run['status']} - {run['seconds']} s",
             f"Definicion {run['definition_id']} - proyecto {run['project_id']}", ""]
    for d in report["discovery"]:
        lines.append(f"descubrimiento {d.get('provider')}: {d.get('outcome')} "
                     f"modelo={d.get('model')} via={d.get('source')} motivo={d.get('reason')}")
    if report["discovery"]:
        lines.append("")
    for s in report["steps"]:
        lines.append(f"[{s['key']}] {s['agent']} - {s['status']} - {s['seconds']} s")
        lines.append(f"    proveedor {s['host']} ({s['endpoint_id']}) modelo {s['model']}; "
                     f"artefacto escrito por {s['artifact_model']}, {s['artifact_chars']} caracteres")
        lines.append(f"    tokens entrada {s['tokens_in']} / salida {s['tokens_out']}")
        for f in s["fallbacks"]:
            lines.append(f"    fallback {f['from']} -> {f['to']}: {f['reason']}")
        for f in s["quota_skips"]:
            lines.append(f"    salto por cuota {f['from']}: {f['reason']}")
        for b in s["zero_cost_blocked"]:
            lines.append(f"    BLOQUEADO por costo cero: {b['endpoint_url']} modelo {b['model']}")
        exits = ", ".join(f"{t['tool']}={t['exit_code']}" for t in s["tools"]) or "sin herramientas"
        lines.append(f"    herramientas: {exits}")
        if s["decision"]:
            d = s["decision"]
            lines.append(f"    decision humana: {d.get('outcome')} por {d.get('by')} el {d.get('at')}")
        if s["error"]:
            lines.append(f"    ERROR: {s['error']}")
    lines += ["", "CRITERIO DE CIERRE DE LA FASE 1",
              f"  run completed .............. {crit['run_completed']}",
              f"  5 artefactos ............... {crit['five_artifacts']}",
              f"  ningun paso en error ....... {crit['no_step_in_error']}",
              f"  evidencia de herramientas .. {crit['evidence_satisfied']}  {crit['evidence']}",
              f"  aprobacion humana registrada {crit['human_approval_recorded']}",
              f"  pasos en ruta que no pasa la compuerta: {crit['steps_on_a_route_that_fails_the_gate'] or 'ninguno'}",
              f"  eventos zero_cost_blocked .. {crit['zero_cost_blocked_events']} (cada uno se explica)",
              f"  TODO CUMPLIDO .............. {crit['all_met']}",
              "  (marca synthetic: un texto escrito por Odysseus falla el paso y no se guarda como "
              "artefacto; un run completed no puede contener uno)"]
    return "\n".join(lines)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("run_id", nargs="?")
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--db", default=None, help="path of app.db (default: the live one)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not args.run_id and not args.latest:
        parser.error("indica un run_id o --latest")
    db_path = pathlib.Path(args.db) if args.db else _seed_module().live_database_path()
    if not db_path.is_file():
        print(f"No existe la base {db_path}")
        return 2
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        run_id = args.run_id or latest_run_id(con)
        if not run_id:
            print("No hay ejecuciones en la base.")
            return 1
        report = build_report(con, run_id)
    except LookupError as exc:
        print(exc)
        return 1
    finally:
        con.close()
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render(report))
    return 0 if report["criteria"]["all_met"] else 3


if __name__ == "__main__":
    sys.exit(main())
