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
from src.task_workspace import validate_task_tools, validate_task_workspace
from src.tool_security import owner_is_admin_or_single_user


CMH_ROOT = Path(__file__).resolve().parents[2].parent
INDEX_PATH = CMH_ROOT / "_control" / "INDICE.md"
MANAGED_PROJECTS = CMH_ROOT / "CMH_Claude" / "Proyectos"
_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*\[Ficha[^]]*\]\(<([^>]+)>\)\s*\|\s*([^|]+?)\s*\|$")
# Financial, production and canon folders stay outside every agent workspace
# (integrations/cmh/README.md), as does any fuentes/ folder, which is read-only.
FINANCIAL_AREAS = ("Base Matriz Nueva", "Modelo Financiero Nuevo", "Dashboard Financiero", "Producción")
PROTECTED_AREAS = FINANCIAL_AREAS + ("CMH_Canon", "CMH_Claude/CMH_Canon")
_FUENTES_SCAN_DEPTH = 3


def in_financial_area(path) -> bool:
    target = Path(path).resolve()
    return any(target.is_relative_to((CMH_ROOT / name).resolve()) for name in FINANCIAL_AREAS)


def protected_area(path) -> Optional[str]:
    """Name the protected area a workspace lies in or contains, or None."""
    target = Path(path).resolve()
    if any(part.casefold() == "fuentes" for part in target.parts):
        return "fuentes"
    for name in PROTECTED_AREAS:
        area = (CMH_ROOT / name).resolve()
        if target.is_relative_to(area) or area.is_relative_to(target):
            return name
    base_depth = len(target.parts)
    for current, dirs, _files in os.walk(target):
        if any(d.casefold() == "fuentes" for d in dirs):
            return "fuentes"
        if len(Path(current).parts) - base_depth >= _FUENTES_SCAN_DEPTH:
            dirs.clear()
    return None


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
    }


class AgentInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    project_id: Optional[str] = None
    role: str = Field(min_length=1, max_length=120)
    instructions: str = Field(min_length=1)
    model: Optional[str] = None
    allowed_tools: list[str] = Field(default_factory=list)
    workspace: Optional[str] = None
    task_id: Optional[str] = None


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)


def _validated_input(body: AgentInput, owner: str):
    if not body.name.strip() or not body.role.strip() or not body.instructions.strip():
        raise HTTPException(400, "Name, role and instructions cannot be blank")
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


def _validate_task_link(db, task_id: Optional[str], owner: str) -> None:
    if task_id and not db.query(ScheduledTask).filter(
        ScheduledTask.id == task_id, ScheduledTask.owner == owner,
        ScheduledTask.task_type == "llm",
    ).first():
        raise HTTPException(400, "Task must be an owned LLM task")


def _recent_runs(db, agents: list[CMHAgent]) -> list[dict]:
    ids = [agent.task_id for agent in agents if agent.task_id]
    if not ids:
        return []
    runs = db.query(TaskRun).filter(TaskRun.task_id.in_(ids)).order_by(TaskRun.started_at.desc()).limit(10).all()
    return [{"id": run.id, "task_id": run.task_id, "status": run.status,
             "model": run.model, "started_at": run.started_at.isoformat() if run.started_at else None,
             "finished_at": run.finished_at.isoformat() if run.finished_at else None}
            for run in runs]


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
            _validate_task_link(db, body.task_id, owner)
            agent = CMHAgent(
                id=uuid.uuid4().hex, owner=owner, name=body.name.strip(),
                project_id=body.project_id, role=body.role.strip(),
                instructions=body.instructions, model=body.model,
                allowed_tools=json.dumps(sorted(tools)), workspace=workspace,
                status="paused", instructions_version=1,
                task_id=body.task_id,
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
            _validate_task_link(db, body.task_id, owner)
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
