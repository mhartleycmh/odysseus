"""Workflow routes through real FastAPI dispatch: approval, stop and resume."""

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


@pytest.fixture
def factory(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    cdb.Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(flow, "SessionLocal", session_factory)
    monkeypatch.setattr(routes, "SessionLocal", session_factory)
    monkeypatch.setattr(routes, "catalog", lambda: [{"id": "project"}])
    monkeypatch.setattr(control, "owner_is_admin_or_single_user", lambda owner: owner == "admin")
    monkeypatch.setattr(routes, "validate_task_tools", lambda tools, owner: set(tools))
    monkeypatch.setattr(routes, "validate_task_workspace",
                        lambda workspace, owner, persisted=True: workspace)
    with session_factory() as db:
        for key in ("a", "b"):
            db.add(cdb.ScheduledTask(id=f"task-{key}", owner="admin", name=key, task_type="llm",
                                     endpoint_url="http://model.invalid", model=f"model-{key}",
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

    app.include_router(routes.setup_cmh_workflow_routes())
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def idle(run_id):
    for _ in range(200):
        if run_id not in flow._ACTIVE:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("workflow task did not settle")


async def create_run(client, steps):
    definition = await client.post("/api/cmh/workflows", json={
        "name": "synthetic", "project_id": "project", "steps": steps})
    assert definition.status_code == 201, definition.text
    run = await client.post(f"/api/cmh/workflows/{definition.json()['id']}/runs",
                            json={"initial_input": "synthetic input"})
    assert run.status_code == 201, run.text
    return run.json()["id"]


async def test_approval_continues_run_through_threadpool_dispatch(client, monkeypatch):
    async def fake(config, prompt):
        return config["model"] + " artifact"
    monkeypatch.setattr(flow, "call_model", fake)
    async with client:
        run_id = await create_run(client, [
            {"key": "a", "agent_id": "agent-a"},
            {"key": "b", "agent_id": "agent-b", "depends_on": ["a"], "requires_approval": True},
        ])
        await idle(run_id)
        detail = (await client.get(f"/api/cmh/runs/{run_id}")).json()
        assert detail["status"] == "waiting_approval"
        approved = await client.post(f"/api/cmh/runs/{run_id}/steps/b/approve")
        assert approved.status_code == 200, approved.text
        await idle(run_id)
        detail = (await client.get(f"/api/cmh/runs/{run_id}")).json()
    assert detail["status"] == "completed"
    assert sorted(a["model"] for a in detail["artifacts"]) == ["model-a", "model-b"]


async def test_stop_then_resume_completes_without_repeating_finished_step(client, monkeypatch):
    release = asyncio.Event()
    calls = []

    async def fake(config, prompt):
        calls.append(config["model"])
        if config["model"] == "model-b" and not release.is_set():
            await asyncio.sleep(30)
        return config["model"] + " artifact"
    monkeypatch.setattr(flow, "call_model", fake)
    async with client:
        run_id = await create_run(client, [
            {"key": "a", "agent_id": "agent-a"},
            {"key": "b", "agent_id": "agent-b", "depends_on": ["a"]},
        ])
        for _ in range(200):
            if "model-b" in calls:
                break
            await asyncio.sleep(0.01)
        stopped = await client.post(f"/api/cmh/runs/{run_id}/stop")
        assert stopped.status_code == 200, stopped.text
        await idle(run_id)
        assert (await client.get(f"/api/cmh/runs/{run_id}")).json()["status"] == "interrupted"
        release.set()
        resumed = await client.post(f"/api/cmh/runs/{run_id}/resume")
        assert resumed.status_code == 200, resumed.text
        await idle(run_id)
        detail = (await client.get(f"/api/cmh/runs/{run_id}")).json()
    assert detail["status"] == "completed"
    assert calls == ["model-a", "model-b", "model-b"]
    assert len(detail["artifacts"]) == 2


async def test_unexpected_engine_failure_marks_run_error_instead_of_running(factory, monkeypatch):
    run_id = "broken"
    with factory() as db:
        db.add(cdb.CMHWorkflowRun(id=run_id, owner="admin", definition_id="d", project_id="project",
                                  status="pending", initial_input="x"))
        db.add(cdb.CMHWorkflowStep(id="s1", run_id=run_id, step_key="b", agent_id="agent-b",
                                   config=json.dumps({"model": "m", "instructions_version": 1}),
                                   dependencies=json.dumps([]), status="completed"))
        db.add(cdb.CMHWorkflowStep(id="s2", run_id=run_id, step_key="c", agent_id="agent-b",
                                   config=json.dumps({"model": "m", "instructions_version": 1}),
                                   dependencies=json.dumps(["b"]), status="pending"))
        db.commit()

    async def never(config, prompt):
        raise AssertionError("must not call the model without dependency artifacts")
    await flow.execute(run_id, model_call=never)
    with factory() as db:
        assert db.get(cdb.CMHWorkflowRun, run_id).status == "error"
        assert db.get(cdb.CMHWorkflowStep, "s2").error == "Dependency artifact missing"


async def test_event_stream_resumes_after_last_event_id(factory):
    from types import SimpleNamespace
    with factory() as db:
        db.add(cdb.CMHWorkflowRun(id="r", owner="admin", definition_id="d", project_id="project",
                                  status="completed", initial_input="x"))
        for kind in ("run_created", "run_started", "run_completed"):
            flow.event(db, "r", kind)
        db.commit()
        seqs = [e.seq for e in db.query(cdb.CMHWorkflowEvent).order_by(cdb.CMHWorkflowEvent.seq)]
    stream = next(r.endpoint for r in routes.setup_cmh_workflow_routes().routes
                  if r.path == "/api/cmh/runs/{run_id}/events")

    def fake_request():
        polls = iter([False])

        async def is_disconnected():
            return next(polls, True)
        return SimpleNamespace(state=SimpleNamespace(current_user="admin"), is_disconnected=is_disconnected)

    response = await stream(fake_request(), "r", after=0, last_event_id=str(seqs[0]))
    replay = "".join([chunk async for chunk in response.body_iterator])
    assert f"id: {seqs[0]}\n" not in replay
    assert f"id: {seqs[1]}\nevent: run_started\n" in replay
    assert f"id: {seqs[2]}\nevent: run_completed\n" in replay
    response = await stream(fake_request(), "r", after=seqs[1], last_event_id=None)
    assert "event: run_started" not in "".join([chunk async for chunk in response.body_iterator])
    with pytest.raises(control.HTTPException) as exc:
        await stream(fake_request(), "r", after=0, last_event_id="not-a-number")
    assert exc.value.status_code == 400


async def test_stop_leaves_an_approval_wait_and_resume_asks_again(client, monkeypatch):
    async def fake(config, prompt):
        return config["model"] + " artifact"
    monkeypatch.setattr(flow, "call_model", fake)
    async with client:
        run_id = await create_run(client, [
            {"key": "a", "agent_id": "agent-a"},
            {"key": "b", "agent_id": "agent-b", "depends_on": ["a"], "requires_approval": True},
        ])
        await idle(run_id)
        assert (await client.post(f"/api/cmh/runs/{run_id}/stop")).status_code == 200
        detail = (await client.get(f"/api/cmh/runs/{run_id}")).json()
        assert detail["status"] == "interrupted"
        assert {s["key"]: s["status"] for s in detail["steps"]}["b"] == "pending"
        assert (await client.post(f"/api/cmh/runs/{run_id}/resume")).status_code == 200
        await idle(run_id)
        detail = (await client.get(f"/api/cmh/runs/{run_id}")).json()
    assert detail["status"] == "waiting_approval"
    assert len(detail["artifacts"]) == 1


async def test_resume_releases_a_step_stranded_in_running(client, factory, monkeypatch):
    async def fake(config, prompt):
        return config["model"] + " artifact"
    monkeypatch.setattr(flow, "call_model", fake)
    async with client:
        run_id = await create_run(client, [{"key": "a", "agent_id": "agent-a"}])
        await idle(run_id)
        with factory() as db:
            db.query(cdb.CMHWorkflowArtifact).filter_by(run_id=run_id).delete()
            db.query(cdb.CMHWorkflowStep).filter_by(run_id=run_id).one().status = "running"
            db.get(cdb.CMHWorkflowRun, run_id).status = "error"
            db.commit()
        assert (await client.post(f"/api/cmh/runs/{run_id}/resume")).status_code == 200
        await idle(run_id)
        detail = (await client.get(f"/api/cmh/runs/{run_id}")).json()
    assert detail["status"] == "completed" and len(detail["artifacts"]) == 1


async def test_run_refuses_step_whose_workspace_reaches_financial_folders(client, factory):
    with factory() as db:
        db.get(cdb.CMHAgent, "agent-a").workspace = str(control.CMH_ROOT / "Modelo Financiero Nuevo")
        db.commit()
    async with client:
        definition = await client.post("/api/cmh/workflows", json={
            "name": "x", "project_id": "project", "steps": [{"key": "a", "agent_id": "agent-a"}]})
        run = await client.post(f"/api/cmh/workflows/{definition.json()['id']}/runs",
                                json={"initial_input": "synthetic"})
    assert run.status_code == 400 and "protected area" in run.json()["detail"]
