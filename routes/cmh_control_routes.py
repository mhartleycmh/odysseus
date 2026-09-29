"""Local CMH project catalog and versioned agent registry."""

import os
import re
import unicodedata
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core.database import CMHAgent, ScheduledTask, SessionLocal, TaskRun
from src.auth_helpers import get_current_user
from src.cmh_cost_policy import ZeroCostViolation, assert_zero_cost_url
from src.cmh_provider_router import normalize_policy
from src.task_workspace import validate_task_tools, validate_task_workspace
from src.tool_security import owner_is_admin_or_single_user


# The protected-area rules live in src/cmh_protected_areas so a script can
# consult them without importing core.database. Re-exported here: every caller
# and test keeps importing them from this module.
from src.cmh_protected_areas import (  # noqa: F401,E402
    CMH_ROOT, FINANCIAL_AREAS, PROTECTED_AREAS, in_financial_area, protected_area,
)

INDEX_PATH = CMH_ROOT / "_control" / "INDICE.md"
MANAGED_PROJECTS = CMH_ROOT / "CMH_Claude" / "Proyectos"
_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*\[Ficha[^]]*\]\(<([^>]+)>\)\s*\|\s*([^|]+?)\s*\|$")


def _card_title(card: Path) -> str:
    try:
        lines = card.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeDecodeError:
        return ""  # a non-UTF-8 card must not take the whole catalog down
    return lines[0].removeprefix("# ").strip() if lines else ""


def _slug(value: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


def catalog() -> list[dict]:
    """Read the CMH index each time; never cache it as another source of truth."""
    root = CMH_ROOT.resolve()
    projects = []
    for line in INDEX_PATH.read_text(encoding="utf-8").splitlines():
        match = _ROW.match(line)
        if not match:
            continue
        name, relative_card, stated_status = match.groups()
        card = (INDEX_PATH.parent / relative_card).resolve()
        if not card.is_relative_to(root) or not card.is_file():
            continue
        parts = Path(relative_card).parts
        project_root = (INDEX_PATH.parent / ".." / parts[1]).resolve() if len(parts) > 1 and parts[0] == ".." else card.parent
        if not card.is_relative_to(project_root) or not project_root.is_relative_to(root):
            continue
        projects.append({
            "id": _slug(name),
            "name": name,
            "status": stated_status.strip(),
            "card_path": str(card),
            "root_path": str(project_root),
            "card_modified": card.stat().st_mtime,
            "source": str(INDEX_PATH),
        })
    if MANAGED_PROJECTS.is_dir():
        for card in sorted(MANAGED_PROJECTS.glob("*/00_Proyecto.md")):
            project_root = card.parent.resolve()
            if not project_root.is_relative_to(MANAGED_PROJECTS.resolve()):
                continue
            projects.append({"id": project_root.name, "name": _card_title(card) or project_root.name,
                             "status": "Nuevo", "card_path": str(card.resolve()),
                             "root_path": str(project_root), "card_modified": card.stat().st_mtime,
                             "source": str(card)})
    return projects


def _owner(request: Request) -> str:
    owner = get_current_user(request)
    if not owner:
        raise HTTPException(401, "Not authenticated")
    return owner


def _admin(owner: str) -> None:
    if not owner_is_admin_or_single_user(owner):
        raise HTTPException(403, "CMH agent management is admin-only")


def _agent_dict(agent: CMHAgent) -> dict:
    import json
    return {
        "id": agent.id,
        "name": agent.name,
        "project_id": agent.project_id,
        "role": agent.role,
        "instructions": agent.instructions,
        "instructions_version": agent.instructions_version,
        "model": agent.model,
        "allowed_tools": json.loads(agent.allowed_tools or "[]"),
        "workspace": agent.workspace,
        "status": agent.status,
        "task_id": agent.task_id,
        "provider_policy": agent.provider_policy,
    }


class AgentInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    project_id: Optional[str] = None
    role: str = Field(min_length=1, max_length=120)
    instructions: str = Field(min_length=1)
    model: Optional[str] = None
    allowed_tools: list[str] = Field(default_factory=list)
    workspace: Optional[str] = None
    # Omitting task_id creates the paused twin LLM task from these same fields.
    # Passing one keeps the previous behaviour, so an existing caller is intact.
    task_id: Optional[str] = None
    provider_policy: Optional[str] = None


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)


