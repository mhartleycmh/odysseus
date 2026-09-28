"""Zero-cost gate (D1): the predicate, and the three places that enforce it."""

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
from src.cmh_cost_policy import (
    ZeroCostViolation, assert_zero_cost, enforced, is_local_endpoint,
    is_zero_cost_endpoint,
)

LOCAL = "http://127.0.0.1:59999/v1"
GROQ = "https://api.groq.com/openai/v1"
CEREBRAS = "https://api.cerebras.ai/v1"
OPENROUTER = "https://openrouter.ai/api/v1"
ANTHROPIC = "https://api.anthropic.com"


def ep(base_url, kind="auto", id="e1"):
    return {"id": id, "base_url": base_url, "endpoint_kind": kind}


# --- the predicate ----------------------------------------------------------

@pytest.mark.parametrize("endpoint, model, expected", [
    (ep(LOCAL, "local"), "cmh-local", True),
    (ep(LOCAL, "auto"), "cmh-local", True),            # unlabelled loopback is still local
    (ep("http://localhost:1234/v1", "auto"), "m", True),
    (ep(GROQ, "api"), "openai/gpt-oss-120b", True),
    (ep(CEREBRAS, "api"), "gpt-oss-120b", True),
    (ep(OPENROUTER, "api"), "some/model:free", True),
    (ep(OPENROUTER, "api"), "some/model", False),      # paid variant on a free host
    (ep(OPENROUTER, "api"), None, False),              # unknown model fails closed
    (ep(ANTHROPIC, "api"), "claude-sonnet-5", False),
    (ep("https://api.openai.com/v1", "api"), "gpt-4", False),
])
def test_zero_cost_classification(endpoint, model, expected):
    assert is_zero_cost_endpoint(endpoint, model) is expected


def test_a_lookalike_host_is_not_the_free_host():
    """FREE_HOSTS is an exact host match, never a suffix match."""
    assert is_zero_cost_endpoint(ep("https://api.groq.com.attacker.example/v1", "api"), "m") is False
    assert is_zero_cost_endpoint(ep("https://notapi.groq.com/v1", "api"), "m") is False


def test_an_api_labelled_loopback_is_not_local():
    """An admin who labels a route external has declared it a tunnel."""
    assert is_local_endpoint(ep(LOCAL, "api")) is False
    assert is_zero_cost_endpoint(ep(LOCAL, "api"), "m") is False


def test_assert_raises_and_names_the_route():
    with pytest.raises(ZeroCostViolation) as caught:
        assert_zero_cost(ep(ANTHROPIC, "api", id="9a76d7a3"), "claude-sonnet-5")
    message = str(caught.value)
    assert "9a76d7a3" in message and "claude-sonnet-5" in message


def test_the_flag_downgrades_the_gate_to_logging(monkeypatch):
    monkeypatch.setenv("CMH_ZERO_COST", "false")
    assert enforced() is False
    assert_zero_cost(ep(ANTHROPIC, "api"), "claude-sonnet-5")  # does not raise
    monkeypatch.setenv("CMH_ZERO_COST", "true")
    with pytest.raises(ZeroCostViolation):
        assert_zero_cost(ep(ANTHROPIC, "api"), "claude-sonnet-5")


def test_the_gate_is_on_by_default(monkeypatch):
    monkeypatch.delenv("CMH_ZERO_COST", raising=False)
    assert enforced() is True


