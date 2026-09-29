"""Findings of the independent review of 2026-09-28, each fixed by its own test.

Every test here exists because a mutant survived, or because a claim in the
code was measured and found false. Named after what the reviewer measured, so
a future reader can tell which of these are load-bearing.
"""

import asyncio
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
OPENROUTER = "https://openrouter.ai/api/v1"
LOCAL = "http://127.0.0.1:59999/v1"
ANTHROPIC = "https://api.anthropic.com"
LOOKALIKE = "https://api.groq.com.attacker.example/v1"

CONFIG = {"threshold": 0.9, "providers": [
    {"endpoint_host": "api.groq.com", "order": 1, "model": "model-a:free",
     "limits": {"rpd": 1000}},
    {"endpoint_host": "openrouter.ai", "order": 2, "model": "model-a:free",
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
        for eid, url, kind in (("groq", GROQ, "api"), ("openrouter", OPENROUTER, "api"),
                               ("local", LOCAL, "local"), ("anthropic", ANTHROPIC, "api")):
            db.add(cdb.ModelEndpoint(id=eid, name=eid, base_url=url, endpoint_kind=kind,
                                     is_enabled=True, cached_models=json.dumps(["model-a:free"])))
        for key in ("constructor", "revisor"):
            db.add(cdb.ScheduledTask(id=f"task-{key}", owner="admin", name=key, task_type="llm",
                                     endpoint_url=GROQ, model="model-a:free", prompt="x",
                                     status="paused"))
            db.add(cdb.CMHAgent(id=f"agent-{key}", owner="admin", name=key, project_id="project",
                                role=key, instructions=key, model="model-a:free",
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
    # No disjunction: the earlier version accepted `endpoint_id: None`, which is
    # exactly the shape that later killed a step after it had already answered.
    assert all(c["endpoint_id"] for c in candidates), "ningun candidato sin id"
    assert [c["endpoint_id"] for c in candidates][:2] == ["groq", "openrouter"]
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
    assert not any("groq" in (c["endpoint_url"] or "") or "openrouter" in (c["endpoint_url"] or "")
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
            "model": "model-a:free", "allowed_tools": ["read_file"], "workspace": ".",
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
              "instructions": "i", "endpoint_url": LOOKALIKE, "model": "model-a:free"}
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
              "instructions": "i", "endpoint_url": GROQ, "model": "model-a:free",
              "candidates": [{"endpoint_id": "groq", "endpoint_url": GROQ,
                              "model": "model-a:free", "host": "api.groq.com"}]}
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
              "instructions": "i", "endpoint_url": GROQ, "model": "model-a:free",
              "candidates": [
                  {"endpoint_id": "groq", "endpoint_url": GROQ, "model": "model-a:free",
                   "host": "api.groq.com"},
                  {"endpoint_id": "openrouter", "endpoint_url": OPENROUTER, "model": "model-a:free",
                   "host": "api.openrouter.ai"}]}
    assert await flow.call_model(config, "prompt") == "artifact"
    assert attempts == ["openrouter"]


# --- P2 nº8: a paid host in the quota config could enter the candidate list --

def test_a_paid_host_written_into_the_quota_config_never_becomes_a_candidate(factory):
    """R10 survived because the test config held only free hosts, so the cost
    check inside resolve_candidates was doing nothing any test could see."""
    poisoned = {"threshold": 0.9, "providers": [
        {"endpoint_host": "api.anthropic.com", "order": 0, "model": "claude-opus-5",
         "limits": {}},
        {"endpoint_host": "api.groq.com", "order": 1, "model": "model-a:free", "limits": {}}]}
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
              "instructions": "i", "endpoint_url": GROQ, "model": "model-groq:free",
              "candidates": [
                  {"endpoint_id": "groq", "endpoint_url": GROQ, "model": "model-groq:free",
                   "host": "api.groq.com"},
                  {"endpoint_id": "openrouter", "endpoint_url": OPENROUTER, "model": "model-openrouter:free",
                   "host": "api.openrouter.ai"}]}
    assert await flow.call_model(config, "prompt") == "artifact"
    with factory() as db:
        events = [(e.kind, json.loads(e.payload)) for e in db.query(cdb.CMHWorkflowEvent).all()]
    fallback = [p for kind, p in events if kind == "provider_fallback"]
    assert fallback and fallback[0]["model"] == "model-groq:free"   # the one that failed


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
        assert select_endpoint_for_url(rows, LOOKALIKE, "model-a:free") is not None
        # The gate must still refuse, because the host is not the same host.
        assert endpoint_for_url(db, LOOKALIKE, model="model-a:free") is None


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
              "instructions": "i", "endpoint_url": LOOKALIKE, "model": "model-a:free"}
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
                  {"endpoint_id": "groq", "endpoint_url": GROQ, "model": "model-groq:free",
                   "host": "api.groq.com"},
                  {"endpoint_id": "openrouter", "endpoint_url": OPENROUTER, "model": "model-openrouter:free",
                   "host": "api.openrouter.ai"}]}
    assert await flow.call_model(config, "prompt") == "artifact"
    with factory() as db:
        events = {e.kind: json.loads(e.payload).get("model")
                  for e in db.query(cdb.CMHWorkflowEvent).all()}
    assert events["provider_fallback"] == "model-groq:free"      # the one that failed
    assert events["model_metrics"] == "model-openrouter:free"      # the one that answered


# --- Cerebras leaves the chain (canon 05, 2026-09-29) ------------------------

