"""Findings of the independent review of 2026-09-28, each fixed by its own test.

Every test here exists because a mutant survived, or because a claim in the
code was measured and found false. Named after what the reviewer measured, so
a future reader can tell which of these are load-bearing.
"""

import json

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as cdb
from routes import cmh_control_routes as control
from routes import cmh_workflow_routes as routes
from src import cmh_workflows as flow
from src import cmh_provider_router as router
from src.cmh_cost_policy import endpoint_for_url, is_zero_cost_endpoint

GROQ = "https://api.groq.com/openai/v1"
CEREBRAS = "https://api.cerebras.ai/v1"
LOCAL = "http://127.0.0.1:59999/v1"
ANTHROPIC = "https://api.anthropic.com"
LOOKALIKE = "https://api.groq.com.attacker.example/v1"

CONFIG = {"threshold": 0.9, "providers": [
    {"endpoint_host": "api.groq.com", "order": 1, "model": "model-a",
     "limits": {"rpd": 1000}},
    {"endpoint_host": "api.cerebras.ai", "order": 2, "model": "model-a",
     "limits": {"rpm": 5}},
]}


@pytest.fixture
def factory(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    cdb.Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    for module in (flow, routes, control):
        monkeypatch.setattr(module, "SessionLocal", session_factory, raising=False)
    monkeypatch.setattr(routes, "catalog", lambda: [{"id": "project"}])
    monkeypatch.setattr(control, "catalog", lambda: [{"id": "project"}])
    monkeypatch.setattr(control, "owner_is_admin_or_single_user", lambda owner: True)
    for module in (routes, control):
        monkeypatch.setattr(module, "validate_task_tools", lambda tools, owner: set(tools))
        monkeypatch.setattr(module, "validate_task_workspace",
                            lambda workspace, owner, persisted=True: workspace)
        monkeypatch.setattr(module, "protected_area", lambda path: None)
    monkeypatch.setattr(router, "load_quota_config", lambda path=None: CONFIG)
    with session_factory() as db:
        for eid, url, kind in (("groq", GROQ, "api"), ("cerebras", CEREBRAS, "api"),
                               ("local", LOCAL, "local"), ("anthropic", ANTHROPIC, "api")):
            db.add(cdb.ModelEndpoint(id=eid, name=eid, base_url=url, endpoint_kind=kind,
                                     is_enabled=True, cached_models=json.dumps(["model-a"])))
        for key in ("constructor", "revisor"):
            db.add(cdb.ScheduledTask(id=f"task-{key}", owner="admin", name=key, task_type="llm",
                                     endpoint_url=GROQ, model="model-a", prompt="x",
                                     status="paused"))
            db.add(cdb.CMHAgent(id=f"agent-{key}", owner="admin", name=key, project_id="project",
                                role=key, instructions=key, model="model-a",
                                allowed_tools=json.dumps(["read_file"]), workspace=str(tmp_path),
                                status="active", task_id=f"task-{key}"))
        db.commit()
    yield session_factory
    flow._ACTIVE.clear()
    engine.dispose()


@pytest.fixture
def client(factory):
    app = FastAPI()

    @app.middleware("http")
    async def as_admin(request, call_next):
        request.state.current_user = "admin"
        return await call_next(request)

    app.include_router(control.setup_cmh_control_routes())
    app.include_router(routes.setup_cmh_workflow_routes())
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _definition(steps):
    return {"name": "d", "project_id": "project", "steps": steps}


async def _create_run(client, steps):
    definition = await client.post("/api/cmh/workflows", json=_definition(steps))
    assert definition.status_code == 201, definition.text
    run = await client.post(f"/api/cmh/workflows/{definition.json()['id']}/runs",
                            json={"initial_input": "x"})
    assert run.status_code == 201, run.text
    return run.json()["id"]


# --- P1 nº1: the candidate list was never frozen on the real path ------------

async def test_a_run_created_through_the_api_freezes_more_than_one_candidate(client, factory,
                                                                             monkeypatch):
    """The reviewer measured: no route ever put `candidates` in a step config,
    so every real run had exactly one and a 429 killed the step instead of
    falling back. Every executor test injected the list by hand — a shape no
    run produced."""
    monkeypatch.setattr(flow, "start", lambda run_id: None)
    async with client:
        run_id = await _create_run(client, [{"key": "constructor", "agent_id": "agent-constructor"}])
    with factory() as db:
        step = db.query(cdb.CMHWorkflowStep).filter(cdb.CMHWorkflowStep.run_id == run_id).first()
        config = json.loads(step.config)
    candidates = config["candidates"]
    assert len(candidates) > 1, "a run must freeze a list, not a single route"
    assert [c["endpoint_id"] for c in candidates][:2] == [None, "cerebras"] or \
           [c["endpoint_id"] for c in candidates][:2] == ["groq", "cerebras"]
    assert all(is_zero_cost_endpoint({"base_url": c["endpoint_url"], "endpoint_kind": "auto"},
                                     c["model"]) for c in candidates)


async def test_the_frozen_list_never_contains_a_paid_endpoint(client, factory, monkeypatch):
    monkeypatch.setattr(flow, "start", lambda run_id: None)
    async with client:
        run_id = await _create_run(client, [{"key": "constructor", "agent_id": "agent-constructor"}])
    with factory() as db:
        step = db.query(cdb.CMHWorkflowStep).filter(cdb.CMHWorkflowStep.run_id == run_id).first()
        config = json.loads(step.config)
    assert not any("anthropic" in (c["endpoint_url"] or "") for c in config["candidates"])


async def test_a_step_policy_of_local_only_freezes_only_local(client, factory, monkeypatch):
    """Policy precedence was dead code: resolve_policy had no caller outside
    tests, so local-only could not be chosen for any step."""
    monkeypatch.setattr(flow, "start", lambda run_id: None)
    async with client:
        run_id = await _create_run(client, [{"key": "constructor", "agent_id": "agent-constructor",
                                             "provider_policy": "local-only"}])
    with factory() as db:
        step = db.query(cdb.CMHWorkflowStep).filter(cdb.CMHWorkflowStep.run_id == run_id).first()
        config = json.loads(step.config)
    assert config["provider_policy"] == "local-only"
    assert not any("groq" in (c["endpoint_url"] or "") or "cerebras" in (c["endpoint_url"] or "")
                   for c in config["candidates"])


async def test_the_agents_policy_applies_when_the_step_is_silent(client, factory, monkeypatch):
    """provider_policy was accepted by the API and dropped: CMHAgent had no
    column for it."""
    monkeypatch.setattr(flow, "start", lambda run_id: None)
    with factory() as db:
        db.query(cdb.CMHAgent).filter(
            cdb.CMHAgent.id == "agent-constructor").first().provider_policy = "local-only"
        db.commit()
    async with client:
        run_id = await _create_run(client, [{"key": "constructor", "agent_id": "agent-constructor"}])
    with factory() as db:
        step = db.query(cdb.CMHWorkflowStep).filter(cdb.CMHWorkflowStep.run_id == run_id).first()
    assert json.loads(step.config)["provider_policy"] == "local-only"


async def test_the_agents_policy_survives_a_round_trip_through_the_api(client):
    async with client:
        created = await client.post("/api/cmh/agents", json={
            "name": "Con politica", "project_id": "project", "role": "r", "instructions": "i",
            "model": "model-a", "allowed_tools": ["read_file"], "workspace": ".",
            "provider_policy": "local-only"})
        assert created.status_code == 201, created.text
        assert created.json()["provider_policy"] == "local-only"
        listed = (await client.get("/api/cmh/agents")).json()["agents"]
    assert any(a["provider_policy"] == "local-only" for a in listed)


# --- P1 nº2: the per-role exemption did not exist ----------------------------

@pytest.mark.parametrize("key, expected", [
    ("investigador", True), ("constructor", True), ("verificador", True),
    ("revisor", False), ("revisor-cmh", False), ("documentador", False),
])
def test_the_evidence_default_is_actually_per_role(key, expected):
    """validate_dag put True on every step while the commit said 'per role'.
    The reviewer and the documenter work on the artifacts they were handed, so
    True would have failed them on every run."""
    steps = flow.validate_dag([{"key": key, "agent_id": "a"}])
    assert steps[0]["require_tool_evidence"] is expected


def test_an_explicit_value_still_wins_over_the_role_default():
    steps = flow.validate_dag([{"key": "revisor", "agent_id": "a",
                                "require_tool_evidence": True},
                               {"key": "constructor", "agent_id": "b",
                                "require_tool_evidence": False}])
    assert steps[0]["require_tool_evidence"] is True
    assert steps[1]["require_tool_evidence"] is False


async def test_the_reviewer_step_reaches_the_run_exempt(client, factory, monkeypatch):
    """End to end on the shape the browser sends, which is where it was broken."""
    monkeypatch.setattr(flow, "start", lambda run_id: None)
    async with client:
        run_id = await _create_run(client, [
            {"key": "constructor", "agent_id": "agent-constructor"},
            {"key": "revisor", "agent_id": "agent-revisor", "depends_on": ["constructor"],
             "independent_of": ["constructor"]}])
    with factory() as db:
        steps = {s.step_key: json.loads(s.config) for s in db.query(cdb.CMHWorkflowStep).filter(
            cdb.CMHWorkflowStep.run_id == run_id).all()}
    assert steps["constructor"]["require_tool_evidence"] is True
    assert steps["revisor"]["require_tool_evidence"] is False


def test_the_browser_sends_the_flag_for_every_step():
    """The fixture described revisor as exempt in a shape the UI could not
    produce, because flowDefinitionBody omitted the field entirely."""
    import pathlib
    source = pathlib.Path("static/cmh-control.js").read_text(encoding="utf-8")
    assert "require_tool_evidence" in source
    assert "noEvidence" in source and "'revisor'" in source and "'documentador'" in source


# --- P2 nº3: CMH_ZERO_COST=false died with KeyError --------------------------

async def test_the_flag_off_degrades_to_logging_instead_of_crashing(factory, monkeypatch):
    """The docstring promised 'the violation is recorded and the call
    proceeds'. Measured by the reviewer: KeyError 'endpoint_id'."""
    monkeypatch.setenv("CMH_ZERO_COST", "false")
    attempts = []

    async def fake(config, candidate, prompt, record):
        attempts.append(candidate["endpoint_id"])
        return "artifact"

    monkeypatch.setattr(flow, "_run_one_candidate", fake)
    config = {"run_id": "r1", "step_key": "uno", "agent_id": "a", "owner": "admin",
              "name": "n", "workspace": ".", "allowed_tools": ["read_file"],
              "instructions": "i", "endpoint_url": ANTHROPIC, "model": "claude-opus-5"}
    assert await flow.call_model(config, "prompt") == "artifact"
    # The id falls back to the URL because no registered row cleared it:
    # the point is that it ran and recorded, not that it crashed.
    assert attempts == [ANTHROPIC]
    with factory() as db:
        kinds = [e.kind for e in db.query(cdb.CMHWorkflowEvent).all()]
    assert "zero_cost_blocked" in kinds     # recorded, as promised


# --- P2 nº4: the gate judged one row while the call dialled another host -----

def test_a_lookalike_host_is_not_cleared_by_the_free_rows_registration(factory):
    """select_endpoint_for_url matches by substring, so the Groq row won for
    api.groq.com.attacker.example. The gate cleared the row; the call would
    have gone to the other host."""
    with factory() as db:
        assert endpoint_for_url(db, LOOKALIKE) is None
        assert endpoint_for_url(db, GROQ) is not None


async def test_a_step_pointed_at_a_lookalike_host_is_blocked(factory, monkeypatch):
    attempts = []

    async def fake(config, candidate, prompt, record):
        attempts.append(candidate["endpoint_url"])
        return "artifact"

    monkeypatch.setattr(flow, "_run_one_candidate", fake)
    from src.cmh_cost_policy import ZeroCostViolation
    config = {"run_id": "r1", "step_key": "uno", "agent_id": "a", "owner": "admin",
              "name": "n", "workspace": ".", "allowed_tools": ["read_file"],
              "instructions": "i", "endpoint_url": LOOKALIKE, "model": "model-a"}
    with pytest.raises(ZeroCostViolation):
        await flow.call_model(config, "prompt")
    assert attempts == []


# --- P2 nº6: the pre-send quota check was never exercised in call_model ------

async def test_call_model_refuses_to_send_at_the_threshold(factory, monkeypatch):
    """R30, R18, R29 and R31 all survived: the 0.9 threshold was only ever
    tested in isolation, on cases that consumed 100% of the limit."""
    attempts = []

    async def fake(config, candidate, prompt, record):
        attempts.append(candidate["endpoint_id"])
        return "artifact"

    monkeypatch.setattr(flow, "_run_one_candidate", fake)
    with factory() as db:
        # 900 of 1000 is exactly the threshold, and well under the hard limit:
        # a mutant that only stops at 100% keeps sending here.
        router.record_usage(db, "groq", requests=900)
        db.commit()
    config = {"run_id": "r1", "step_key": "uno", "agent_id": "a", "owner": "admin",
              "name": "n", "workspace": ".", "allowed_tools": ["read_file"],
              "instructions": "i", "endpoint_url": GROQ, "model": "model-a",
              "candidates": [{"endpoint_id": "groq", "endpoint_url": GROQ,
                              "model": "model-a", "host": "api.groq.com"}]}
    with pytest.raises(RuntimeError, match="sin cuota"):
        await flow.call_model(config, "prompt")
    assert attempts == [], "the call that would cross the line must never be sent"


async def test_a_spent_candidate_is_skipped_and_the_next_one_answers(factory, monkeypatch):
    attempts = []

    async def fake(config, candidate, prompt, record):
        attempts.append(candidate["endpoint_id"])
        return "artifact"

    monkeypatch.setattr(flow, "_run_one_candidate", fake)
    with factory() as db:
        router.record_usage(db, "groq", requests=900)
        db.commit()
    config = {"run_id": "r1", "step_key": "uno", "agent_id": "a", "owner": "admin",
              "name": "n", "workspace": ".", "allowed_tools": ["read_file"],
              "instructions": "i", "endpoint_url": GROQ, "model": "model-a",
              "candidates": [
                  {"endpoint_id": "groq", "endpoint_url": GROQ, "model": "model-a",
                   "host": "api.groq.com"},
                  {"endpoint_id": "cerebras", "endpoint_url": CEREBRAS, "model": "model-a",
                   "host": "api.cerebras.ai"}]}
    assert await flow.call_model(config, "prompt") == "artifact"
    assert attempts == ["cerebras"]


# --- P2 nº8: a paid host in the quota config could enter the candidate list --

def test_a_paid_host_written_into_the_quota_config_never_becomes_a_candidate(factory):
    """R10 survived because the test config held only free hosts, so the cost
    check inside resolve_candidates was doing nothing any test could see."""
    poisoned = {"threshold": 0.9, "providers": [
        {"endpoint_host": "api.anthropic.com", "order": 0, "model": "claude-opus-5",
         "limits": {}},
        {"endpoint_host": "api.groq.com", "order": 1, "model": "model-a", "limits": {}}]}
    with factory() as db:
        ids = [c["endpoint_id"] for c in router.resolve_candidates(
            db, router.FREE_CLOUD_FIRST, config=poisoned)]
    assert "anthropic" not in ids
    assert "groq" in ids


async def test_the_twin_task_gate_fires_on_a_paid_first_candidate(client, factory, monkeypatch):
    """R24 survived: the existing test only reached `endpoint_url is None` and
    never made the gate refuse anything."""
    monkeypatch.setattr(router, "resolve_candidates",
                        lambda db, policy, owner=None, **kw: [
                            {"endpoint_id": "anthropic", "endpoint_url": ANTHROPIC,
                             "model": "claude-opus-5", "host": "api.anthropic.com"}])
    async with client:
        refused = await client.post("/api/cmh/agents", json={
            "name": "Pagado", "project_id": "project", "role": "r", "instructions": "i",
            "model": "claude-opus-5", "allowed_tools": ["read_file"], "workspace": "."})
    assert refused.status_code == 400
    assert "Costo cero" in refused.json()["detail"]


# --- P3 findings -------------------------------------------------------------

async def test_the_fallback_event_names_the_model_that_actually_answered(factory, monkeypatch):
    """It reported config['model'] always, so a fallback was stamped with the
    model that did NOT produce it."""
    async def fake(config, candidate, prompt, record):
        if candidate["endpoint_id"] == "groq":
            raise TimeoutError()
        return "artifact"

    monkeypatch.setattr(flow, "_run_one_candidate", fake)
    config = {"run_id": "r1", "step_key": "uno", "agent_id": "a", "owner": "admin",
              "name": "n", "workspace": ".", "allowed_tools": ["read_file"],
              "instructions": "i", "endpoint_url": GROQ, "model": "model-groq",
              "candidates": [
                  {"endpoint_id": "groq", "endpoint_url": GROQ, "model": "model-groq",
                   "host": "api.groq.com"},
                  {"endpoint_id": "cerebras", "endpoint_url": CEREBRAS, "model": "model-cerebras",
                   "host": "api.cerebras.ai"}]}
    assert await flow.call_model(config, "prompt") == "artifact"
    with factory() as db:
        events = [(e.kind, json.loads(e.payload)) for e in db.query(cdb.CMHWorkflowEvent).all()]
    fallback = [p for kind, p in events if kind == "provider_fallback"]
    assert fallback and fallback[0]["model"] == "model-groq"   # the one that failed


@pytest.mark.parametrize("status", [500, 501, 502, 503, 504, 505, 529])
def test_every_5xx_falls_back_not_just_the_four_that_were_listed(status):
    class _Response:
        def __init__(self, code):
            self.status_code = code

    class _HttpError(Exception):
        def __init__(self, code):
            super().__init__(str(code))
            self.response = _Response(code)

    assert router.is_fallback_error(_HttpError(status)) == f"http:{status}"


# --- gaps my own re-run of the reviewer's mutants exposed ---------------------

def test_a_bare_host_row_does_not_clear_a_lookalike(factory):
    """Measured: a row registered as 'https://api.groq.com/openai/v1' does NOT
    substring-match the lookalike, so the first version of this test could not
    fail. A row registered as the BARE host does match, and that is the shape
    that makes the substring rule dangerous."""
    from src.endpoint_resolver import select_endpoint_for_url
    with factory() as db:
        db.add(cdb.ModelEndpoint(id="groq-bare", name="groq", base_url="https://api.groq.com",
                                 endpoint_kind="api", is_enabled=True))
        db.commit()
        rows = db.query(cdb.ModelEndpoint).all()
        # The runner's own ranking picks it: the danger is real, not theoretical.
        assert select_endpoint_for_url(rows, LOOKALIKE, "model-a") is not None
        # The gate must still refuse, because the host is not the same host.
        assert endpoint_for_url(db, LOOKALIKE, model="model-a") is None


async def test_a_lookalike_is_blocked_even_with_a_bare_host_row_registered(factory, monkeypatch):
    from src.cmh_cost_policy import ZeroCostViolation
    with factory() as db:
        db.add(cdb.ModelEndpoint(id="groq-bare", name="groq", base_url="https://api.groq.com",
                                 endpoint_kind="api", is_enabled=True))
        db.commit()
    attempts = []

    async def fake(config, candidate, prompt, record):
        attempts.append(candidate["endpoint_url"])
        return "artifact"

    monkeypatch.setattr(flow, "_run_one_candidate", fake)
    config = {"run_id": "r1", "step_key": "uno", "agent_id": "a", "owner": "admin",
              "name": "n", "workspace": ".", "allowed_tools": ["read_file"],
              "instructions": "i", "endpoint_url": LOOKALIKE, "model": "model-a"}
    with pytest.raises(ZeroCostViolation):
        await flow.call_model(config, "prompt")
    assert attempts == []


def test_the_shipped_quota_config_carries_the_threshold_and_it_defaults_to_0_9(tmp_path):
    """The threshold default was only ever read from a config the tests passed
    in, so a mutant that changed the fallback to 1.0 survived."""
    shipped = router.load_quota_config()
    assert shipped["threshold"] == 0.9
    without = tmp_path / "sin-umbral.json"
    without.write_text(json.dumps({"providers": []}), encoding="utf-8")
    assert router.load_quota_config(without)["threshold"] == 0.9
    unreadable = tmp_path / "no-existe.json"
    assert router.load_quota_config(unreadable)["threshold"] == 0.9


async def test_a_successful_fallback_labels_its_event_with_the_failing_model(factory, monkeypatch):
    """The first version could not fail: config['model'] and the first
    candidate's model were the same string, so labelling with either passed."""
    async def fake(config, candidate, prompt, record):
        if candidate["endpoint_id"] == "groq":
            raise TimeoutError()
        record("model_metrics", note="segundo candidato")
        return "artifact"

    monkeypatch.setattr(flow, "_run_one_candidate", fake)
    config = {"run_id": "r1", "step_key": "uno", "agent_id": "a", "owner": "admin",
              "name": "n", "workspace": ".", "allowed_tools": ["read_file"],
              "instructions": "i", "endpoint_url": GROQ,
              # Deliberately unlike either candidate's model, so a label taken
              # from config instead of from the live candidate is visible.
              "model": "modelo-del-config",
              "candidates": [
                  {"endpoint_id": "groq", "endpoint_url": GROQ, "model": "model-groq",
                   "host": "api.groq.com"},
                  {"endpoint_id": "cerebras", "endpoint_url": CEREBRAS, "model": "model-cerebras",
                   "host": "api.cerebras.ai"}]}
    assert await flow.call_model(config, "prompt") == "artifact"
    with factory() as db:
        events = {e.kind: json.loads(e.payload).get("model")
                  for e in db.query(cdb.CMHWorkflowEvent).all()}
    assert events["provider_fallback"] == "model-groq"      # the one that failed
    assert events["model_metrics"] == "model-cerebras"      # the one that answered