def _validated_input(body: AgentInput, owner: str):
    if not body.name.strip() or not body.role.strip() or not body.instructions.strip():
        raise HTTPException(400, "Name, role and instructions cannot be blank")
    if body.provider_policy and normalize_policy(body.provider_policy) is None:
        from src.cmh_provider_router import PROVIDER_POLICIES
        raise HTTPException(400, f"provider_policy '{body.provider_policy}' no existe. "
                                 f"Validos: {', '.join(sorted(PROVIDER_POLICIES))}")
    if body.project_id and body.project_id not in {p["id"] for p in catalog()}:
        raise HTTPException(400, "Unknown project")
    try:
        workspace = validate_task_workspace(body.workspace, owner)
        tools = validate_task_tools(body.allowed_tools, owner)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(400, str(exc)) from exc
    area = protected_area(workspace) if workspace else None
    if area:
        raise HTTPException(400, f"Workspace lies in or contains the protected area {area}")
    return workspace, tools


def _validate_task_link(db, task_id: Optional[str], owner: str,
                        model: Optional[str] = None) -> None:
    if not task_id:
        return
    task = db.query(ScheduledTask).filter(
        ScheduledTask.id == task_id, ScheduledTask.owner == owner,
        ScheduledTask.task_type == "llm",
    ).first()
    if not task:
        raise HTTPException(400, "Task must be an owned LLM task")
    # Zero cost (D1): an agent may not be pointed at a paid route. Checked on
    # the linked task's endpoint, which is what its steps will actually call.
    # A task with no endpoint yet has no route to price, and no run can start
    # from it either: ``_snapshot`` refuses it with its own 400. Refusing it
    # here as "not provably free" would block linking a task still being set up.
    if not task.endpoint_url:
        return
    try:
        assert_zero_cost_url(db, task.endpoint_url, model, owner)
    except ZeroCostViolation as exc:
        raise HTTPException(400, str(exc)) from exc


def _create_twin_task(db, body: AgentInput, workspace, tools, owner: str) -> str:
    """Create the paused LLM task an agent needs, and return its id.

    Until now the user had to build the task by hand in another screen and paste
    its id, and a step whose task had a different model than its agent was
    refused at run time with no clue why. The twin is created from the agent's
    own fields, so the two cannot disagree at birth.

    Paused, with e-mail and notifications off: canon rule of 2026-09-24 for
    pilot tasks. A task that runs on its own schedule, or writes to the user's
    inbox, is not what an agent's twin is for — the workflow engine drives it.
    """
    import json
    from src.cmh_cost_policy import ZeroCostViolation, assert_zero_cost_url
    from src.cmh_provider_router import resolve_candidates

    candidates = resolve_candidates(
        db, normalize_policy(body.provider_policy) or "free-cloud-first", owner)
    endpoint_url = candidates[0]["endpoint_url"] if candidates else None
    model = body.model or (candidates[0]["model"] if candidates else None)
    if endpoint_url:
        try:
            assert_zero_cost_url(db, endpoint_url, model, owner)
        except ZeroCostViolation as exc:
            raise HTTPException(400, str(exc)) from exc
    task = ScheduledTask(
        id=str(uuid.uuid4()), owner=owner, name=f"{body.name.strip()} (agente CMH)",
        task_type="llm", prompt="Gestionada por el motor de flujos CMH.",
        status="paused", trigger_type="manual", model=model,
        endpoint_url=endpoint_url, workspace=workspace,
        allowed_tools=json.dumps(sorted(tools)) if tools else None,
        email_results=False, notifications_enabled=False,
    )
    db.add(task)
    db.flush()
    return task.id


def _recent_runs(db, agents: list[CMHAgent]) -> list[dict]:
    ids = [agent.task_id for agent in agents if agent.task_id]
    if not ids:
        return []
    runs = db.query(TaskRun).filter(TaskRun.task_id.in_(ids)).order_by(TaskRun.started_at.desc()).limit(10).all()
    return [{"id": run.id, "task_id": run.task_id, "status": run.status,
             "model": run.model, "started_at": run.started_at.isoformat() if run.started_at else None,
             "finished_at": run.finished_at.isoformat() if run.finished_at else None}
            for run in runs]