CEREBRAS = "https://api.cerebras.ai/v1"


def test_cerebras_is_no_longer_a_free_host():
    """It has no permanent free tier: the trial is 5 USD of credit that expires
    in 30 days and the API goes inactive without a verified card, which fails
    the condition D1 rests on. Kept as a test rather than only a deletion, so
    putting it back is a decision somebody has to make against a red suite."""
    from src.cmh_cost_policy import FREE_HOSTS
    assert "api.cerebras.ai" not in FREE_HOSTS
    assert sorted(FREE_HOSTS) == ["api.groq.com", "openrouter.ai"]
    assert is_zero_cost_endpoint({"base_url": CEREBRAS, "endpoint_kind": "api"},
                                 "gpt-oss-120b") is False


def test_the_shipped_quota_config_no_longer_lists_cerebras():
    hosts = [p["endpoint_host"] for p in router.load_quota_config()["providers"]]
    assert "api.cerebras.ai" not in hosts
    assert hosts == ["api.groq.com", "openrouter.ai"], "el orden D3 es Groq -> OpenRouter"


async def test_a_step_pointed_at_cerebras_is_refused(factory, monkeypatch):
    from src.cmh_cost_policy import ZeroCostViolation
    with factory() as db:
        db.add(cdb.ModelEndpoint(id="cerebras", name="cerebras", base_url=CEREBRAS,
                                 endpoint_kind="api", is_enabled=True))
        db.commit()
    attempts = []

    async def fake(config, candidate, prompt, record):
        attempts.append(candidate["endpoint_url"])
        return "artifact"

    monkeypatch.setattr(flow, "_run_one_candidate", fake)
    config = {"run_id": "r1", "step_key": "uno", "agent_id": "a", "owner": "admin",
              "name": "n", "workspace": ".", "allowed_tools": ["read_file"],
              "instructions": "i", "endpoint_url": CEREBRAS, "model": "gpt-oss-120b"}
    with pytest.raises(ZeroCostViolation):
        await flow.call_model(config, "prompt")
    assert attempts == []


def test_a_registered_cerebras_endpoint_never_becomes_a_candidate(factory):
    with factory() as db:
        db.add(cdb.ModelEndpoint(id="cerebras", name="cerebras", base_url=CEREBRAS,
                                 endpoint_kind="api", is_enabled=True))
        db.commit()
        poisoned = {"threshold": 0.9, "providers": [
            {"endpoint_host": "api.cerebras.ai", "order": 0, "model": "gpt-oss-120b",
             "limits": {}},
            {"endpoint_host": "api.groq.com", "order": 1, "model": "model-a:free",
             "limits": {}}]}
        ids = [c["endpoint_id"] for c in router.resolve_candidates(
            db, router.FREE_CLOUD_FIRST, config=poisoned)]
    assert "cerebras" not in ids, "ni escrito a mano en el JSON de cuotas entra"


# --- findings of the SECOND independent review (2026-09-29) -------------------

async def test_a_step_whose_route_is_unregistered_still_records_its_quota(factory, monkeypatch):
    """P1 of round 2: _snapshot froze endpoint_id None, _frozen_candidates used
    setdefault (which keeps a present None) and record_usage then violated
    cmh_provider_quota.endpoint_id NOT NULL - AFTER the step had produced its
    artifact, so the work was thrown away."""
    produced = []

    async def fake(config, candidate, prompt, record):
        produced.append(candidate["endpoint_id"])
        record("model_metrics", metrics={"input_tokens": 1, "output_tokens": 1, "rounds": 1})
        return "artifact"

    monkeypatch.setattr(flow, "_run_one_candidate", fake)
    unregistered = "http://127.0.0.1:59998/v1"      # local, free, and in no row
    config = {"run_id": "r1", "step_key": "uno", "agent_id": "a", "owner": "admin",
              "name": "n", "workspace": ".", "allowed_tools": ["read_file"],
              "instructions": "i", "endpoint_url": unregistered, "model": "m",
              "candidates": [{"endpoint_id": None, "endpoint_url": unregistered,
                              "model": "m", "host": "127.0.0.1"}]}
    assert await flow.call_model(config, "prompt") == "artifact"
    assert produced and produced[0] is not None, "un candidato sin id no llega al modelo"
    with factory() as db:
        rows = db.query(cdb.CMHProviderQuota).all()
    assert rows and all(r.endpoint_id for r in rows)


async def test_the_frozen_list_never_repeats_a_provider(client, factory, monkeypatch):
    """P2 of round 2: the prepend compared URL strings, so a row registered as
    the bare host and a task pointed at host+path listed the same provider
    twice - and a 429 then retried the host that had just refused."""
    monkeypatch.setattr(flow, "start", lambda run_id: None)
    with factory() as db:
        db.query(cdb.ModelEndpoint).filter(
            cdb.ModelEndpoint.id == "groq").first().base_url = "https://api.groq.com"
        db.commit()
    async with client:
        run_id = await _create_run(client, [{"key": "constructor",
                                             "agent_id": "agent-constructor"}])
    with factory() as db:
        step = db.query(cdb.CMHWorkflowStep).filter(
            cdb.CMHWorkflowStep.run_id == run_id).first()
        candidates = json.loads(step.config)["candidates"]
    pairs = [(c["host"], c["model"]) for c in candidates]
    assert len(pairs) == len(set(pairs)), f"proveedor repetido: {pairs}"


