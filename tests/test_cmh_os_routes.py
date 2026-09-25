"""Agentic OS page (/cmh/os): public config, page route, static integrity, and
the contract between the real /api/cmh handlers and the samples the UI tests use."""

import hashlib
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as cdb
from routes import cmh_control_routes as control
from routes import cmh_memory_routes as memory
from routes import cmh_os_routes as os_routes
from routes import cmh_workflow_routes as workflow_routes
from src import cmh_workflows as flow

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static" / "cmh-os"
SAMPLES = json.loads((ROOT / "tests" / "cmh_os" / "fixtures" / "api_samples.json").read_text(encoding="utf-8"))


def request(owner="admin"):
    return SimpleNamespace(state=SimpleNamespace(current_user=owner))


def endpoint_of(router, method, path):
    return next(r.endpoint for r in router.routes if r.path == path and method in r.methods)


# --- public config ---------------------------------------------------------

def test_config_requires_a_signed_in_user():
    config = endpoint_of(os_routes.setup_cmh_os_routes(), "GET", "/api/cmh/os/config")
    with pytest.raises(HTTPException) as exc:
        config(request(owner=None))
    assert exc.value.status_code == 401


@pytest.mark.parametrize(("enabled", "mode", "expected"), [
    (None, None, {"ui_enabled": True, "default_mode": "auto"}),
    ("false", "demo", {"ui_enabled": False, "default_mode": "demo"}),
    ("TRUE", "Demo ", {"ui_enabled": True, "default_mode": "demo"}),
    ("0", "anything-else", {"ui_enabled": False, "default_mode": "auto"}),
])
def test_config_reads_only_the_two_public_variables(monkeypatch, enabled, mode, expected):
    for name, value in (("CMH_OS_UI_ENABLED", enabled), ("CMH_OS_DEFAULT_MODE", mode)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-never-appear")
    body = endpoint_of(os_routes.setup_cmh_os_routes(), "GET", "/api/cmh/os/config")(request())
    assert body == expected
    assert set(body) == set(SAMPLES["os_config"])


# --- page route through the real app --------------------------------------

def _serve_page(tmp_path, enabled):
    env = os.environ.copy()
    env.update({
        "AUTH_ENABLED": "true", "CHROMADB_CONNECT_TIMEOUT": "0.01", "CHROMADB_HOST": "127.0.0.1", "CHROMADB_PORT": "9",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}", "LOCALHOST_BYPASS": "false", "ODYSSEUS_DATA_DIR": str(tmp_path),
        "ODYSSEUS_DISABLE_MCP": "1", "OPENAI_API_KEY": "", "PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1",
        "CMH_OS_UI_ENABLED": enabled,
    })
    probe = textwrap.dedent("""
        import asyncio, json
        from types import SimpleNamespace
        from fastapi import HTTPException
        import app as app_module
        route = next(r for r in app_module.app.routes if getattr(r, "path", None) == "/cmh/os")
        req = SimpleNamespace(state=SimpleNamespace(csp_nonce="nonce-test"))
        try:
            response = asyncio.run(route.endpoint(req))
            print(json.dumps({"status": response.status_code, "body": response.body.decode()}))
        except HTTPException as exc:
            print(json.dumps({"status": exc.status_code, "body": ""}))
    """)
    result = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_page_route_serves_the_app_and_honours_the_flag(tmp_path):
    served = _serve_page(tmp_path / "on", "true")
    assert served["status"] == 200
    assert 'src="/static/cmh-os/js/main.js"' in served["body"]
    assert 'type="module"' in served["body"]
    assert _serve_page(tmp_path / "off", "false")["status"] == 404


# --- static integrity ------------------------------------------------------

def test_index_references_existing_assets_and_no_inline_script():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="(/static/[^"]+)"', html)
    assert refs, "index.html references no assets"
    for ref in refs:
        assert (ROOT / ref.lstrip("/")).is_file(), ref
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)


def test_official_logo_is_the_unmodified_brand_file():
    data = (STATIC / "assets" / "logo-cmh.png").read_bytes()
    assert hashlib.sha256(data).hexdigest().startswith("4358872912c35db8")
    width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    assert (width, height) == (460, 189)
    assert round(width / height, 2) == 2.43


