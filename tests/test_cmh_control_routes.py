"""CMH catalog and agent registry keep source files read-only and enforce scope."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as cdb
from routes import cmh_control_routes as control


@pytest.fixture
def api(monkeypatch, tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    index = root / "_control" / "INDICE.md"
    index.parent.mkdir()
    project = root / "Project"
    project.mkdir()
    card = project / "00_Proyecto.md"
    card.write_text("# Canonical card\n", encoding="utf-8")
    index.write_text("| Project | [Ficha](<../Project/00_Proyecto.md>) | Activo |\n", encoding="utf-8")
    monkeypatch.setattr(control, "CMH_ROOT", root)
    monkeypatch.setattr(control, "INDEX_PATH", index)
    monkeypatch.setattr(control, "owner_is_admin_or_single_user", lambda owner: owner == "admin")
    monkeypatch.setattr("src.tool_security.owner_is_admin_or_single_user", lambda owner: owner == "admin")
    engine = create_engine("sqlite:///:memory:")
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(control, "SessionLocal", factory)
    router = control.setup_cmh_control_routes()

    def endpoint(method, path):
        return next(r.endpoint for r in router.routes if r.path == path and method in r.methods)

    yield endpoint, root, card, factory
    engine.dispose()


def request(owner="admin"):
    return SimpleNamespace(state=SimpleNamespace(current_user=owner))


def test_catalog_and_agent_lifecycle(api):
    endpoint, root, card, factory = api
    projects = endpoint("GET", "/api/cmh/projects")(request())["projects"]
    assert len(projects) == 1
    assert projects[0]["id"] == "project"
    assert projects[0]["card_path"] == str(card)
    assert endpoint("GET", "/api/cmh/projects/{project_id}")(request(), "project")["card_text"] == "# Canonical card\n"
    body = control.AgentInput(name="Researcher", role="Research", instructions="Read synthetic files", model="test-model", project_id="project", workspace=str(root / "Project"), allowed_tools=["read_file", "ls"])
    created = endpoint("POST", "/api/cmh/agents")(request(), body)
    assert created["status"] == "paused"
    assert created["instructions_version"] == 1
    assert endpoint("GET", "/api/cmh/agents")(request())["agents"][0]["id"] == created["id"]
    assert endpoint("POST", "/api/cmh/agents/{agent_id}/resume")(request(), created["id"])["status"] == "active"
    body.instructions = "Read only approved files"
    updated = endpoint("PUT", "/api/cmh/agents/{agent_id}")(request(), created["id"], body)
    assert updated["instructions_version"] == 2
    assert endpoint("POST", "/api/cmh/agents/{agent_id}/pause")(request(), created["id"])["status"] == "paused"
    assert card.read_text(encoding="utf-8") == "# Canonical card\n"


def test_catalog_and_registry_reject_invalid_scope(api, tmp_path):
    endpoint, _, card, _ = api
    with pytest.raises(HTTPException) as exc:
        endpoint("GET", "/api/cmh/projects")(request("other"))
    assert exc.value.status_code == 403
    body = control.AgentInput(name="A", role="Reader", instructions="Read", project_id="missing", allowed_tools=[])
    with pytest.raises(HTTPException) as exc:
        endpoint("POST", "/api/cmh/agents")(request(), body)
    assert exc.value.status_code == 400
    body.project_id = "project"
    body.workspace = str(tmp_path)
    body.allowed_tools = ["tool_that_does_not_exist"]
    with pytest.raises(HTTPException) as exc:
        endpoint("POST", "/api/cmh/agents")(request(), body)
    assert exc.value.status_code == 400
    assert card.read_text(encoding="utf-8") == "# Canonical card\n"


def test_project_shows_only_explicitly_linked_task_runs(api):
    endpoint, root, _, factory = api
    with factory() as db:
        db.add(cdb.ScheduledTask(id="task-a", owner="admin", name="Research", task_type="llm"))
        db.add(cdb.ScheduledTask(id="task-b", owner="other", name="Other", task_type="llm"))
        db.commit()
        db.add(cdb.TaskRun(id="run-a", task_id="task-a", status="success", model="model-a"))
        db.commit()
    body = control.AgentInput(name="Researcher", role="Research", instructions="Read", project_id="project", workspace=str(root / "Project"), task_id="task-a")
    agent = endpoint("POST", "/api/cmh/agents")(request(), body)
    assert agent["task_id"] == "task-a"
    detail = endpoint("GET", "/api/cmh/projects/{project_id}")(request(), "project")
    assert [run["id"] for run in detail["recent_runs"]] == ["run-a"]
    body.task_id = "task-b"
    with pytest.raises(HTTPException) as exc:
        endpoint("PUT", "/api/cmh/agents/{agent_id}")(request(), agent["id"], body)
    assert exc.value.status_code == 400