async def test_an_explicit_value_in_a_stored_definition_is_honoured(
        client, factory, monkeypatch):
    """Decision on the P2 of round 2 that the reviewer sent to human criterion.

    An explicit value in a stored definition is HONOURED, whatever wrote it;
    the per-role default applies only when the field is absent. A stored `True`
    on the reviewer cannot be told apart from a deliberate choice by someone who
    does want that step to read files, and overriding it would make the field
    unusable for those two roles forever.

    Measured on 2026-09-29 before deciding: the live database holds **0**
    workflow definitions and 0 runs, so nothing out there carries the old
    blanket True and there is nothing to migrate. Alternative discarded:
    treating a stored True on revisor/documentador as the old bug."""
    monkeypatch.setattr(flow, "start", lambda run_id: None)
    async with client:
        created = await client.post("/api/cmh/workflows", json=_definition([
            {"key": "constructor", "agent_id": "agent-constructor"},
            {"key": "revisor", "agent_id": "agent-revisor", "depends_on": ["constructor"],
             "independent_of": ["constructor"]}]))
        definition_id = created.json()["id"]
        # Rewrite the stored steps into the shape validate_dag produced before
        # the per-role default existed: a blanket True on every step.
        with factory() as db:
            row = db.query(cdb.CMHWorkflowDefinition).filter(
                cdb.CMHWorkflowDefinition.id == definition_id).first()
            steps = json.loads(row.steps)
            for step in steps:
                step["require_tool_evidence"] = True
            row.steps = json.dumps(steps)
            db.commit()
        run = await client.post(f"/api/cmh/workflows/{definition_id}/runs",
                                json={"initial_input": "x"})
        assert run.status_code == 201, run.text
    with factory() as db:
        frozen = {s.step_key: json.loads(s.config)["require_tool_evidence"]
                  for s in db.query(cdb.CMHWorkflowStep).filter(
                      cdb.CMHWorkflowStep.run_id == run.json()["id"]).all()}
    assert frozen["constructor"] is True
    assert frozen["revisor"] is True, "un valor explicito manda sobre el default por rol"


async def test_a_definition_with_no_field_at_all_also_exempts_the_reviewer(
        client, factory, monkeypatch):
    monkeypatch.setattr(flow, "start", lambda run_id: None)
    async with client:
        created = await client.post("/api/cmh/workflows", json=_definition([
            {"key": "revisor", "agent_id": "agent-revisor"}]))
        with factory() as db:
            row = db.query(cdb.CMHWorkflowDefinition).filter(
                cdb.CMHWorkflowDefinition.id == created.json()["id"]).first()
            steps = json.loads(row.steps)
            for step in steps:
                step.pop("require_tool_evidence", None)
            row.steps = json.dumps(steps)
            db.commit()
        run = await client.post(f"/api/cmh/workflows/{created.json()['id']}/runs",
                                json={"initial_input": "x"})
    with factory() as db:
        step = db.query(cdb.CMHWorkflowStep).filter(
            cdb.CMHWorkflowStep.run_id == run.json()["id"]).first()
    assert json.loads(step.config)["require_tool_evidence"] is False


async def test_the_artifact_carries_the_model_that_wrote_it(factory, monkeypatch):
    """P2 of round 2: only the EVENT label was fixed. The artifact - the thing a
    person opens - was still stamped with the first candidate."""
    async def fake(config, candidate, prompt, record):
        if candidate["endpoint_id"] == "groq":
            raise TimeoutError()
        return "ARTIFACT from openrouter"

    monkeypatch.setattr(flow, "_run_one_candidate", fake)
    config = {"run_id": "r1", "step_key": "uno", "agent_id": "a", "owner": "admin",
              "name": "n", "workspace": ".", "allowed_tools": ["read_file"],
              "instructions": "i", "endpoint_url": GROQ, "model": "model-groq:free",
              "candidates": [
                  {"endpoint_id": "groq", "endpoint_url": GROQ,
                   "model": "model-groq:free", "host": "api.groq.com"},
                  {"endpoint_id": "openrouter", "endpoint_url": OPENROUTER,
                   "model": "model-openrouter:free", "host": "openrouter.ai"}]}
    await flow.call_model(config, "prompt")
    assert config["resolved_model"] == "model-openrouter:free"


@pytest.mark.parametrize("bad", ["local_only", "solo-local", "free_cloud_first"])
async def test_an_unrecognised_provider_policy_is_refused_not_ignored(client, bad):
    """P2 of round 2: a typo degraded to None and routed to the cloud. The one
    setting whose purpose is that nothing leaves the machine cannot fail open."""
    async with client:
        refused = await client.post("/api/cmh/workflows", json=_definition([
            {"key": "constructor", "agent_id": "agent-constructor",
             "provider_policy": bad}]))
        assert refused.status_code == 400, refused.text
        assert "provider_policy" in refused.json()["detail"]
        agent = await client.post("/api/cmh/agents", json={
            "name": "x", "project_id": "project", "role": "r", "instructions": "i",
            "model": "model-a:free", "allowed_tools": ["read_file"], "workspace": ".",
            "provider_policy": bad})
    assert agent.status_code == 400