def test_shipped_ui_contains_no_credentials():
    pattern = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{8,}|ody_[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})")
    offenders = [str(p) for p in STATIC.rglob("*") if p.is_file() and p.suffix in {".js", ".css", ".html", ".json"}
                 and pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


# --- contract: real handlers return the keys the UI samples use -----------

@pytest.fixture
def control_api(monkeypatch, tmp_path):
    root = tmp_path / "vault"
    (root / "_control").mkdir(parents=True)
    project = root / "Project"
    project.mkdir()
    (project / "00_Proyecto.md").write_text("# Canonical card\n", encoding="utf-8")
    (root / "_control" / "INDICE.md").write_text("| Project | [Ficha](<../Project/00_Proyecto.md>) | Activo |\n", encoding="utf-8")
    monkeypatch.setattr(control, "CMH_ROOT", root)
    monkeypatch.setattr(control, "INDEX_PATH", root / "_control" / "INDICE.md")
    monkeypatch.setattr(control, "MANAGED_PROJECTS", root / "Managed")
    monkeypatch.setattr(control, "owner_is_admin_or_single_user", lambda owner: owner == "admin")
    monkeypatch.setattr("src.tool_security.owner_is_admin_or_single_user", lambda owner: owner == "admin")
    engine = create_engine("sqlite:///:memory:")
    cdb.Base.metadata.create_all(engine)
    monkeypatch.setattr(control, "SessionLocal", sessionmaker(bind=engine))
    router = control.setup_cmh_control_routes()
    yield router, root
    engine.dispose()


def test_projects_and_agents_match_the_ui_samples(control_api):
    router, root = control_api
    body = control.AgentInput(name="Researcher", role="Research", instructions="Read synthetic files", model="m",
                              project_id="project", workspace=str(root / "Project"), allowed_tools=["read_file", "ls"])
    endpoint_of(router, "POST", "/api/cmh/agents")(request(), body)
    agents = endpoint_of(router, "GET", "/api/cmh/agents")(request())
    assert set(agents) == set(SAMPLES["agents"])
    assert set(agents["agents"][0]) == set(SAMPLES["agents"]["agents"][0])
    projects = endpoint_of(router, "GET", "/api/cmh/projects")(request())
    assert set(projects["projects"][0]) == set(SAMPLES["projects"]["projects"][0])


@pytest.fixture
def workflow_client(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(flow, "SessionLocal", factory)
    monkeypatch.setattr(workflow_routes, "SessionLocal", factory)
    monkeypatch.setattr(workflow_routes, "catalog", lambda: [{"id": "project"}])
    monkeypatch.setattr(control, "owner_is_admin_or_single_user", lambda owner: owner == "admin")
    monkeypatch.setattr(workflow_routes, "validate_task_tools", lambda tools, owner: set(tools))
    monkeypatch.setattr(workflow_routes, "validate_task_workspace", lambda workspace, owner, persisted=True: workspace)
    with factory() as db:
        for key in ("a", "b"):
            db.add(cdb.ScheduledTask(id=f"task-{key}", owner="admin", name=key, task_type="llm", endpoint_url="http://model.invalid",
                                     model=f"model-{key}", prompt="unused", status="paused"))
            db.add(cdb.CMHAgent(id=f"agent-{key}", owner="admin", name=key, project_id="project", role=key, instructions=key,
                                model=f"model-{key}", allowed_tools=json.dumps(["read_file"]), workspace=str(tmp_path),
                                status="active", task_id=f"task-{key}"))
        db.commit()

    async def fake(config, prompt):
        return config["model"] + " artifact"
    monkeypatch.setattr(flow, "call_model", fake)
    app = FastAPI()

    @app.middleware("http")
    async def as_admin(req, call_next):
        req.state.current_user = "admin"
        return await call_next(req)
    app.include_router(workflow_routes.setup_cmh_workflow_routes())
    yield httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test"), factory
    flow._ACTIVE.clear()
    engine.dispose()


async def test_workflow_runs_and_events_match_the_ui_samples(workflow_client):
    import asyncio
    client, factory = workflow_client
    async with client:
        definition = await client.post("/api/cmh/workflows", json={"name": "synthetic", "project_id": "project", "steps": [
            {"key": "a", "agent_id": "agent-a"}, {"key": "b", "agent_id": "agent-b", "depends_on": ["a"], "requires_approval": True}]})
        assert definition.status_code == 201, definition.text
        run = await client.post(f"/api/cmh/workflows/{definition.json()['id']}/runs", json={"initial_input": "synthetic input"})
        run_id = run.json()["id"]
        for _ in range(200):
            if run_id not in flow._ACTIVE:
                break
            await asyncio.sleep(0.01)
        workflows = (await client.get("/api/cmh/workflows")).json()
        runs = (await client.get("/api/cmh/runs")).json()
        detail = (await client.get(f"/api/cmh/runs/{run_id}")).json()
    sample_flow = SAMPLES["workflows"]["workflows"][0]
    assert set(workflows["workflows"][0]) == set(sample_flow)
    assert set(workflows["workflows"][0]["steps"][0]) == set(sample_flow["steps"][0])
    assert set(runs["runs"][0]) == set(SAMPLES["runs"]["runs"][0])
    sample_detail = SAMPLES["run_detail"]["run-1"]
    assert detail["status"] == "waiting_approval"
    assert set(detail) == set(sample_detail)
    assert set(detail["steps"][0]) == set(sample_detail["steps"][0])
    assert set(detail["artifacts"][0]) == set(sample_detail["artifacts"][0])

    stream = endpoint_of(workflow_routes.setup_cmh_workflow_routes(), "GET", "/api/cmh/runs/{run_id}/events")
    polls = iter([False])

    async def is_disconnected():
        return next(polls, True)
    response = await stream(SimpleNamespace(state=SimpleNamespace(current_user="admin"), is_disconnected=is_disconnected), run_id, after=0, last_event_id=None)
    replay = "".join([chunk async for chunk in response.body_iterator])
    data = [json.loads(line[6:]) for line in replay.splitlines() if line.startswith("data: ")]
    kinds = [line[7:] for line in replay.splitlines() if line.startswith("event: ")]
    assert data and all(set(item) == set(SAMPLES["events"]["run-1"][0]["data"]) for item in data)
    assert {"run_created", "step_started", "step_completed", "step_approval_requested"} <= set(kinds)


def test_memory_endpoints_match_the_ui_samples(monkeypatch, tmp_path):
    canon = tmp_path / "vault" / "CMH_Canon"
    canon.mkdir(parents=True)
    target = canon / "decision.md"
    target.write_bytes(b"# Before\n")
    monkeypatch.setattr(memory, "CANON_ROOT", canon)
    monkeypatch.setattr(memory, "MIRROR_ROOT", tmp_path / "vault" / "CMH_Claude" / "CMH_Canon")
    monkeypatch.setattr(memory, "BACKUP_ROOT", tmp_path / "backups")
    monkeypatch.setattr(memory, "catalog", lambda: [])
    monkeypatch.setattr(control, "owner_is_admin_or_single_user", lambda owner: owner == "admin")
    engine = create_engine("sqlite:///:memory:")
    cdb.Base.metadata.create_all(engine)
    monkeypatch.setattr(memory, "SessionLocal", sessionmaker(bind=engine))
    router = memory.setup_cmh_memory_routes()
    listed = endpoint_of(router, "GET", "/api/cmh/memories")(request())
    assert set(listed["memories"][0]) == set(SAMPLES["memories"]["memories"][0])
    content = endpoint_of(router, "GET", "/api/cmh/memories/content")(request(), str(target))
    assert set(content) == set(SAMPLES["memory_content"])
    proposal = endpoint_of(router, "POST", "/api/cmh/memory-proposals")(request(), memory.ProposalInput(
        target_path=str(target), proposed_content="# After\n", base_sha256=memory._hash(target.read_bytes())))
    proposals = endpoint_of(router, "GET", "/api/cmh/memory-proposals")(request())
    assert set(proposals["proposals"][0]) == set(SAMPLES["memory_proposals"]["proposals"][0])
    detail = endpoint_of(router, "GET", "/api/cmh/memory-proposals/{proposal_id}")(request(), proposal["id"])
    assert set(detail) == set(SAMPLES["memory_proposal_detail"])
    engine.dispose()