# --- the three enforcement sites --------------------------------------------

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
    monkeypatch.setattr(control, "owner_is_admin_or_single_user", lambda owner: owner == "admin")
    monkeypatch.setattr(routes, "validate_task_tools", lambda tools, owner: set(tools))
    monkeypatch.setattr(routes, "validate_task_workspace",
                        lambda workspace, owner, persisted=True: workspace)
    monkeypatch.setattr(control, "validate_task_tools", lambda tools, owner: set(tools))
    monkeypatch.setattr(control, "validate_task_workspace",
                        lambda workspace, owner, persisted=True: workspace)
    monkeypatch.setattr(control, "protected_area", lambda path: None)
    monkeypatch.setattr(routes, "protected_area", lambda path: None)
    with session_factory() as db:
        for key, url in (("free", GROQ), ("paid", ANTHROPIC)):
            db.add(cdb.ScheduledTask(id=f"task-{key}", owner="admin", name=key, task_type="llm",
                                     endpoint_url=url, model=f"model-{key}",
                                     prompt="unused", status="paused"))
            db.add(cdb.CMHAgent(id=f"agent-{key}", owner="admin", name=key, project_id="project",
                                role=key, instructions=key, model=f"model-{key}",
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


def _agent_body(task_id, model):
    return {"name": "n", "project_id": "project", "role": "r", "instructions": "i",
            "model": model, "allowed_tools": ["read_file"], "workspace": ".",
            "task_id": task_id}


async def test_site_1_creating_an_agent_on_a_paid_endpoint_is_refused(client):
    async with client:
        paid = await client.post("/api/cmh/agents", json=_agent_body("task-paid", "model-paid"))
        assert paid.status_code == 400
        assert "Costo cero" in paid.json()["detail"]
        free = await client.post("/api/cmh/agents", json=_agent_body("task-free", "model-free"))
        assert free.status_code == 201, free.text


async def test_site_1_editing_an_agent_onto_a_paid_endpoint_is_refused(client):
    async with client:
        moved = await client.put("/api/cmh/agents/agent-free",
                                 json=_agent_body("task-paid", "model-paid"))
        assert moved.status_code == 400
        assert "Costo cero" in moved.json()["detail"]


def _definition(agent_id):
    return {"name": "d", "project_id": "project",
            "steps": [{"key": "uno", "agent_id": agent_id, "depends_on": [],
                       "independent_of": [], "requires_approval": False}]}


async def test_site_2_a_definition_on_a_paid_endpoint_is_refused(client):
    async with client:
        paid = await client.post("/api/cmh/workflows", json=_definition("agent-paid"))
        assert paid.status_code == 400
        assert "Costo cero" in paid.json()["detail"]
        free = await client.post("/api/cmh/workflows", json=_definition("agent-free"))
        assert free.status_code == 201, free.text


async def test_site_2_run_creation_refuses_a_step_moved_onto_a_paid_endpoint(client, factory):
  async with client:
    created = await client.post("/api/cmh/workflows", json=_definition("agent-free"))
    assert created.status_code == 201
    # The definition froze nothing but an agent id, so repoint the agent after
    # the fact: the snapshot gate is the one that must still catch it.
    with factory() as db:
        agent = db.query(cdb.CMHAgent).filter(cdb.CMHAgent.id == "agent-free").first()
        # The model moves with the task: _snapshot rejects a task/agent model
        # mismatch first, and that 400 would mask the cost gate behind it.
        agent.task_id, agent.model = "task-paid", "model-paid"
        db.commit()
    run = await client.post(f"/api/cmh/workflows/{created.json()['id']}/runs",
                            json={"initial_input": "x"})
    assert run.status_code == 400
    assert "Costo cero" in run.json()["detail"]


def test_site_3_a_paid_candidate_is_blocked_and_the_step_gets_no_paid_fallback(factory):
    """call_model records zero_cost_blocked per candidate and refuses to run."""
    events = []
    config = {"run_id": "r1", "step_key": "uno", "agent_id": "agent-paid", "owner": "admin",
              "name": "n", "workspace": ".", "allowed_tools": ["read_file"],
              "instructions": "i", "instructions_version": 1,
              "endpoint_url": ANTHROPIC, "model": "claude-sonnet-5"}
    blocked = flow._zero_cost_candidates(config, lambda kind, **p: events.append((kind, p)))
    assert blocked == []
    assert [kind for kind, _ in events] == ["zero_cost_blocked"]
    assert events[0][1]["endpoint_url"] == ANTHROPIC


def test_site_3_a_free_candidate_passes_without_an_event(factory):
    events = []
    config = {"run_id": "r1", "step_key": "uno", "agent_id": "agent-free", "owner": "admin",
              "endpoint_url": GROQ, "model": "openai/gpt-oss-120b"}
    allowed = flow._zero_cost_candidates(config, lambda kind, **p: events.append((kind, p)))
    assert len(allowed) == 1 and allowed[0]["endpoint_url"] == GROQ
    assert events == []


def test_site_3_the_event_is_recorded_even_when_the_gate_is_not_enforcing(factory, monkeypatch):
    """CMH_ZERO_COST=false must be diagnosable, not silent."""
    monkeypatch.setenv("CMH_ZERO_COST", "false")
    events = []
    config = {"run_id": "r1", "step_key": "uno", "agent_id": "a", "owner": "admin",
              "endpoint_url": ANTHROPIC, "model": "claude-sonnet-5"}
    assert flow._zero_cost_candidates(config, lambda kind, **p: events.append((kind, p))) == []
    assert [kind for kind, _ in events] == ["zero_cost_blocked"]


def test_site_3_the_registered_row_decides_not_the_bare_url(factory):
    """A loopback URL an admin labelled `api` is judged by the row, not the URL."""
    with factory() as db:
        db.add(cdb.ModelEndpoint(id="tunnel", name="t", base_url=LOCAL,
                                 endpoint_kind="api", is_enabled=True))
        db.commit()
    events = []
    config = {"run_id": "r1", "step_key": "uno", "agent_id": "a", "owner": "admin",
              "endpoint_url": LOCAL, "model": "m"}
    assert flow._zero_cost_candidates(config, lambda kind, **p: events.append((kind, p))) == []
    assert [kind for kind, _ in events] == ["zero_cost_blocked"]
