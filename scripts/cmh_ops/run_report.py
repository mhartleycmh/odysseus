"""The record of one workflow run, read from the database, read-only (step 3.6).

Step 3.6 asks for, per step: the agent, the provider and model that answered, the
fallbacks, tokens in and out, seconds, the exit of every tool call and the size of
the artifact; plus who approved before the reviewer and when. It also asks for a
closing criterion measured, not narrated. This script computes all of it from the
run's rows and events so that the punto limpio quotes numbers, not impressions.

Read-only by construction: it opens the file with ``mode=ro``, imports neither
``core.database`` (which migrates whatever it is pointed at) nor anything that
does, and selects only the columns it reports. It never reads ``api_key``.

An empty list never means "verified" here. A step whose route cannot be resolved is
listed as unverifiable and fails the criterion; a run with no approval gate fails the
approval criterion instead of passing it for having nothing to check.

    python scripts/cmh_ops/run_report.py --latest
    python scripts/cmh_ops/run_report.py <run_id> --json
"""

import argparse
import importlib.util
import json
import pathlib
import re
import sqlite3
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

#: The three roles whose artifact is built from files, so a run that made no
#: successful tool call there did not look at anything (ADR-023, blueprint 18). They
#: are required WHATEVER the frozen config of each step says: the config decides
#: whether the engine enforces it, not whether the phase's criterion asks for it.
EVIDENCE_ROLES = ("investigador", "constructor", "verificador")
DEFAULT_EVIDENCE = set(EVIDENCE_ROLES)

#: The step a human must approve before it starts (blueprint 18).
REVIEW_STEP = "revisor"


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


def _utc(value):
    """A naive UTC datetime from an ISO string with or without ``Z`` or an offset.

    The engine stores step times naive (UTC) and the approval decision with a ``Z``;
    comparing the two as they are raises, or worse, compares different clocks.
    """
    moment = _parse(str(value).replace("Z", "+00:00") if value else value)
    if moment is not None and moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def _seconds(start, finish):
    a, b = _parse(start), _parse(finish)
    return round((b - a).total_seconds(), 1) if a and b else None


def _json(text, default):
    try:
        return json.loads(text) if text else default
    except ValueError:
        return default


def _scheme_host(url):
    """``scheme://host`` of a URL, and nothing else: no credentials, path or query."""
    try:
        parts = urlparse(url or "")
        return f"{parts.scheme}://{parts.hostname}" if parts.hostname else "URL sin host"
    except ValueError:
        return "URL no interpretable"


def _shown(value):
    """An endpoint id as the report shows it: one that is itself a URL (a run frozen before
    the rows carried ids) is cut to scheme://host, credentials and all."""
    return _scheme_host(value) if isinstance(value, str) and "://" in value else value


_URL_IN_TEXT = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"<>)]+")


def _without_url_credentials(text):
    """A step's error message may quote the URL that failed, userinfo included. Those URLs are
    cut to scheme://host; every other word, and every URL without credentials, is kept."""
    if not isinstance(text, str):
        return text

    def cut(match):
        url = match.group(0)
        authority = url.split("://", 1)[1].split("/", 1)[0]
        return _scheme_host(url) if "@" in authority else url

    return _URL_IN_TEXT.sub(cut, text)


def latest_run_id(con):
    row = con.execute("SELECT id FROM cmh_workflow_runs "
                      "ORDER BY COALESCE(started_at, created_at) DESC LIMIT 1").fetchone()
    return row[0] if row else None


