"""The 3.6 record of a run, computed from its rows: read-only, and honest about the
closing criterion.

Step 3.6 asks to record, per step, the agent, the provider and model that answered,
the fallbacks, tokens, seconds, the exit of every tool call and the size of the
artifact, and to close the phase on a criterion made of counts. run_report.py builds
that from the database so the punto limpio quotes numbers. These tests build a run
with the real schema in a file and read it back the way the script does: through a
read-only connection that has never imported core.database.

The review of 2026-09-29 found the criterion could be met by having nothing to
check: an empty list meant "verified" and "not verified" at once. Each of those is a
test here.
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
#: The reviewer starts 30 s after the run (index 3 x 10 s); an approval before that
#: is an approval that came first.
BEFORE_REVIEWER = "2026-09-30T09:00:25Z"
AFTER_REVIEWER = "2026-09-30T09:01:00Z"


def build(path, *, status="completed", drop_artifact=None, drop_step=None, verifier_tools=None,
          constructor_tools=None, reviewer_started=True, decision="approved", decision_by="admin",
          decision_at=BEFORE_REVIEWER, gate=("revisor",), reviewer_endpoint="orr",
          reviewer_frozen=None, broken_step=None, evidence_flags=None, blocked_url=None,
          usage_sources=None, run_id="run-1", started=T0):
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
            if key == drop_step:
                continue
            endpoint, model = ("groq", "openai/gpt-oss-120b")
            if key == "constructor":
                endpoint, model = "orr", "big/model:free"
            if key == "revisor":
                endpoint, model = reviewer_endpoint, "big/model:free"
            evidence = key in ("investigador", "constructor", "verificador")
            if evidence_flags and key in evidence_flags:
                evidence = evidence_flags[key]
            config = {"model": "openai/gpt-oss-120b", "resolved_model": model,
                      "resolved_endpoint_id": endpoint, "instructions_version": 1,
                      "require_tool_evidence": evidence, "requires_approval": key in gate}
            if key == "revisor" and reviewer_frozen:
                config["candidates"] = [{"endpoint_id": endpoint, "endpoint_url": reviewer_frozen,
                                         "model": model, "host": "frozen"}]
            step_decision = None
            if key in gate and decision:
                step_decision = json.dumps({"outcome": decision, "justification": None,
                                            "by": decision_by, "at": decision_at})
            db.add(cdb.CMHWorkflowStep(
                id=f"step-{run_id}-{key}", run_id=run_id, step_key=key, agent_id=f"agent-{key}",
                config=json.dumps(config), dependencies="[]",
                status="error" if key == broken_step else "completed",
                started_at=(None if key == "revisor" and not reviewer_started
                            else started + timedelta(seconds=index * 10)),
                finished_at=started + timedelta(seconds=index * 10 + 8), decision=step_decision))
            if key != drop_artifact:
                db.add(cdb.CMHWorkflowArtifact(
                    id=f"art-{run_id}-{key}", run_id=run_id, step_key=key, agent_id=f"agent-{key}",
                    model=model, instructions_version=1, content="a" * (100 * (index + 1))))

        sources = usage_sources or {}

        def event(key, kind, **payload):
            db.add(cdb.CMHWorkflowEvent(run_id=run_id, step_key=key, kind=kind,
                                        payload=json.dumps(payload)))

        def metrics(key, position, tokens_in, tokens_out):
            listed = sources.get(key) or []
            body = {"input_tokens": tokens_in, "output_tokens": tokens_out}
            if position < len(listed) and listed[position]:
                body["usage_source"] = listed[position]
            event(key, "model_metrics", metrics=body)

        event(None, "provider_discovery", provider="openrouter.ai", outcome="ok",
              model="big/model:free", source="models/user", reason=None)
        event("investigador", "zero_cost_blocked",
              endpoint_url=blocked_url or "https://api.anthropic.com",
              candidate_model="claude-sonnet-4-5")
        event("investigador", "tool_finished", tool="ls", error=False, exit_code=0, duration_seconds=0.1)
        event("investigador", "tool_finished", tool="read_file", error=False, exit_code=0, duration_seconds=0.2)
        metrics("investigador", 0, 100, 50)
        event("investigador", "step_completed", artifact_id="art-investigador", artifact_chars=100,
              duration_seconds=3.5)
        event("constructor", "provider_fallback", **{"from": "groq", "to": "orr", "reason": "http:429"})
        event("constructor", "provider_fallback", **{"from": "groq", "to": None, "reason": "quota:tpd"})
        for tool in (constructor_tools if constructor_tools is not None else [("read_file", 0)]):
            event("constructor", "tool_finished", tool=tool[0], error=tool[1] not in (None, 0),
                  exit_code=tool[1], duration_seconds=0.3)
        metrics("constructor", 0, 200, 80)
        metrics("constructor", 1, 30, 10)
        event("constructor", "step_completed", artifact_id="art-constructor", artifact_chars=200,
              duration_seconds=6.25)
        for tool in (verifier_tools if verifier_tools is not None else [("ls", 0)]):
            event("verificador", "tool_finished", tool=tool[0], error=tool[1] not in (None, 0),
                  exit_code=tool[1], duration_seconds=0.1)
        metrics("verificador", 0, 50, 20)
        event("verificador", "step_completed", artifact_id="art-verificador", artifact_chars=300,
              duration_seconds=2.0)
        db.commit()
    engine.dispose()


def repoint(path, endpoint_id, url):
    con = sqlite3.connect(str(path))
    con.execute("UPDATE model_endpoints SET base_url = ? WHERE id = ?", (url, endpoint_id))
    con.commit()
    con.close()


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
                                    "by": "admin", "at": BEFORE_REVIEWER}
    assert reviewer["tools"] == [] and reviewer["requires_evidence"] is False


def test_the_seconds_of_the_run_and_of_a_step_without_a_completion_event(tmp_path):
    """The run's seconds come from its own start and finish; a step with no
    step_completed event falls back to its own start and finish (8 s in the fixture)."""
    path = tmp_path / "app.db"
    build(path)
    result = report(path)
    assert result["run"]["seconds"] == 90.0
    steps = {s["key"]: s for s in result["steps"]}
    assert steps["documentador"]["seconds"] == 8.0        # no step_completed event
    assert steps["constructor"]["seconds"] == 6.25        # the event wins when there is one


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
    assert criteria["evidence_off_in_config"] == []
    assert criteria["human_approval_recorded"] is True and criteria["human_approval_note"] is None
    assert criteria["zero_cost_blocked_events"] == 1     # admitted, and listed to be explained
    assert criteria["steps_on_a_route_that_fails_the_gate"] == []
    assert criteria["steps_with_unverifiable_route"] == []


@pytest.mark.parametrize("break_it, criterion", [
    ({"status": "error"}, "run_completed"),
    ({"drop_artifact": "documentador"}, "five_artifacts"),
    ({"verifier_tools": [("ls", 1)]}, "evidence_satisfied"),
    ({"verifier_tools": []}, "evidence_satisfied"),
    ({"decision": None}, "human_approval_recorded"),
    ({"decision": "rejected"}, "human_approval_recorded"),
    ({"broken_step": "constructor"}, "no_step_in_error"),
])
def test_each_way_of_failing_the_criterion_is_seen(tmp_path, break_it, criterion):
    path = tmp_path / "app.db"
    build(path, **break_it)
    criteria = report(path)["criteria"]
    assert criteria[criterion] is False, criterion
    assert criteria["all_met"] is False


# --- the route of each step ---------------------------------------------------

def test_a_step_on_a_route_the_cost_gate_refuses_fails_the_criterion(tmp_path):
    path = tmp_path / "app.db"
    build(path, reviewer_endpoint="anthropic")
    criteria = report(path)["criteria"]
    assert criteria["steps_on_a_route_that_fails_the_gate"] == ["revisor"]
    assert criteria["all_met"] is False


def test_a_route_that_cannot_be_resolved_is_unverifiable_and_fails_the_criterion(tmp_path):
    """resolved_endpoint_id names no registered row and is not a URL (a deleted row, a
    None): host None and an empty 'paid' list used to read as 'verified'."""
    path = tmp_path / "app.db"
    build(path, reviewer_endpoint="ghost-endpoint")
    result = report(path)
    criteria = result["criteria"]
    assert criteria["steps_with_unverifiable_route"] == ["revisor"]
    assert criteria["steps_on_a_route_that_fails_the_gate"] == []
    assert criteria["all_met"] is False
    text = report_mod.render(result)
    assert "NO SE PUDO VERIFICAR: ['revisor']" in text and "NO VERIFICABLE" in text


@pytest.mark.parametrize("url, paid", [
    ("https://api.anthropic.com/v1", ["revisor"]),          # a URL used as the id, paid
    ("https://api.groq.com/openai/v1", []),                 # a URL used as the id, free
])
def test_an_id_that_is_itself_a_url_is_judged_as_that_url(tmp_path, url, paid):
    path = tmp_path / "app.db"
    build(path, reviewer_endpoint=url)
    criteria = report(path)["criteria"]
    assert criteria["steps_on_a_route_that_fails_the_gate"] == paid
    assert criteria["steps_with_unverifiable_route"] == []


def test_the_url_frozen_at_run_creation_decides_not_the_row_as_it_is_today(tmp_path):
    """A row repointed AFTER the run must not change the verdict on what the run did."""
    path = tmp_path / "app.db"
    build(path, reviewer_endpoint="orr", reviewer_frozen="https://openrouter.ai/api/v1")
    repoint(path, "orr", "https://api.anthropic.com")       # the row now points at a paid host
    # The reviewer froze its URL, so it is judged by that. The constructor has no frozen
    # candidate in this fixture, so it falls back to the row as it is today: the
    # documented limit of a run frozen before candidates carried a URL.
    assert report(path)["criteria"]["steps_on_a_route_that_fails_the_gate"] == ["constructor"]

    other = tmp_path / "otra.db"
    build(other, reviewer_endpoint="groq", reviewer_frozen="https://api.anthropic.com/v1")
    assert report(other)["criteria"]["steps_on_a_route_that_fails_the_gate"] == ["revisor"]


def test_a_step_that_never_completed_is_not_asked_for_a_route(tmp_path):
    """Only a completed step must have been somewhere; an errored one may not have started."""
    path = tmp_path / "app.db"
    build(path, reviewer_endpoint="ghost-endpoint", broken_step="revisor")
    assert report(path)["criteria"]["steps_with_unverifiable_route"] == []


# --- evidence: the three roles the blueprint names, whatever the config says ----------

def test_the_evidence_criterion_covers_the_three_roles_even_if_a_config_switched_it_off(tmp_path):
    path = tmp_path / "app.db"
    build(path, constructor_tools=[], evidence_flags={"constructor": False})
    criteria = report(path)["criteria"]
    assert criteria["evidence"]["constructor"] is False
    assert criteria["evidence_satisfied"] is False and criteria["all_met"] is False
    assert criteria["evidence_off_in_config"] == ["constructor"]
    assert "AVISO" in report_mod.render(report(path)) and "constructor" in report_mod.render(report(path))


def test_a_missing_evidence_role_is_not_satisfied(tmp_path):
    path = tmp_path / "app.db"
    build(path, drop_step="verificador")
    criteria = report(path)["criteria"]
    assert criteria["evidence"]["verificador"] is False
    assert criteria["evidence_satisfied"] is False


def test_with_no_step_asking_for_evidence_the_criterion_is_not_met(tmp_path):
    path = tmp_path / "app.db"
    build(path, verifier_tools=[], constructor_tools=[],
          evidence_flags={"investigador": False, "constructor": False, "verificador": False})
    criteria = report(path)["criteria"]
    assert criteria["evidence_satisfied"] is False and criteria["all_met"] is False


# --- the human approval: present, by someone, and BEFORE the reviewer started ----------

def test_a_run_with_no_approval_gate_does_not_pass_the_approval_criterion(tmp_path):
    """The phase's objective is a human decision before the reviewer. A run that has no
    gate used to pass it for having nothing to check."""
    path = tmp_path / "app.db"
    build(path, gate=(), decision=None)
    criteria = report(path)["criteria"]
    assert criteria["human_approval_recorded"] is False
    assert criteria["human_approval_note"] == "ningun paso exige aprobacion humana"
    assert criteria["all_met"] is False


def test_the_gate_has_to_be_on_the_reviewer(tmp_path):
    path = tmp_path / "app.db"
    build(path, gate=("documentador",))
    criteria = report(path)["criteria"]
    assert criteria["human_approval_recorded"] is False
    assert criteria["human_approval_note"] == "el paso revisor no exige aprobacion"


@pytest.mark.parametrize("knobs, why", [
    ({"decision_by": ""}, "sin autor"),
    ({"decision_at": ""}, "sin fecha"),
    ({"decision_at": AFTER_REVIEWER}, "la aprobacion es posterior al inicio del paso"),
])
def test_an_approval_needs_who_when_and_to_come_first(tmp_path, knobs, why):
    path = tmp_path / "app.db"
    build(path, **knobs)
    criteria = report(path)["criteria"]
    assert criteria["human_approval_recorded"] is False
    assert criteria["human_approval_note"] == f"revisor: {why}"
    assert criteria["all_met"] is False


def test_the_approval_time_is_compared_in_utc_whatever_offset_it_was_written_with(tmp_path):
    """11:00:00+02:00 is 09:00:00Z, before the reviewer; read as a naive 11:00 it would be
    two hours after it."""
    path = tmp_path / "app.db"
    build(path, decision_at="2026-09-30T11:00:00+02:00")
    assert report(path)["criteria"]["human_approval_recorded"] is True


# --- what the report prints -----------------------------------------------------------

def test_a_blocked_url_is_reported_as_scheme_and_host_only(tmp_path, capsys):
    path = tmp_path / "app.db"
    build(path, blocked_url="https://user:hunter2@api.anthropic.com/v1?key=hunter2")
    step = {s["key"]: s for s in report(path)["steps"]}["investigador"]
    assert step["zero_cost_blocked"][0]["endpoint_url"] == "https://api.anthropic.com"
    report_mod.main(["run-1", "--db", str(path), "--json"])
    assert "hunter2" not in capsys.readouterr().out
    report_mod.main(["run-1", "--db", str(path)])
    assert "hunter2" not in capsys.readouterr().out


def test_tokens_say_where_they_come_from_and_a_step_without_metrics_says_it_has_none(tmp_path):
    path = tmp_path / "app.db"
    build(path, usage_sources={"investigador": ["real"], "constructor": ["real", "estimated"],
                               "verificador": ["estimated"]})
    result = report(path)
    steps = {s["key"]: s for s in result["steps"]}
    assert [steps[k]["usage_source"] for k in ("investigador", "constructor", "verificador")] == [
        "real", "mixed", "estimated"]
    assert steps["revisor"]["tokens_reported"] is False and steps["investigador"]["tokens_reported"] is True
    text = report_mod.render(result)
    assert "tokens entrada 100 / salida 50 (reales)" in text
    assert "tokens entrada 230 / salida 90 (mixtos)" in text
    assert "tokens entrada 50 / salida 20 (estimados)" in text
    assert "tokens: sin dato (el paso no emitio model_metrics)" in text


def test_tokens_without_a_stated_source_are_labelled_as_such(tmp_path):
    path = tmp_path / "app.db"
    build(path)
    assert "tokens entrada 100 / salida 50 (origen no informado)" in report_mod.render(report(path))


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
    build(path, run_id="nueva", started=T0 + timedelta(hours=2), decision_at="2026-09-30T11:00:25Z")
    assert report_mod.main(["--latest", "--db", str(path), "--json"]) == 0
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


def test_a_path_with_a_hash_and_a_space_is_still_opened_read_only(tmp_path, capsys):
    """An unescaped '#' cut the URI short, dropped mode=ro and made SQLite create an empty
    file beside the folder; the script then died with a traceback."""
    folder = tmp_path / "datos #1 de prueba"
    folder.mkdir()
    path = folder / "app.db"
    build(path)
    before = sorted(p.name for p in tmp_path.iterdir())
    assert report_mod.main(["run-1", "--db", str(path)]) == 0
    assert "Ejecucion run-1" in capsys.readouterr().out
    assert sorted(p.name for p in tmp_path.iterdir()) == before      # nothing was created


def test_a_file_that_is_not_a_database_is_reported_and_not_a_traceback(tmp_path, capsys):
    path = tmp_path / "app.db"
    path.write_bytes(b"this is not a sqlite file" * 40)
    assert report_mod.main(["run-1", "--db", str(path)]) == 2
    assert "no se pudo" in capsys.readouterr().out.lower()


# --- review of revision-fase1-r7 -----------------------------------------------------------

@pytest.mark.parametrize("decision_at", ["1999-01-01T00:00:00Z", "1970-01-01T00:00:00",
                                         "2026-09-30T08:59:59Z"])
def test_an_approval_dated_before_the_run_began_is_not_an_approval_of_this_run(
        tmp_path, decision_at):
    """The upper bound alone let a decision dated 1999 (or 1970) meet the criterion: the
    engine cannot write such a date, so it means the database was altered."""
    path = tmp_path / "app.db"
    build(path, decision_at=decision_at)
    criteria = report(path)["criteria"]
    assert criteria["human_approval_recorded"] is False
    assert criteria["human_approval_note"] == "revisor: la aprobacion es anterior al inicio de la ejecucion"
    assert criteria["all_met"] is False


def test_an_approval_at_the_very_second_the_reviewer_started_is_still_before_it(tmp_path):
    """The engine sets started_at only after the approval: equal is allowed, later is not."""
    path = tmp_path / "app.db"
    build(path, decision_at="2026-09-30T09:00:30Z")          # the reviewer starts at 09:00:30
    assert report(path)["criteria"]["human_approval_recorded"] is True


def test_a_reviewer_with_no_start_time_cannot_be_shown_to_have_been_approved_first(tmp_path):
    path = tmp_path / "app.db"
    build(path, reviewer_started=False)
    criteria = report(path)["criteria"]
    assert criteria["human_approval_recorded"] is False
    assert criteria["human_approval_note"] == "revisor: el paso no tiene hora de inicio"


def test_a_step_whose_endpoint_id_is_a_url_with_credentials_prints_no_credential(tmp_path, capsys):
    path = tmp_path / "app.db"
    build(path, reviewer_endpoint="https://rvuser:RVPASS@api.groq.com/openai/v1")
    step = {s["key"]: s for s in report(path)["steps"]}["revisor"]
    assert step["endpoint_id"] == "https://api.groq.com"
    report_mod.main(["run-1", "--db", str(path)])
    assert "RVPASS" not in capsys.readouterr().out
    report_mod.main(["run-1", "--db", str(path), "--json"])
    assert "RVPASS" not in capsys.readouterr().out


def test_latest_on_a_database_with_no_runs_says_so_and_is_not_green(tmp_path, capsys):
    """Nothing to verify is not 'verified': the exit code that says it has to be pinned."""
    path = tmp_path / "vacia.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    cdb.Base.metadata.create_all(engine)
    engine.dispose()
    assert report_mod.main(["--latest", "--db", str(path)]) == 1
    assert "No hay ejecuciones en la base." in capsys.readouterr().out
