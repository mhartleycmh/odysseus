"""OpenRouter's model is discovered when a run is created, and the second link of
the chain finally enters the frozen list.

``config/cmh_free_quotas.json`` gives OpenRouter ``model: null`` because the free
catalogue turns over, and ``resolve_candidates`` skips a provider without a model.
Nothing ever filled it in: ``pick_openrouter_free_model`` had no caller outside its
own tests, so with U1, U2 and U4 done the real chain was Groq -> LM Studio and the
blueprint's Groq -> OpenRouter -> LM Studio existed only on paper.

Only the network is fake, through ``llm_core._get_http_client``. The key is a
recognisable dummy so the tests can prove it is sent as a header and appears in
no note, no event and no frozen config.
"""

import asyncio
import json
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as cdb
import src.cmh_provider_router as router
import src.llm_core as llm_core
from routes import cmh_control_routes as control
from routes import cmh_workflow_routes as routes
from src import cmh_workflows as flow
from src.cmh_provider_router import (
    FREE_CLOUD_FIRST, discover_free_models, resolve_candidates,
)

SECRET = "sk-or-DUMMY-KEY-FOR-TESTS"
GROQ = "https://api.groq.com/openai/v1"
OPENROUTER = "https://openrouter.ai/api/v1"
LOCAL = "http://127.0.0.1:59999/v1"
USER_PATH = "/api/v1/models/user"
GENERAL_PATH = "/api/v1/models"
T0 = datetime(2026, 9, 29, 12, 0)

CONFIG = {
    "threshold": 0.9,
    "discovery": {"ttl_s": 21600, "timeout_s": 15},
    "providers": [
        {"endpoint_host": "api.groq.com", "order": 1, "model": "openai/gpt-oss-120b", "limits": {}},
        {"endpoint_host": "openrouter.ai", "order": 2, "model": None, "limits": {}},
    ],
}


def _model(model_id, context, tools=True):
    return {"id": model_id, "context_length": context,
            "supported_parameters": ["tools", "temperature"] if tools else ["temperature"]}


CATALOGUE = {"data": [
    _model("small/model:free", 8_000),
    _model("big/model:free", 128_000),
    _model("huge/model", 1_000_000),              # not :free
    _model("huger/model:free", 2_000_000, tools=False),  # no tool calling
]}


class Catalogue:
    """What OpenRouter answers on each path, and who asked."""

    def __init__(self):
        self.responses = {}
        self.requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append((path, request.headers.get("authorization")))
        outcome = self.responses.get(path)
        if callable(outcome):
            raise outcome(request)
        if outcome is None:
            return httpx.Response(404, json={"error": "not found"})
        status, body = outcome
        return httpx.Response(status, json=body)

    def paths(self):
        return [p for p, _ in self.requests]