def _route(config, endpoints):
    """The route a step actually called, as the cost gate judges it, or None.

    Judged by the URL the run FROZE for that candidate, not by the registered row as
    it is today: a row repointed after the run must not change the verdict on what
    the run did. Falls back to the row's current URL, then to the id when the id is
    itself a URL (a run frozen before rows carried ids). Only the ``endpoint_kind``
    comes from the current row; the frozen candidate does not record it.
    """
    resolved = config.get("resolved_endpoint_id")
    if not resolved:
        return None
    frozen = next((c for c in (config.get("candidates") or [])
                   if isinstance(c, dict) and c.get("endpoint_id") == resolved), None) or {}
    row = endpoints.get(resolved) or {}
    url = frozen.get("endpoint_url") or row.get("base_url") or (
        resolved if "://" in str(resolved) else None)
    if not url:
        return None
    return {"id": resolved, "base_url": url, "endpoint_kind": row.get("endpoint_kind") or "auto"}


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

    steps, paid, unverifiable = [], [], []
    for row in con.execute(
            "SELECT step_key, agent_id, status, config, started_at, finished_at, error, decision "
            "FROM cmh_workflow_steps WHERE run_id = ? ORDER BY COALESCE(started_at, ?)",
            (run_id, "9999")):
        key, agent_id, status, config_text, started, finished, error, decision = row
        config = _json(config_text, {})
        step_events = events.get(key, [])
        route = _route(config, endpoints)
        endpoint_id = config.get("resolved_endpoint_id")
        model = config.get("resolved_model") or config.get("model")
        host = urlparse(route["base_url"]).hostname if route else None
        tools = [{"tool": p.get("tool"), "exit_code": p.get("exit_code"),
                  "error": p.get("error"), "seconds": p.get("duration_seconds")}
                 for kind, p in step_events if kind == "tool_finished"]
        tokens_in = tokens_out = 0
        tokens_reported, sources = False, []
        for kind, p in step_events:
            if kind == "model_metrics":
                metrics = p.get("metrics") or {}
                tokens_reported = True
                tokens_in += int(metrics.get("input_tokens") or 0)
                tokens_out += int(metrics.get("output_tokens") or 0)
                if metrics.get("usage_source"):
                    sources.append(metrics["usage_source"])
        usage_source = (None if not sources
                        else sources[0] if len(set(sources)) == 1 else "mixed")
        completed = next((p for kind, p in step_events if kind == "step_completed"), {})
        fallbacks = [{"from": _shown(p.get("from")), "to": _shown(p.get("to")),
                      "reason": p.get("reason")}
                     for kind, p in step_events if kind == "provider_fallback"]
        blocked = [{"endpoint_url": _scheme_host(p.get("endpoint_url")),
                    "model": p.get("candidate_model")}
                   for kind, p in step_events if kind == "zero_cost_blocked"]
        if route is not None:
            if not is_zero_cost_endpoint(route, model):
                paid.append(key)
        elif status == "completed":
            unverifiable.append(key)
        declared = config.get("require_tool_evidence")
        needs_evidence = (key in DEFAULT_EVIDENCE) if declared is None else bool(declared)
        shown_id = _shown(endpoint_id)
        steps.append({
            "key": key, "agent": agents.get(agent_id, agent_id), "status": status,
            "model": model, "endpoint_id": shown_id, "host": host,
            "fallbacks": [f for f in fallbacks if not str(f["reason"]).startswith("quota:")],
            "quota_skips": [f for f in fallbacks if str(f["reason"]).startswith("quota:")],
            "zero_cost_blocked": blocked,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "tokens_reported": tokens_reported, "usage_source": usage_source,
            "seconds": completed.get("duration_seconds") or _seconds(started, finished),
            "started_at": started,
            "tools": tools,
            "artifact_chars": artifacts.get(key, {}).get("chars"),
            "artifact_model": artifacts.get(key, {}).get("model"),
            "requires_evidence": needs_evidence,
            "requires_approval": bool(config.get("requires_approval")),
            "decision": _json(decision, None), "error": _without_url_credentials(error),
        })

    discovery = [p for p in (pl for kind, pl in events.get(None, []) if kind == "provider_discovery")]

    # Evidence: the three roles the blueprint names, always. A role missing from the
    # run counts as NOT satisfied, and a step whose config switched the requirement
    # off is listed, not trusted.
    by_key = {s["key"]: s for s in steps}
    evidence = {role: bool(by_key.get(role)) and any(
        t["exit_code"] in (None, 0) and not t["error"] for t in by_key[role]["tools"])
        for role in EVIDENCE_ROLES}
    evidence_off_in_config = [role for role in EVIDENCE_ROLES
                              if role in by_key and not by_key[role]["requires_evidence"]]

    # Approval: the reviewer must be gated, and every gated step must carry an
    # approved decision with a who, and a when that is not after the step started
    # (the engine sets started_at only once the approval has been given) and not before the
    # RUN started (an approval dated 1999 is not one given in this run).
    gated = {s["key"]: s for s in steps if s["requires_approval"]}
    approvals = {key: s["decision"] for key, s in gated.items()}

    run_started = _utc(run[4])

    def _problem(step):
        d = step["decision"] or {}
        if d.get("outcome") != "approved":
            return "sin decision aprobada"
        if not d.get("by"):
            return "sin autor"
        at, started = _utc(d.get("at")), _utc(step["started_at"])
        if at is None:
            return "sin fecha"
        if started is None:
            return "el paso no tiene hora de inicio"
        if at > started:
            return "la aprobacion es posterior al inicio del paso"
        if run_started is None:
            return "la ejecucion no tiene hora de inicio"
        if at < run_started:
            # An approval dated 1999 or 1970 is not one given in this run. The engine cannot
            # write such a date (it stamps the moment of approval), so it means the database
            # was altered, or the clock was wrong.
            return "la aprobacion es anterior al inicio de la ejecucion"
        return None

    if not gated:
        approval_note = "ningun paso exige aprobacion humana"
    elif REVIEW_STEP not in gated:
        approval_note = f"el paso {REVIEW_STEP} no exige aprobacion"
    else:
        problems = {key: _problem(s) for key, s in gated.items() if _problem(s)}
        approval_note = "; ".join(f"{key}: {why}" for key, why in problems.items()) or None
    approval_ok = approval_note is None

    criteria = {
        "run_completed": run[1] == "completed",
        "five_artifacts": len(artifacts) == 5,
        "no_step_in_error": not any(s["status"] == "error" for s in steps),
        "evidence": evidence,
        "evidence_satisfied": all(evidence.values()),
        "evidence_off_in_config": evidence_off_in_config,
        "human_approval": approvals,
        "human_approval_recorded": approval_ok,
        "human_approval_note": approval_note,
        "steps_on_a_route_that_fails_the_gate": paid,
        "steps_with_unverifiable_route": unverifiable,
        "zero_cost_blocked_events": sum(len(s["zero_cost_blocked"]) for s in steps),
    }
    criteria["all_met"] = bool(
        criteria["run_completed"] and criteria["five_artifacts"]
        and criteria["no_step_in_error"] and criteria["evidence_satisfied"]
        and criteria["human_approval_recorded"] and not paid and not unverifiable)
    return {
        "run": {"id": run[0], "status": run[1], "definition_id": run[2], "project_id": run[3],
                "started_at": run[4], "finished_at": run[5], "seconds": _seconds(run[4], run[5])},
        "steps": steps, "discovery": discovery, "criteria": criteria,
    }