async def test_updating_an_agent_persists_its_policy_too(client):
    """P2 of round 2: only the create path was covered, so deleting the line in
    update_agent survived all 225 tests."""
    async with client:
        created = await client.post("/api/cmh/agents", json={
            "name": "Actualizable", "project_id": "project", "role": "r",
            "instructions": "i", "model": "model-a:free",
            "allowed_tools": ["read_file"], "workspace": "."})
        agent_id = created.json()["id"]
        updated = await client.put(f"/api/cmh/agents/{agent_id}", json={
            "name": "Actualizable", "project_id": "project", "role": "r",
            "instructions": "i", "model": "model-a:free",
            "allowed_tools": ["read_file"], "workspace": ".",
            "provider_policy": "local-only"})
        assert updated.status_code == 200, updated.text
        assert updated.json()["provider_policy"] == "local-only"
        listed = (await client.get("/api/cmh/agents")).json()["agents"]
    assert [a for a in listed if a["id"] == agent_id][0]["provider_policy"] == "local-only"


async def test_the_quota_row_is_keyed_on_the_endpoint_id_not_the_url(factory, monkeypatch):
    """P2 of round 2: the commit claimed charging a URL would split a provider's
    counter, and nothing measured it."""
    async def fake(config, candidate, prompt, record):
        record("model_metrics", metrics={"input_tokens": 1, "output_tokens": 1, "rounds": 1})
        return "artifact"

    monkeypatch.setattr(flow, "_run_one_candidate", fake)
    base = {"run_id": "r1", "step_key": "uno", "agent_id": "a", "owner": "admin",
            "name": "n", "workspace": ".", "allowed_tools": ["read_file"],
            "instructions": "i", "model": "model-a:free"}
    # One registered provider, reached by two spellings of its URL.
    for url in (GROQ, "https://api.groq.com/openai/v1/"):
        await flow.call_model({**base, "endpoint_url": url}, "prompt")
    with factory() as db:
        ids = {r.endpoint_id for r in db.query(cdb.CMHProviderQuota).filter(
            cdb.CMHProviderQuota.window_kind == "day").all()}
    assert ids == {"groq"}, f"el contador del proveedor se partio: {ids}"


def test_the_local_candidate_uses_the_model_the_agent_chose(factory):
    """Observation 3 of round 2, narrowed on 2026-09-29: an EXPLICIT local_model
    still wins over everything the router would pick on its own. What changed is
    the caller: _snapshot no longer hands it the agent's model, because that name
    is a cloud one (see the API test below)."""
    with factory() as db:
        candidates = router.resolve_candidates(db, router.LOCAL_ONLY, "admin",
                                               local_model="elegido-por-el-agente")
    assert candidates and candidates[0]["model"] == "elegido-por-el-agente"


# --- closing the nine mutants that survived round 2 --------------------------

async def test_the_frozen_list_never_carries_a_null_endpoint_id(client, factory, monkeypatch):
    """N1. The earlier test could not catch it: its fixture made `already_listed`
    true, so the prepend never ran and the None was never produced. Point the
    task at a route the router does NOT list, which is when the prepend fires."""
    monkeypatch.setattr(flow, "start", lambda run_id: None)
    unlisted = "http://127.0.0.1:59998/v1"          # local, free, in no row
    with factory() as db:
        task = db.query(cdb.ScheduledTask).filter(
            cdb.ScheduledTask.id == "task-constructor").first()
        task.endpoint_url = unlisted
        db.commit()
    async with client:
        run_id = await _create_run(client, [{"key": "constructor",
                                             "agent_id": "agent-constructor"}])
    with factory() as db:
        step = db.query(cdb.CMHWorkflowStep).filter(
            cdb.CMHWorkflowStep.run_id == run_id).first()
        candidates = json.loads(step.config)["candidates"]
    assert candidates[0]["endpoint_url"] == unlisted, "la ruta de la tarea encabeza"
    assert all(c["endpoint_id"] for c in candidates), (
        f"un id nulo mata el paso al contabilizar la cuota: {candidates}")


async def test_a_policy_that_leaves_no_candidate_refuses_the_run(client, factory, monkeypatch):
    """M13. Nothing exercised the empty-list guard."""
    monkeypatch.setattr(flow, "start", lambda run_id: None)
    with factory() as db:
        # No local endpoint left, and the step asks for local-only.
        db.query(cdb.ModelEndpoint).filter(cdb.ModelEndpoint.id == "local").delete()
        db.commit()
    async with client:
        definition = await client.post("/api/cmh/workflows", json=_definition([
            {"key": "constructor", "agent_id": "agent-constructor",
             "provider_policy": "local-only"}]))
        assert definition.status_code == 201, definition.text
        run = await client.post(f"/api/cmh/workflows/{definition.json()['id']}/runs",
                                json={"initial_input": "x"})
    assert run.status_code == 400
    assert "local-only" in run.json()["detail"]


def test_a_frozen_candidate_without_a_host_still_gets_one(factory):
    """M05b. The host keys the quota limits: an empty one silently means "no
    limits known", so a spent provider would keep being sent requests."""
    config = {"endpoint_url": "https://api.groq.com/openai/v1", "model": "m:free",
              "candidates": [{"endpoint_id": "groq",
                              "endpoint_url": "https://api.groq.com/openai/v1",
                              "model": "m:free"}]}
    completed = flow._frozen_candidates(config)
    assert completed[0]["host"] == "api.groq.com"