@pytest.fixture
def world(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(cdb.ModelEndpoint(id="groq", name="groq", base_url=GROQ,
                                      endpoint_kind="api", is_enabled=True, api_key="gsk-DUMMY"))
        session.add(cdb.ModelEndpoint(id="orr", name="orr", base_url=OPENROUTER,
                                      endpoint_kind="api", is_enabled=True, api_key=SECRET))
        session.add(cdb.ModelEndpoint(id="lms", name="lms", base_url=LOCAL,
                                      endpoint_kind="local", is_enabled=True,
                                      cached_models=json.dumps(["cmh-local"])))
        session.commit()
    net = Catalogue()
    client = httpx.AsyncClient(transport=httpx.MockTransport(net.handler))
    monkeypatch.setattr(llm_core, "_get_http_client", lambda *a, **k: client)
    router.clear_discovery_cache()
    yield factory, net, tmp_path
    router.clear_discovery_cache()
    engine.dispose()


# --- what discovery asks, and in which order --------------------------------

async def test_the_accounts_own_list_is_asked_first_and_its_pick_follows_the_rule(world):
    factory, net, _ = world
    net.responses[USER_PATH] = (200, CATALOGUE)
    with factory() as db:
        found, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert found == {"openrouter.ai": "big/model:free"}  # longest context among :free WITH tools
    assert net.paths() == [USER_PATH]
    assert notes == [{"provider": "openrouter.ai", "outcome": "ok", "model": "big/model:free",
                      "source": "models/user", "reason": None}]


async def test_the_key_travels_as_a_header_and_appears_in_no_note(world):
    factory, net, _ = world
    net.responses[USER_PATH] = (200, CATALOGUE)
    with factory() as db:
        _, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert net.requests[0][1] == f"Bearer {SECRET}"
    assert SECRET not in json.dumps(notes)


async def test_the_general_list_is_used_only_when_the_accounts_list_is_not_there(world):
    factory, net, _ = world
    net.responses[GENERAL_PATH] = (200, CATALOGUE)  # /models/user answers 404
    with factory() as db:
        found, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert found == {"openrouter.ai": "big/model:free"}
    assert net.paths() == [USER_PATH, GENERAL_PATH]
    assert notes[0]["source"] == "models"


async def test_an_empty_accounts_list_does_not_widen_to_the_general_one(world):
    """A 200 with nothing eligible is the account saying no. Asking the unfiltered
    catalogue would pick a model the account's own privacy settings exclude."""
    factory, net, _ = world
    net.responses[USER_PATH] = (200, {"data": [_model("huge/model", 1_000_000)]})
    net.responses[GENERAL_PATH] = (200, CATALOGUE)  # would offer a good one
    with factory() as db:
        found, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert found == {}
    assert GENERAL_PATH not in net.paths()
    assert notes[0]["outcome"] == "failed" and "account" in notes[0]["reason"]


# --- failures leave the provider out and say why ----------------------------

async def test_a_rejected_key_fails_the_discovery_and_says_why_without_the_key(world):
    factory, net, _ = world
    net.responses[USER_PATH] = (401, {"error": "bad key"})
    net.responses[GENERAL_PATH] = (401, {"error": "bad key"})
    with factory() as db:
        found, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert found == {}
    assert notes[0]["outcome"] == "failed" and notes[0]["reason"] == "http:401"
    assert SECRET not in json.dumps(notes)


async def test_a_network_failure_does_not_raise_and_is_reported(world):
    factory, net, _ = world
    net.responses[USER_PATH] = lambda request: httpx.ConnectError("simulated", request=request)
    net.responses[GENERAL_PATH] = lambda request: httpx.ConnectError("simulated", request=request)
    with factory() as db:
        found, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert found == {}
    assert notes[0]["reason"] == "connection:ConnectError"


async def test_a_failed_discovery_is_not_cached(world):
    factory, net, _ = world
    with factory() as db:
        await discover_free_models(db, config=CONFIG, at=T0)
        net.responses[USER_PATH] = (200, CATALOGUE)
        found, _ = await discover_free_models(db, config=CONFIG, at=T0 + timedelta(seconds=5))
    assert found == {"openrouter.ai": "big/model:free"}


# --- cost, cache, precedence -------------------------------------------------

async def test_the_result_is_reused_within_the_ttl_and_asked_again_after_it(world):
    factory, net, _ = world
    net.responses[USER_PATH] = (200, CATALOGUE)
    with factory() as db:
        await discover_free_models(db, config=CONFIG, at=T0)
        found, notes = await discover_free_models(db, config=CONFIG, at=T0 + timedelta(hours=1))
        assert found == {"openrouter.ai": "big/model:free"}
        assert notes[0]["outcome"] == "cached"
        assert len(net.requests) == 1
        await discover_free_models(db, config=CONFIG, at=T0 + timedelta(hours=7))
    assert len(net.requests) == 2


async def test_a_model_written_in_the_config_is_never_asked_for_nor_replaced(world):
    factory, net, _ = world
    pinned = json.loads(json.dumps(CONFIG))
    pinned["providers"][1]["model"] = "pinned/model:free"
    with factory() as db:
        found, notes = await discover_free_models(db, config=pinned, at=T0)
        candidates = resolve_candidates(db, FREE_CLOUD_FIRST, config=pinned,
                                        discovered={"openrouter.ai": "other/model:free"})
    assert found == {} and notes == [] and net.requests == []
    assert [c["model"] for c in candidates if c["endpoint_id"] == "orr"] == ["pinned/model:free"]


async def test_no_registered_account_means_no_request(world):
    factory, net, _ = world
    with factory() as db:
        db.query(cdb.ModelEndpoint).filter(cdb.ModelEndpoint.id == "orr").delete()
        db.commit()
        found, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert found == {} and notes == [] and net.requests == []


def test_a_discovered_model_enters_second_and_a_missing_one_leaves_the_provider_out(world):
    factory, _, _ = world
    with factory() as db:
        with_it = resolve_candidates(db, FREE_CLOUD_FIRST, config=CONFIG,
                                     discovered={"openrouter.ai": "big/model:free"})
        without = resolve_candidates(db, FREE_CLOUD_FIRST, config=CONFIG)
    assert [c["endpoint_id"] for c in with_it] == ["groq", "orr", "lms"]
    assert [c["endpoint_id"] for c in without] == ["groq", "lms"]


def test_the_cost_gate_still_refuses_a_discovered_model_that_is_not_free(world):
    factory, _, _ = world
    with factory() as db:
        candidates = resolve_candidates(db, FREE_CLOUD_FIRST, config=CONFIG,
                                        discovered={"openrouter.ai": "huge/model"})
    assert "orr" not in [c["endpoint_id"] for c in candidates]


def test_the_shipped_config_declares_the_discovery_knobs_and_leaves_openrouter_open():
    """The file is what runs. A rule with no knob would fall back to code constants."""
    settings = router.load_quota_config()
    assert set(settings["discovery"]) == {"ttl_s", "timeout_s"}
    openrouter = router.provider_for_host(settings, "openrouter.ai")
    assert openrouter["model"] is None


# --- through create_run ------------------------------------------------------

@pytest.fixture
def api(world, monkeypatch):
    factory, net, tmp_path = world
    monkeypatch.setattr(flow, "SessionLocal", factory)
    monkeypatch.setattr(routes, "SessionLocal", factory)
    monkeypatch.setattr(routes, "catalog", lambda: [{"id": "project"}])
    monkeypatch.setattr(control, "owner_is_admin_or_single_user", lambda owner: owner == "admin")
    monkeypatch.setattr(routes, "validate_task_tools", lambda tools, owner: set(tools))
    monkeypatch.setattr(routes, "validate_task_workspace",
                        lambda workspace, owner, persisted=True: workspace)

    async def fake(config, prompt):
        return "artifact"

    monkeypatch.setattr(flow, "call_model", fake)
    with factory() as db:
        db.add(cdb.ScheduledTask(id="task-a", owner="admin", name="a", task_type="llm",
                                 endpoint_url=GROQ, model="openai/gpt-oss-120b",
                                 prompt="unused", status="paused"))
        db.add(cdb.CMHAgent(id="agent-a", owner="admin", name="a", project_id="project",
                            role="a", instructions="a", model="openai/gpt-oss-120b",
                            allowed_tools=json.dumps(["read_file"]), workspace=str(tmp_path),
                            status="active", task_id="task-a"))
        db.commit()
    app = FastAPI()

    @app.middleware("http")
    async def as_admin(request, call_next):
        request.state.current_user = "admin"
        return await call_next(request)

    app.include_router(routes.setup_cmh_workflow_routes())
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    yield client, factory, net
    flow._ACTIVE.clear()


async def _create_run(client):
    definition = await client.post("/api/cmh/workflows", json={
        "name": "synthetic", "project_id": "project",
        "steps": [{"key": "a", "agent_id": "agent-a"}]})
    assert definition.status_code == 201, definition.text
    run = await client.post(f"/api/cmh/workflows/{definition.json()['id']}/runs",
                            json={"initial_input": "synthetic input"})
    assert run.status_code == 201, run.text
    run_id = run.json()["id"]
    for _ in range(200):
        if run_id not in flow._ACTIVE:
            break
        await asyncio.sleep(0.01)
    return run_id


def _stored(factory, run_id):
    with factory() as db:
        step = db.query(cdb.CMHWorkflowStep).filter(cdb.CMHWorkflowStep.run_id == run_id).one()
        events = [(e.kind, json.loads(e.payload)) for e in db.query(cdb.CMHWorkflowEvent).filter(
            cdb.CMHWorkflowEvent.run_id == run_id).all()]
        return step.config, events


async def test_a_run_freezes_openrouter_with_the_model_discovered_for_it(api):
    client, factory, net = api
    net.responses[USER_PATH] = (200, CATALOGUE)
    async with client:
        run_id = await _create_run(client)
    config, events = _stored(factory, run_id)
    frozen = json.loads(config)["candidates"]
    # The local candidate's own model name is a separate capacity (3.3b.3): only
    # its position is pinned here.
    assert [(c["endpoint_id"], c["model"]) for c in frozen[:2]] == [
        ("groq", "openai/gpt-oss-120b"), ("orr", "big/model:free")]
    assert [c["endpoint_id"] for c in frozen] == ["groq", "orr", "lms"]
    discovery = [payload for kind, payload in events if kind == "provider_discovery"]
    assert discovery == [{"provider": "openrouter.ai", "outcome": "ok", "model": "big/model:free",
                          "source": "models/user", "reason": None}]
    assert SECRET not in config and SECRET not in json.dumps(events)


async def test_a_failed_discovery_still_creates_the_run_and_the_event_says_why(api):
    client, factory, net = api
    net.responses[USER_PATH] = (401, {"error": "bad key"})
    net.responses[GENERAL_PATH] = (401, {"error": "bad key"})
    async with client:
        run_id = await _create_run(client)
    config, events = _stored(factory, run_id)
    assert "orr" not in [c["endpoint_id"] for c in json.loads(config)["candidates"]]
    discovery = [payload for kind, payload in events if kind == "provider_discovery"]
    assert len(discovery) == 1 and discovery[0]["outcome"] == "failed"
    assert discovery[0]["reason"] == "http:401"
    assert SECRET not in config and SECRET not in json.dumps(events)