_SOURCE_LABEL = {"real": "reales", "estimated": "estimados", "mixed": "mixtos"}


def _tokens_line(step):
    if not step["tokens_reported"]:
        return "    tokens: sin dato (el paso no emitio model_metrics)"
    label = _SOURCE_LABEL.get(step["usage_source"], "origen no informado")
    return (f"    tokens entrada {step['tokens_in']} / salida {step['tokens_out']} ({label})")


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
        lines.append(f"    proveedor {s['host'] or 'NO VERIFICABLE'} ({s['endpoint_id']}) "
                     f"modelo {s['model']}; artefacto escrito por {s['artifact_model']}, "
                     f"{s['artifact_chars']} caracteres")
        lines.append(_tokens_line(s))
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
    paid, unverifiable = crit["steps_on_a_route_that_fails_the_gate"], crit["steps_with_unverifiable_route"]
    lines += ["", "CRITERIO DE CIERRE DE LA FASE 1",
              f"  run completed .............. {crit['run_completed']}",
              f"  5 artefactos ............... {crit['five_artifacts']}",
              f"  ningun paso en error ....... {crit['no_step_in_error']}",
              f"  evidencia de herramientas .. {crit['evidence_satisfied']}  {crit['evidence']}",
              f"  aprobacion humana registrada {crit['human_approval_recorded']}"
              + (f"  ({crit['human_approval_note']})" if crit["human_approval_note"] else ""),
              f"  pasos en ruta que no pasa la compuerta: {paid or 'ninguno'}",
              f"  pasos cuya ruta NO SE PUDO VERIFICAR: {unverifiable or 'ninguno'}",
              f"  eventos zero_cost_blocked .. {crit['zero_cost_blocked_events']} (cada uno se explica)",
              f"  TODO CUMPLIDO .............. {crit['all_met']}"]
    if crit["evidence_off_in_config"]:
        lines.append("  AVISO: el config de estos pasos no exige evidencia, el criterio si: "
                     + ", ".join(crit["evidence_off_in_config"]))
    lines.append("  (marca synthetic: un texto escrito por Odysseus falla el paso y no se guarda como "
                 "artefacto; un run completed no puede contener uno)")
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
    # as_uri() percent-encodes '#', '?' and spaces: an unescaped '#' cut the URI short,
    # dropped mode=ro and made SQLite create an empty file beside the folder.
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        print(f"No se pudo abrir {db_path} en solo lectura: {exc}")
        return 2
    try:
        run_id = args.run_id or latest_run_id(con)
        if not run_id:
            print("No hay ejecuciones en la base.")
            return 1
        report = build_report(con, run_id)
    except LookupError as exc:
        print(exc)
        return 1
    except sqlite3.Error as exc:
        print(f"La base {db_path} no se pudo leer: {exc}")
        return 2
    finally:
        con.close()
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render(report))
    return 0 if report["criteria"]["all_met"] else 3


if __name__ == "__main__":
    sys.exit(main())