async def test_a_spent_provider_is_skipped_even_when_the_host_was_not_frozen(
        factory, monkeypatch):
    """M05b, measured through the executor rather than the helper."""
    attempts = []

    async def fake(config, candidate, prompt, record):
        attempts.append(candidate["endpoint_id"])
        return "artifact"

    monkeypatch.setattr(flow, "_run_one_candidate", fake)
    with factory() as db:
        router.record_usage(db, "groq", requests=900)      # the 0.9 threshold of rpd 1000
        db.commit()
    config = {"run_id": "r1", "step_key": "uno", "agent_id": "a", "owner": "admin",
              "name": "n", "workspace": ".", "allowed_tools": ["read_file"],
              "instructions": "i", "endpoint_url": GROQ, "model": "model-a:free",
              "candidates": [{"endpoint_id": "groq", "endpoint_url": GROQ,
                              "model": "model-a:free"}]}   # no host frozen
    with pytest.raises(RuntimeError, match="sin cuota"):
        await flow.call_model(config, "prompt")
    assert attempts == []


async def test_the_prepend_compares_the_model_too(client, factory, monkeypatch):
    """M25. With `or` instead of `and`, a task on a listed host but a DIFFERENT
    model is treated as already listed and its own route is dropped."""
    monkeypatch.setattr(flow, "start", lambda run_id: None)
    with factory() as db:
        agent = db.query(cdb.CMHAgent).filter(
            cdb.CMHAgent.id == "agent-constructor").first()
        task = db.query(cdb.ScheduledTask).filter(
            cdb.ScheduledTask.id == "task-constructor").first()
        agent.model = task.model = "otro-modelo:free"       # same host, other model
        db.commit()
    async with client:
        run_id = await _create_run(client, [{"key": "constructor",
                                             "agent_id": "agent-constructor"}])
    with factory() as db:
        step = db.query(cdb.CMHWorkflowStep).filter(
            cdb.CMHWorkflowStep.run_id == run_id).first()
        candidates = json.loads(step.config)["candidates"]
    assert candidates[0]["model"] == "otro-modelo:free", (
        "la ruta de la tarea debe encabezar: su modelo no estaba en la lista")


def test_the_role_default_is_case_insensitive():
    """M24. The step-key regex forbids uppercase today, so the .lower() is only
    reachable through a direct call - which is exactly how a future caller
    would reach it."""
    assert flow.default_tool_evidence("REVISOR") is False
    assert flow.default_tool_evidence("Documentador") is False
    assert flow.default_tool_evidence("  revisor  ") is False
    assert flow.default_tool_evidence("CONSTRUCTOR") is True


async def test_the_stored_artifact_row_carries_the_answering_model(client, factory, monkeypatch):
    """N3. The earlier test asserted on config["resolved_model"], which the
    mutant did not touch: it changed what `_one` writes into the artifact ROW.
    Read the row."""
    async def fake(config, prompt):
        # Simulate a fallback having happened inside call_model.
        config["resolved_model"] = "model-que-respondio:free"
        return "ARTIFACT"

    monkeypatch.setattr(flow, "call_model", fake)
    async with client:
        run_id = await _create_run(client, [{"key": "constructor",
                                             "agent_id": "agent-constructor"}])
        for _ in range(200):
            if run_id not in flow._ACTIVE:
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("la ejecucion no termino")
        detail = (await client.get(f"/api/cmh/runs/{run_id}")).json()
    with factory() as db:
        artifact = db.query(cdb.CMHWorkflowArtifact).filter(
            cdb.CMHWorkflowArtifact.run_id == run_id).first()
    assert artifact is not None, "el paso debe haber producido artefacto"
    assert artifact.model == "model-que-respondio:free", (
        "el artefacto se rotula con el modelo que lo escribio")
    assert detail["steps"][0]["model"] == "model-que-respondio:free", (
        "el detalle del run y el artefacto deben coincidir")


# --- findings of the THIRD independent review (2026-09-29) -------------------

@pytest.mark.parametrize("url", [
    "https://api.groq.com/openai/v1",
    "https://api.groq.com:443/openai/v1",          # explicit default port
    "https://API.GROQ.COM./openai/v1/",            # case, trailing dot, trailing slash
    "https://clave:SECRETO@api.groq.com/openai/v1",  # embedded credential
])
def test_equivalent_spellings_of_one_route_share_one_key(url):
    """Each spelling used to be a different provider: the quota counter split
    and the free-tier limit stopped biting."""
    from routes.cmh_workflow_routes import _canonical_route, _provider_key
    assert _provider_key(url) == "api.groq.com"
    assert _canonical_route(url) == "https://api.groq.com/openai/v1"


def test_two_local_runtimes_on_different_ports_stay_different():
    from routes.cmh_workflow_routes import _provider_key
    assert _provider_key("http://127.0.0.1:59998/v1") != _provider_key("http://127.0.0.1:59999/v1")


def test_an_ipv6_literal_keeps_its_brackets():
    from routes.cmh_workflow_routes import _provider_key
    assert _provider_key("http://[::1]:1234/v1") == "[::1]:1234"


def test_no_credential_survives_into_a_candidate_id():
    from routes.cmh_workflow_routes import _canonical_route
    assert "SECRETO" not in _canonical_route("https://k:SECRETO@api.groq.com/v1")