def _window_reset(kind: str, window_start_iso: str) -> str:
    """When this window turns over, so the interface can show a real hour.

    Ours, not the provider's: their reset clock is not exposed, and presenting
    our truncation as theirs would be a number that looks measured and is not.
    """
    from datetime import datetime, timedelta
    span = timedelta(minutes=1) if kind == "minute" else timedelta(days=1)
    return (datetime.fromisoformat(window_start_iso) + span).isoformat()


def setup_cmh_control_routes() -> APIRouter:
    router = APIRouter(prefix="/api/cmh", tags=["cmh-control"])

    @router.get("/projects")
    def projects(request: Request):
        owner = _owner(request)
        _admin(owner)
        with SessionLocal() as db:
            agents = db.query(CMHAgent).filter(CMHAgent.owner == owner).all()
            result = catalog()
            for project in result:
                linked = [agent for agent in agents if agent.project_id == project["id"]]
                project["agents"] = [
                    {"id": agent.id, "name": agent.name, "status": agent.status}
                    for agent in linked
                ]
                project["recent_runs"] = _recent_runs(db, linked)
            return {"projects": result}

    @router.post("/projects", status_code=201)
    def create_project(request: Request, body: ProjectInput):
        owner = _owner(request)
        _admin(owner)
        name = body.name.strip()
        slug = _slug(name)
        if not slug:
            raise HTTPException(400, "Project name needs letters or numbers")
        if slug in {project["id"] for project in catalog()}:
            raise HTTPException(409, "Project ID already exists")
        MANAGED_PROJECTS.mkdir(parents=True, exist_ok=True)
        folder = MANAGED_PROJECTS / slug
        try:
            folder.mkdir(exist_ok=False)
            with (folder / "00_Proyecto.md").open("x", encoding="utf-8") as stream:
                stream.write(f"# {name}\n\nEstado: nuevo\n\n## Objetivo\n\nPendiente de definir.\n")
        except FileExistsError as exc:
            raise HTTPException(409, "Project folder already exists") from exc
        return next(project for project in catalog() if project["id"] == slug)

    @router.get("/projects/{project_id}")
    def project(request: Request, project_id: str):
        owner = _owner(request)
        _admin(owner)
        item = next((p for p in catalog() if p["id"] == project_id), None)
        if item is None:
            raise HTTPException(404, "Project not found")
        card = Path(item["card_path"])
        item["card_text"] = card.read_text(encoding="utf-8")[:20000]
        with SessionLocal() as db:
            linked = db.query(CMHAgent).filter(
                CMHAgent.owner == owner, CMHAgent.project_id == project_id,
            ).all()
            item["agents"] = [_agent_dict(agent) for agent in linked]
            item["recent_runs"] = _recent_runs(db, linked)
        return item

    @router.get("/quotas")
    def quotas(request: Request):
        """Free-tier consumption per provider and window, for the interface.

        Reports our own count, which is an estimate of the provider's: it sees
        this installation's calls and nothing else. ``verified`` carries through
        from the config so a limit nobody has confirmed is not displayed as if
        somebody had, and a null limit is reported as unmeasured, not infinite.
        """
        from src.cmh_provider_router import (
            load_quota_config, quota_exceeded, usage_snapshot, window_start,
        )
        owner = _owner(request)
        _admin(owner)
        config = load_quota_config()
        threshold = float(config.get("threshold", 0.9))
        from core.database import ModelEndpoint
        from src.cmh_cost_policy import endpoint_host
        result = []
        with SessionLocal() as db:
            rows = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True).all()  # noqa: E712
            for provider in sorted(config.get("providers", []), key=lambda p: p.get("order", 99)):
                host = str(provider.get("endpoint_host", "")).lower()
                match = next((r for r in rows if endpoint_host(r.base_url) == host), None)
                limits = provider.get("limits") or {}
                entry = {
                    "host": host, "model": provider.get("model"),
                    "registered": match is not None,
                    "endpoint_id": match.id if match else None,
                    "limits": limits, "verified": bool(provider.get("verified")),
                    "source_url": provider.get("source_url"),
                    "source_date": provider.get("source_date"),
                    "threshold": threshold, "blocked_by": None, "windows": {},
                }
                if match:
                    entry["windows"] = usage_snapshot(db, match.id)
                    entry["blocked_by"] = quota_exceeded(db, match.id, limits, threshold)
                for kind in ("minute", "day"):
                    entry["windows"].setdefault(kind, {"window_start": window_start(kind).isoformat(),
                                                       "requests": 0, "tokens_in": 0, "tokens_out": 0})
                    entry["windows"][kind]["resets_at"] = (
                        _window_reset(kind, entry["windows"][kind]["window_start"]))
                result.append(entry)
        return {"threshold": threshold, "providers": result}

    @router.get("/agents")
    def agents(request: Request):
        owner = _owner(request)
        _admin(owner)
        with SessionLocal() as db:
            return {"agents": [_agent_dict(agent) for agent in db.query(CMHAgent).filter(
                CMHAgent.owner == owner,
            ).order_by(CMHAgent.name).all()]}

    @router.post("/agents", status_code=201)
    def create_agent(request: Request, body: AgentInput):
        import json
        owner = _owner(request)
        _admin(owner)
        workspace, tools = _validated_input(body, owner)
        with SessionLocal() as db:
            task_id = body.task_id
            if task_id:
                _validate_task_link(db, task_id, owner, body.model)
            else:
                task_id = _create_twin_task(db, body, workspace, tools, owner)
            agent = CMHAgent(
                id=uuid.uuid4().hex, owner=owner, name=body.name.strip(),
                project_id=body.project_id, role=body.role.strip(),
                instructions=body.instructions, model=body.model,
                allowed_tools=json.dumps(sorted(tools)), workspace=workspace,
                status="paused", instructions_version=1,
                task_id=task_id, provider_policy=normalize_policy(body.provider_policy),
            )
            db.add(agent)
            db.commit()
            db.refresh(agent)
            return _agent_dict(agent)

    @router.put("/agents/{agent_id}")
    def update_agent(request: Request, agent_id: str, body: AgentInput):
        import json
        owner = _owner(request)
        _admin(owner)
        workspace, tools = _validated_input(body, owner)
        with SessionLocal() as db:
            _validate_task_link(db, body.task_id, owner, body.model)
            agent = db.query(CMHAgent).filter(CMHAgent.id == agent_id, CMHAgent.owner == owner).first()
            if not agent:
                raise HTTPException(404, "Agent not found")
            if agent.instructions != body.instructions:
                agent.instructions_version += 1
            agent.name = body.name.strip()
            agent.project_id = body.project_id
            agent.role = body.role.strip()
            agent.instructions = body.instructions
            agent.model = body.model
            agent.allowed_tools = json.dumps(sorted(tools))
            agent.workspace = workspace
            agent.task_id = body.task_id
            agent.provider_policy = normalize_policy(body.provider_policy)
            db.commit()
            db.refresh(agent)
            return _agent_dict(agent)

    @router.post("/agents/{agent_id}/pause")
    def pause_agent(request: Request, agent_id: str):
        owner = _owner(request)
        _admin(owner)
        with SessionLocal() as db:
            agent = db.query(CMHAgent).filter(CMHAgent.id == agent_id, CMHAgent.owner == owner).first()
            if not agent:
                raise HTTPException(404, "Agent not found")
            agent.status = "paused"
            db.commit()
            return _agent_dict(agent)

    @router.post("/agents/{agent_id}/resume")
    def resume_agent(request: Request, agent_id: str):
        owner = _owner(request)
        _admin(owner)
        with SessionLocal() as db:
            agent = db.query(CMHAgent).filter(CMHAgent.id == agent_id, CMHAgent.owner == owner).first()
            if not agent:
                raise HTTPException(404, "Agent not found")
            if not agent.project_id or not agent.workspace or not agent.model:
                raise HTTPException(400, "Project, workspace and model are required to activate an agent")
            agent.workspace = validate_task_workspace(agent.workspace, owner, persisted=True)
            agent.status = "active"
            db.commit()
            return _agent_dict(agent)

    return router
