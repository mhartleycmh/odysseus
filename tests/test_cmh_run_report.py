"""The 3.6 record of a run, computed from its rows: read-only, and honest about the
closing criterion.

Step 3.6 asks to record, per step, the agent, the provider and model that answered,
the fallbacks, tokens, seconds, the exit of every tool call and the size of the
artifact, and to close the phase on a criterion made of counts. run_report.py builds
that from the database so the punto limpio quotes numbers. These tests build a run
with the real schema in a file and read it back the way the script does: through a
read-only connection that has never imported core.database.
"""

import importlib.util
import json
import pathlib
import sqlite3
import sys
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as cdb

REPO = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cmh_run_report", REPO / "scripts" / "cmh_ops" / "run_report.py")
report_mod = importlib.util.module_from_spec(spec)
sys.modules["cmh_run_report"] = report_mod
spec.loader.exec_module(report_mod)

T0 = datetime(2026, 9, 30, 9, 0, 0)
KEYS = ["investigador", "constructor", "verificador", "revisor", "documentador"]


def build(path, *, status="completed", drop_artifact=None, verifier_tools=None,
          decision="approved", reviewer_endpoint="orr", run_id="run-1", started=T0):
    """A five-step run as the engine would leave it, with knobs for what to break."""
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        for eid, url, kind in (("groq", "https://api.groq.com/openai/v1", "api"),
                               ("orr", "https://openrouter.ai/api/v1", "api"),
                               ("anthropic", "https://api.anthropic.com", "api"),
                               ("lms", "http://127.0.0.1:1234/v1", "local")):
            if db.get(cdb.ModelEndpoint, eid) is None:     # build() may run twice on one file
                db.add(cdb.ModelEndpoint(id=eid, name=eid, base_url=url, endpoint_kind=kind,
                                         is_enabled=True, api_key="sk-DUMMY-SECRET-DO-NOT-PRINT"))
        for key in KEYS:
            if db.get(cdb.CMHAgent, f"agent-{key}") is None:
                db.add(cdb.CMHAgent(id=f"agent-{key}", owner="admin", name=key.capitalize(),
                                    project_id="p", role=key, instructions="x", status="active",
                                    instructions_version=1))
        db.add(cdb.CMHWorkflowRun(id=run_id, owner="admin", definition_id="def-1", project_id="p",
                                  status=status, initial_input="entrada sintetica",
                                  started_at=started, finished_at=started + timedelta(seconds=90)))
        for index, key in enumerate(KEYS):
            endpoint, model = ("groq", "openai/gpt-oss-120b")
            if key == "constructor":
                endpoint, model = "orr", "big/model:free"
            if key == "revisor":
                endpoint, model = reviewer_endpoint, "big/model:free"
            evidence = key in ("investigador", "constructor", "verificador")
            config = {"model": "openai/gpt-oss-120b", "resolved_model": model,
                      "resolved_endpoint_id": endpoint, "instructions_version": 1,
                      "require_tool_evidence": evidence, "requires_approval": key == "revisor"}
            step_decision = None
            if key == "revisor" and decision:
                step_decision = json.dumps({"outcome": decision, "justification": None,
                                            "by": "admin", "at": "2026-09-30T09:01:00Z"})
            db.add(cdb.CMHWorkflowStep(
                id=f"step-{run_id}-{key}", run_id=run_id, step_key=key, agent_id=f"agent-{key}",
                config=json.dumps(config), dependencies="[]", status="completed",
                started_at=started + timedelta(seconds=index * 10),
                finished_at=started + timedelta(seconds=index * 10 + 8), decision=step_decision))
            if key != drop_artifact:
                db.add(cdb.CMHWorkflowArtifact(
                    id=f"art-{run_id}-{key}", run_id=run_id, step_key=key, agent_id=f"agent-{key}",
                    model=model, instructions_version=1, content="a" * (100 * (index + 1))))

        def event(key, kind, **payload):
            db.add(cdb.CMHWorkflowEvent(run_id=run_id, step_key=key, kind=kind,
                                        payload=json.dumps(payload)))

        event(None, "provider_discovery", provider="openrouter.ai", outcome="ok",
              model="big/model:free", source="models/user", reason=None)
        event("investigador", "zero_cost_blocked", endpoint_url="https://api.anthropic.com",
              candidate_model="claude-sonnet-4-5")
        event("investigador", "tool_finished", tool="ls", error=False, exit_code=0, duration_seconds=0.1)
        event("investigador", "tool_finished", tool="read_file", error=False, exit_code=0, duration_seconds=0.2)
        event("investigador", "model_metrics", metrics={"input_tokens": 100, "output_tokens": 50})
        event("investigador", "step_completed", artifact_id="art-investigador", artifact_chars=100,
              duration_seconds=3.5)
        event("constructor", "provider_fallback", **{"from": "groq", "to": "orr", "reason": "http:429"})
        event("constructor", "provider_fallback", **{"from": "groq", "to": None, "reason": "quota:tpd"})
        event("constructor", "tool_finished", tool="read_file", error=False, exit_code=0, duration_seconds=0.3)
        event("constructor", "model_metrics", metrics={"input_tokens": 200, "output_tokens": 80})
        event("constructor", "model_metrics", metrics={"input_tokens": 30, "output_tokens": 10})
        event("constructor", "step_completed", artifact_id="art-constructor", artifact_chars=200,
              duration_seconds=6.25)
        for tool in (verifier_tools if verifier_tools is not None else [("ls", 0)]):
            event("verificador", "tool_finished", tool=tool[0], error=tool[1] not in (None, 0),
                  exit_code=tool[1], duration_seconds=0.1)
        event("verificador", "model_metrics", metrics={"input_tokens": 50, "output_tokens": 20})
        event("verificador", "step_completed", artifact_id="art-verificador", artifact_chars=300,
              duration_seconds=2.0)
        db.commit()
    engine.dispose()