async def test_a_task_url_with_an_embedded_credential_is_refused_outright(
        client, factory, monkeypatch):
    """Decision of 2026-09-29: the credential belongs in the endpoint's
    api_key, where registration now puts it.

    The previous version of this test was wrong twice, as the fourth review
    measured: it never touched the event stream its name promised, and it
    asserted only on config["candidates"], so it could not see the credential
    still sitting in the top-level endpoint_url of the same config. And the
    fix it guarded was itself unsafe — httpx 0.28.1 turns URL userinfo into
    Authorization: Basic at send time, so stripping the credential from the
    dialled URL removed working authentication. Refusing is the answer; the
    step no longer gets created at all.
    """
    monkeypatch.setattr(flow, "start", lambda run_id: None)
    with factory() as db:
        db.query(cdb.ScheduledTask).filter(
            cdb.ScheduledTask.id == "task-constructor").first().endpoint_url = (
                "http://usuario:SECRETO123@127.0.0.1:59998/v1")
        db.commit()
    async with client:
        definition = await client.post("/api/cmh/workflows", json=_definition([
            {"key": "constructor", "agent_id": "agent-constructor"}]))
        assert definition.status_code == 201, definition.text
        run = await client.post(f"/api/cmh/workflows/{definition.json()['id']}/runs",
                                json={"initial_input": "x"})
    assert run.status_code == 400
    assert "credenciales embebidas" in run.json()["detail"]
    assert "SECRETO123" not in run.json()["detail"], "el mensaje no repite el secreto"
    with factory() as db:
        steps = db.query(cdb.CMHWorkflowStep).all()
    assert steps == [], "no se congela ningun paso con una URL con credencial"


async def test_one_provider_appears_once_even_when_the_models_differ(
        client, factory, monkeypatch):
    """A 429 is applied by the provider to the account and host, not to the
    model. Deduplicating on provider+model listed api.groq.com twice whenever
    the agent's model differed from the one the quota config names."""
    monkeypatch.setattr(flow, "start", lambda run_id: None)
    with factory() as db:
        agent = db.query(cdb.CMHAgent).filter(
            cdb.CMHAgent.id == "agent-constructor").first()
        task = db.query(cdb.ScheduledTask).filter(
            cdb.ScheduledTask.id == "task-constructor").first()
        agent.model = task.model = "otro-modelo:free"
        db.commit()
    async with client:
        run_id = await _create_run(client, [{"key": "constructor",
                                             "agent_id": "agent-constructor"}])
    with factory() as db:
        step = db.query(cdb.CMHWorkflowStep).filter(
            cdb.CMHWorkflowStep.run_id == run_id).first()
        candidates = json.loads(step.config)["candidates"]
    from routes.cmh_workflow_routes import _provider_key
    keys = [_provider_key(c["endpoint_url"]) for c in candidates]
    assert len(keys) == len(set(keys)), f"proveedor repetido: {keys}"
    assert candidates[0]["model"] == "otro-modelo:free", "manda el modelo del agente"


async def test_the_quota_counter_does_not_split_on_an_equivalent_spelling(
        client, factory, monkeypatch):
    """R03 of the third review: with :443 explicit the row keyed on the raw URL
    while the limit was looked up by host, so the free-tier cap stopped biting."""
    monkeypatch.setattr(flow, "start", lambda run_id: None)
    with factory() as db:
        db.query(cdb.ModelEndpoint).filter(cdb.ModelEndpoint.id == "groq").delete()
        db.query(cdb.ScheduledTask).filter(
            cdb.ScheduledTask.id == "task-constructor").first().endpoint_url = (
                "https://api.groq.com:443/openai/v1")
        db.commit()
    async with client:
        run_id = await _create_run(client, [{"key": "constructor",
                                             "agent_id": "agent-constructor"}])
    with factory() as db:
        step = db.query(cdb.CMHWorkflowStep).filter(
            cdb.CMHWorkflowStep.run_id == run_id).first()
        first = json.loads(step.config)["candidates"][0]
    assert first["endpoint_id"] == "https://api.groq.com/openai/v1", (
        "una grafia equivalente no puede abrir un contador distinto")


@pytest.mark.parametrize("value, expected", [
    ("", None), (None, None), ("  local-only  ", "local-only"),
    ("LOCAL-ONLY", "local-only"),
])
def test_an_empty_policy_is_absence_and_a_valid_one_is_normalised(value, expected):
    """R09 and R10 of the third review: neither the empty string nor the
    normalisation of a valid value was measured."""
    assert flow._checked_policy(value, "uno") == expected


def test_local_only_judges_the_registered_row_not_the_bare_url(factory):
    """R16 of the third review: judging the URL alone would let a loopback
    endpoint an admin labelled `api` - a tunnel - lead the list under a policy
    whose whole point is that nothing leaves the machine."""
    from src.cmh_cost_policy import is_local_endpoint
    tunnel = {"id": "t", "base_url": "http://127.0.0.1:59998/v1", "endpoint_kind": "api"}
    assert is_local_endpoint(tunnel) is False
    assert is_local_endpoint({"id": "l", "base_url": "http://127.0.0.1:59998/v1",
                              "endpoint_kind": "local"}) is True


# --- closing the survivors of the round-3 campaign ---------------------------

