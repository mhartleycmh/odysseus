"""Scheduled workspaces persist, retain owner gates, and fail closed."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import core.database as cdb
from routes.task import task_routes
from src.task_scheduler import TaskScheduler
from src.task_workspace import TaskWorkspaceError, validate_task_workspace


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setattr(
        "src.tool_security.owner_is_admin_or_single_user",
        lambda owner: owner == "admin",
    )


@pytest.fixture
def api(monkeypatch, admin):
    engine = create_engine("sqlite:///:memory:")
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(task_routes, "SessionLocal", factory)
    router = task_routes.setup_task_routes(SimpleNamespace())

    def endpoint(method, path):
        return next(r.endpoint for r in router.routes if r.path == path and method in r.methods)

    yield endpoint, factory
    engine.dispose()


def request(owner="admin"):
    return SimpleNamespace(state=SimpleNamespace(current_user=owner))


async def test_workspace_create_update_clear_and_owner_gate(api, tmp_path):
    endpoint, factory = api
    create = endpoint("POST", "/api/tasks")
    update = endpoint("PUT", "/api/tasks/{task_id}")
    result = await create(request(), task_routes.TaskCreate(
        name="Pilot", prompt="Inspect", trigger_type="webhook", workspace=str(tmp_path),
    ))
    assert result["workspace"] == str(tmp_path.resolve())
    with factory() as db:
        assert db.get(cdb.ScheduledTask, result["id"]).workspace == str(tmp_path.resolve())
    with pytest.raises(HTTPException) as exc:
        await update(request("other"), result["id"], task_routes.TaskUpdate(workspace=""))
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        await update(request(), result["id"], task_routes.TaskUpdate(task_type="research"))
    assert exc.value.status_code == 400
    child = tmp_path / "new"
    child.mkdir()
    result = await update(request(), result["id"], task_routes.TaskUpdate(workspace=str(child)))
    assert result["workspace"] == str(child.resolve())
    result = await update(request(), result["id"], task_routes.TaskUpdate(workspace=""))
    assert result["workspace"] is None


@pytest.mark.parametrize("owner,kind,invalid,status", [
    ("other", "llm", False, 403),
    ("admin", "research", False, 400),
    ("admin", "llm", True, 400),
])
async def test_create_rejects_unsupported_workspace(api, tmp_path, owner, kind, invalid, status):
    endpoint, factory = api
    path = tmp_path / "missing" if invalid else tmp_path
    with pytest.raises(HTTPException) as exc:
        await endpoint("POST", "/api/tasks")(request(owner), task_routes.TaskCreate(
            name="Pilot", prompt="Inspect", trigger_type="webhook",
            task_type=kind, workspace=str(path),
        ))
    assert exc.value.status_code == status
    with factory() as db:
        assert db.query(cdb.ScheduledTask).count() == 0


def task(path):
    return SimpleNamespace(
        workspace=str(path), owner="admin", prompt="Inspect", name="Pilot",
        crew_member_id=None, endpoint_url="http://endpoint", model="model",
        session_id="session", max_steps=1, character_id=None,
    )


async def test_deleted_workspace_never_calls_model(monkeypatch, tmp_path, admin):
    model = AsyncMock()
    monkeypatch.setattr("src.task_endpoint.task_llm_call_async", model)
    scheduler = TaskScheduler(session_manager=None)
    with pytest.raises(TaskWorkspaceError):
        await scheduler._execute_llm_task(task(tmp_path / "missing"), None)
    model.assert_not_awaited()


async def test_workspace_error_during_execution_does_not_fall_back(monkeypatch, tmp_path, admin):
    model = AsyncMock()
    monkeypatch.setattr("src.task_endpoint.task_llm_call_async", model)
    monkeypatch.setattr("src.tool_index.get_tool_index", lambda: None)
    scheduler = TaskScheduler(session_manager=None)
    scheduler._run_agent_loop = AsyncMock(side_effect=TaskWorkspaceError("workspace removed"))
    with pytest.raises(TaskWorkspaceError):
        await scheduler._execute_llm_task(task(tmp_path.resolve()), None)
    model.assert_not_awaited()


def test_runtime_rechecks_owner_privileges(tmp_path, admin):
    with pytest.raises(PermissionError):
        validate_task_workspace(str(tmp_path), "other", persisted=True)


def test_runtime_rejects_changed_canonical_target(monkeypatch, tmp_path, admin):
    monkeypatch.setattr("src.tool_execution.vet_workspace", lambda raw: str(tmp_path / "other"))
    with pytest.raises(TaskWorkspaceError, match="changed"):
        validate_task_workspace(str(tmp_path), "admin", persisted=True)


@pytest.mark.parametrize("rebuild", [False, True])
def test_workspace_migration_preserves_existing_rows_and_is_repeatable(monkeypatch, rebuild):
    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(cdb, "engine", engine)
    try:
        with engine.begin() as conn:
            if rebuild:
                conn.execute(text("""
                    CREATE TABLE scheduled_tasks (
                        id VARCHAR PRIMARY KEY, owner VARCHAR, name VARCHAR NOT NULL,
                        prompt TEXT NOT NULL, schedule VARCHAR, scheduled_time VARCHAR,
                        scheduled_day INTEGER, scheduled_date DATETIME, next_run DATETIME,
                        last_run DATETIME, status VARCHAR, output_target VARCHAR,
                        session_id VARCHAR, model VARCHAR, endpoint_url VARCHAR,
                        run_count INTEGER, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
                    )
                """))
                conn.execute(text("""
                    INSERT INTO scheduled_tasks (id, name, prompt, created_at, updated_at)
                    VALUES ('old', 'Legacy', 'Keep me', '2026-01-01', '2026-01-01')
                """))
            else:
                conn.execute(text("CREATE TABLE scheduled_tasks (id VARCHAR PRIMARY KEY, prompt TEXT)"))
                conn.execute(text("INSERT INTO scheduled_tasks VALUES ('old', 'Keep me')"))
        cdb._migrate_add_task_automation_columns()
        cdb._migrate_add_task_automation_columns()
        with engine.connect() as conn:
            row = conn.execute(text("SELECT id, prompt, workspace FROM scheduled_tasks")).one()
            assert tuple(row) == ("old", "Keep me", None)
    finally:
        engine.dispose()