def open_ro(path):
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def report(path, run_id="run-1"):
    con = open_ro(path)
    try:
        return report_mod.build_report(con, run_id)
    finally:
        con.close()


def test_the_record_has_what_step_36_asks_for_per_step(tmp_path):
    path = tmp_path / "app.db"
    build(path)
    steps = {s["key"]: s for s in report(path)["steps"]}
    assert list(steps) == KEYS

    first = steps["investigador"]
    assert (first["agent"], first["host"], first["model"]) == (
        "Investigador", "api.groq.com", "openai/gpt-oss-120b")
    assert [(t["tool"], t["exit_code"]) for t in first["tools"]] == [("ls", 0), ("read_file", 0)]
    assert (first["tokens_in"], first["tokens_out"], first["seconds"]) == (100, 50, 3.5)
    assert first["artifact_chars"] == 100 and first["artifact_model"] == "openai/gpt-oss-120b"
    assert first["zero_cost_blocked"] == [{"endpoint_url": "https://api.anthropic.com",
                                           "model": "claude-sonnet-4-5"}]

    built = steps["constructor"]
    assert (built["host"], built["model"]) == ("openrouter.ai", "big/model:free")
    assert built["fallbacks"] == [{"from": "groq", "to": "orr", "reason": "http:429"}]
    assert built["quota_skips"] == [{"from": "groq", "to": None, "reason": "quota:tpd"}]
    # tokens are the sum over the step's model_metrics events, one per attempt
    assert (built["tokens_in"], built["tokens_out"]) == (230, 90)

    reviewer = steps["revisor"]
    assert reviewer["decision"] == {"outcome": "approved", "justification": None,
                                    "by": "admin", "at": "2026-09-30T09:01:00Z"}
    assert reviewer["tools"] == [] and reviewer["requires_evidence"] is False


def test_the_discovery_of_the_run_is_reported(tmp_path):
    path = tmp_path / "app.db"
    build(path)
    assert report(path)["discovery"] == [{"provider": "openrouter.ai", "outcome": "ok",
                                          "model": "big/model:free", "source": "models/user",
                                          "reason": None}]