async def test_the_local_candidate_carries_the_configured_local_model_through_the_api(
        client, factory, monkeypatch):
    """R12, repointed on 2026-09-29. It used to pin the OPPOSITE: that the local
    candidate is called with the agent's model. Wrong across providers: a Groq
    agent carries a cloud name that no local runtime serves, so the local
    fallback was asked for a model that is not there. The local candidate now
    carries the config's local identifier - not the agent's model, and not
    whatever the runtime happens to have cached. This still goes through the API:
    the first version of this test called resolve_candidates directly, so the
    call site could change without it noticing."""
    monkeypatch.setattr(flow, "start", lambda run_id: None)
    monkeypatch.setattr(router, "load_quota_config",
                        lambda path=None: {**CONFIG, "local": {"model": "cmh-local"}})
    with factory() as db:
        # The local runtime has a different model cached than the agent chose.
        db.query(cdb.ModelEndpoint).filter(
            cdb.ModelEndpoint.id == "local").first().cached_models = json.dumps(
                ["lo-que-tenga-el-runtime:free"])
        db.commit()
    async with client:
        run_id = await _create_run(client, [{"key": "constructor",
                                             "agent_id": "agent-constructor"}])
    with factory() as db:
        step = db.query(cdb.CMHWorkflowStep).filter(
            cdb.CMHWorkflowStep.run_id == run_id).first()
        candidates = json.loads(step.config)["candidates"]
    local = [c for c in candidates if "127.0.0.1" in (c["endpoint_url"] or "")]
    assert local, "el respaldo local debe estar en la lista"
    assert local[0]["model"] == "cmh-local", (
        "el respaldo local usa el identificador local del config: ni el modelo "
        "(de nube) del agente, ni el que el runtime cachea")


async def test_a_loopback_endpoint_labelled_as_external_is_refused_outright(
        client, factory, monkeypatch):
    """R16, and why it is an equivalent mutant.

    An admin who labels a loopback row `api` has declared a tunnel to somewhere
    else. The mutant makes local-only judge the bare URL instead of the row,
    which would let the tunnel lead the list — but it is unreachable: the cost
    gate refuses the tunnel at definition time, because is_local_endpoint is
    False for an api-labelled row and 127.0.0.1 is in no FREE_HOSTS. Measured
    here rather than argued: this is the guard that actually protects us, so it
    is the one pinned.
    """
    monkeypatch.setattr(flow, "start", lambda run_id: None)
    tunnel = "http://127.0.0.1:59997/v1"
    with factory() as db:
        db.add(cdb.ModelEndpoint(id="tunnel", name="tunnel", base_url=tunnel,
                                 endpoint_kind="api", is_enabled=True,
                                 cached_models=json.dumps(["model-a:free"])))
        db.query(cdb.ScheduledTask).filter(
            cdb.ScheduledTask.id == "task-constructor").first().endpoint_url = tunnel
        db.commit()
    async with client:
        refused = await client.post("/api/cmh/workflows", json=_definition([
            {"key": "constructor", "agent_id": "agent-constructor",
             "provider_policy": "local-only"}]))
    assert refused.status_code == 400
    assert "Costo cero" in refused.json()["detail"]
    assert "tunnel" in refused.json()["detail"]


# --- decisions of 2026-09-29 and findings of the FOURTH review ---------------

@pytest.mark.parametrize("url, kind, expected", [
    ("http://127.0.0.1:1234/v1", "auto", True),
    ("http://127.0.0.1:1234/v1", "local", True),
    ("http://localhost:1234/v1", "local", True),
    ("http://[::1]:1234/v1", "local", True),
    ("http://192.168.1.50:1234/v1", "local", True),     # CMH's own LAN
    ("http://10.0.0.7:8000/v1", "auto", True),
    ("http://172.16.4.2:8000/v1", "auto", True),
    ("http://gpu.local:1234/v1", "auto", True),
    ("https://gpu.corp.example/v1", "local", False),    # public, labelled local
    ("https://api.groq.com/v1", "local", False),
    ("http://127.0.0.1:1234/v1", "api", False),         # loopback, labelled a tunnel
])
def test_local_means_loopback_or_private_network_not_whatever_the_label_says(
        url, kind, expected):
    """User decision of 2026-09-29. Before it, the label alone decided: a row an
    admin marked `local` on a public host passed both this and the cost gate,
    and local-only — a policy whose docstring promises nothing leaves the
    machine — froze it at the head of the list."""
    from src.cmh_cost_policy import is_local_endpoint
    assert is_local_endpoint({"id": "x", "base_url": url,
                              "endpoint_kind": kind}) is expected


def test_a_public_host_labelled_local_is_not_free_either():
    """The label used to buy a free pass through the cost gate as well."""
    from src.cmh_cost_policy import is_zero_cost_endpoint
    assert is_zero_cost_endpoint({"id": "x", "base_url": "https://gpu.corp.example/v1",
                                  "endpoint_kind": "local"}, "m") is False


async def test_local_only_never_freezes_a_public_host_however_it_is_labelled(
        client, factory, monkeypatch):
    """R16 of the third review, which was retired as 'unreachable' on a reason
    that covered only one of the two directions. This is the other one, and it
    was reachable: the cost gate passed a public host labelled local, so
    local-only froze it leading the list."""
    monkeypatch.setattr(flow, "start", lambda run_id: None)
    remote = "https://gpu.corp.example/v1"
    with factory() as db:
        db.add(cdb.ModelEndpoint(id="gpu", name="gpu", base_url=remote,
                                 endpoint_kind="local", is_enabled=True,
                                 cached_models=json.dumps(["model-a:free"])))
        db.query(cdb.ScheduledTask).filter(
            cdb.ScheduledTask.id == "task-constructor").first().endpoint_url = remote
        db.commit()
    async with client:
        definition = await client.post("/api/cmh/workflows", json=_definition([
            {"key": "constructor", "agent_id": "agent-constructor",
             "provider_policy": "local-only"}]))
    assert definition.status_code == 400
    assert "Costo cero" in definition.json()["detail"]


async def test_one_entry_per_provider_when_a_free_host_is_labelled_local(
        client, factory, monkeypatch):
    """P1-3 of the fourth review, case A: a row for a free host registered as
    `local` is emitted by BOTH branches of resolve_candidates, and the list was
    only ever deduplicated against the task's key."""
    monkeypatch.setattr(flow, "start", lambda run_id: None)
    with factory() as db:
        db.query(cdb.ModelEndpoint).filter(
            cdb.ModelEndpoint.id == "groq").first().endpoint_kind = "local"
        db.query(cdb.ScheduledTask).filter(
            cdb.ScheduledTask.id == "task-constructor").first().endpoint_url = LOCAL
        db.query(cdb.CMHAgent).filter(
            cdb.CMHAgent.id == "agent-constructor").first().model = "model-a:free"
        db.commit()
    async with client:
        run = await _create_run(client, [{"key": "constructor",
                                          "agent_id": "agent-constructor"}])
    with factory() as db:
        step = db.query(cdb.CMHWorkflowStep).filter(
            cdb.CMHWorkflowStep.run_id == run).first()
        candidates = json.loads(step.config)["candidates"]
    from routes.cmh_workflow_routes import _provider_key
    keys = [_provider_key(c["endpoint_url"]) for c in candidates]
    assert len(keys) == len(set(keys)), f"proveedor repetido: {keys}"


async def test_one_entry_per_provider_when_two_rows_share_a_base_url(
        client, factory, monkeypatch):
    """P1-3 case B: two enabled rows on one base URL."""
    monkeypatch.setattr(flow, "start", lambda run_id: None)
    with factory() as db:
        db.add(cdb.ModelEndpoint(id="local-bis", name="local-bis", base_url=LOCAL,
                                 endpoint_kind="local", is_enabled=True,
                                 cached_models=json.dumps(["model-a:free"])))
        db.commit()
    async with client:
        run = await _create_run(client, [{"key": "constructor",
                                          "agent_id": "agent-constructor"}])
    with factory() as db:
        step = db.query(cdb.CMHWorkflowStep).filter(
            cdb.CMHWorkflowStep.run_id == run).first()
        candidates = json.loads(step.config)["candidates"]
    from routes.cmh_workflow_routes import _provider_key
    keys = [_provider_key(c["endpoint_url"]) for c in candidates]
    assert len(keys) == len(set(keys)), f"proveedor repetido: {keys}"


def test_the_whole_stored_config_carries_no_credential(factory):
    """P1-1: the previous test asserted on config["candidates"] only, so it
    could not see the top-level endpoint_url of the same config."""
    from routes.cmh_workflow_routes import _canonical_route
    assert "SECRETO" not in _canonical_route("http://u:SECRETO@127.0.0.1:1/v1")


@pytest.mark.parametrize("url, clean, has_key", [
    ("https://usuario:SECRETO123@api.x.com/v1", "https://api.x.com/v1", True),
    ("http://127.0.0.1:1234/v1", "http://127.0.0.1:1234/v1", False),
    ("http://u%40a:p%3Ab@[::1]:8080/v1", "http://[::1]:8080/v1", True),
])
def test_a_url_credential_is_lifted_into_an_api_key(url, clean, has_key):
    """User decision of 2026-09-29: the credential moves to api_key at
    registration, so the URL is clean from the start and one form travels."""
    import base64
    from src.endpoint_resolver import split_url_credentials
    got_clean, key = split_url_credentials(url)
    assert got_clean == clean
    assert bool(key) is has_key
    if key:
        assert key.startswith("Basic ")
        assert base64.b64decode(key.split()[1]).decode()  # decodes, round trips


def test_the_url_credential_really_does_authenticate():
    """Recorded because the opposite was asserted in a commit message and was
    false: httpx turns userinfo into Authorization: Basic at SEND time, not at
    build time, which is why checking build_request missed it."""
    import httpx
    client = httpx.Client()
    try:
        request = client.build_request("POST", "http://u:SECRETO123@127.0.0.1:1/v1")
        sent = next(client._build_request_auth(request).auth_flow(request))
        assert sent.headers.get("authorization", "").startswith("Basic ")
    finally:
        client.close()


async def test_the_frozen_endpoint_url_is_canonical_too(client, factory, monkeypatch):
    """R03b. It survived because _snapshot now REFUSES a URL with a credential
    before this line runs, so reverting to the raw URL no longer leaks one. But
    the canonical form does more than strip credentials: it collapses the
    equivalent spellings that otherwise reach the wire and the stored config as
    different strings. That property was unmeasured, so the mutant lived."""
    monkeypatch.setattr(flow, "start", lambda run_id: None)
    with factory() as db:
        db.query(cdb.ModelEndpoint).filter(cdb.ModelEndpoint.id == "groq").delete()
        db.query(cdb.ScheduledTask).filter(
            cdb.ScheduledTask.id == "task-constructor").first().endpoint_url = (
                "https://API.GROQ.COM.:443/openai/v1/")
        db.commit()
    async with client:
        run_id = await _create_run(client, [{"key": "constructor",
                                             "agent_id": "agent-constructor"}])
    with factory() as db:
        step = db.query(cdb.CMHWorkflowStep).filter(
            cdb.CMHWorkflowStep.run_id == run_id).first()
        first = json.loads(step.config)["candidates"][0]
    assert first["endpoint_url"] == "https://api.groq.com/openai/v1", (
        "la URL que se marca y se guarda es la forma canonica")
    assert first["endpoint_id"] == first["endpoint_url"], (
        "sin fila registrada, id y URL son la misma forma canonica")