def test_a_clean_run_meets_the_whole_closing_criterion(tmp_path):
    path = tmp_path / "app.db"
    build(path)
    criteria = report(path)["criteria"]
    assert criteria["all_met"] is True
    assert criteria["evidence"] == {"investigador": True, "constructor": True, "verificador": True}
    assert criteria["zero_cost_blocked_events"] == 1     # admitted, and listed to be explained
    assert criteria["steps_on_a_route_that_fails_the_gate"] == []


@pytest.mark.parametrize("break_it, criterion", [
    ({"status": "error"}, "run_completed"),
    ({"drop_artifact": "documentador"}, "five_artifacts"),
    ({"verifier_tools": [("ls", 1)]}, "evidence_satisfied"),
    ({"verifier_tools": []}, "evidence_satisfied"),
    ({"decision": None}, "human_approval_recorded"),
    ({"decision": "rejected"}, "human_approval_recorded"),
])
def test_each_way_of_failing_the_criterion_is_seen(tmp_path, break_it, criterion):
    path = tmp_path / "app.db"
    build(path, **break_it)
    criteria = report(path)["criteria"]
    assert criteria[criterion] is False, criterion
    assert criteria["all_met"] is False


def test_a_step_on_a_route_the_cost_gate_refuses_fails_the_criterion(tmp_path):
    path = tmp_path / "app.db"
    build(path, reviewer_endpoint="anthropic")
    criteria = report(path)["criteria"]
    assert criteria["steps_on_a_route_that_fails_the_gate"] == ["revisor"]
    assert criteria["all_met"] is False


def test_the_report_is_read_only_and_never_selects_the_key(tmp_path):
    path = tmp_path / "app.db"
    build(path)
    before = path.read_bytes()
    statements = []
    con = open_ro(path)
    con.set_trace_callback(statements.append)
    report_mod.build_report(con, "run-1")
    con.close()
    assert path.read_bytes() == before
    assert statements and not any("api_key" in s.lower() for s in statements)


def test_the_command_reports_and_signals_with_its_exit_code(tmp_path, capsys):
    path = tmp_path / "app.db"
    build(path)
    assert report_mod.main(["run-1", "--db", str(path)]) == 0
    out = capsys.readouterr().out
    assert "TODO CUMPLIDO .............. True" in out and "sk-DUMMY" not in out
    assert "http:429" in out and "BLOQUEADO por costo cero" in out

    broken = tmp_path / "roto.db"
    build(broken, status="error")
    assert report_mod.main(["run-1", "--db", str(broken)]) == 3
    assert report_mod.main(["no-existe", "--db", str(path)]) == 1
    assert report_mod.main(["run-1", "--db", str(tmp_path / "ausente.db")]) == 2


def test_latest_picks_the_most_recent_run(tmp_path, capsys):
    path = tmp_path / "app.db"
    build(path, run_id="vieja", started=T0)
    build(path, run_id="nueva", started=T0 + timedelta(hours=2))
    assert report_mod.main(["--latest", "--db", str(path), "--json"]) in (0, 3)
    assert json.loads(capsys.readouterr().out)["run"]["id"] == "nueva"


def test_the_command_opens_the_database_read_only(tmp_path, monkeypatch, capsys):
    """Opening with mode=ro is what makes the promise checkable from the outside; a
    script that only ever SELECTs would leave the file byte-identical either way, so
    the open call itself is what is inspected."""
    path = tmp_path / "app.db"
    build(path)
    opened = []
    real = sqlite3.connect

    def spy(target, *args, **kwargs):
        opened.append(str(target))
        return real(target, *args, **kwargs)

    monkeypatch.setattr(report_mod.sqlite3, "connect", spy)
    report_mod.main(["run-1", "--db", str(path)])
    assert opened and all("mode=ro" in target for target in opened), opened
