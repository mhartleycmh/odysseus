"""Admin API for artifact-based CMH workflows and recoverable event streams."""

import asyncio
import json
import uuid

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.database import (
    CMHAgent, CMHWorkflowArtifact, CMHWorkflowDefinition, CMHWorkflowEvent,
    CMHWorkflowRun, CMHWorkflowStep, ScheduledTask, SessionLocal, utcnow_naive,
)
from routes.cmh_control_routes import _admin, _owner, catalog, protected_area
from src.cmh_workflows import (
    READ_TOOLS, event, is_active, release_stranded_steps, start, stop, validate_dag,
)

_HEARTBEAT_POLLS = 30  # idle polls of 0.5 s between keep-alive comments
from src.task_workspace import TaskWorkspaceError, validate_task_tools, validate_task_workspace


class DefinitionInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    project_id: str
    steps: list[dict]


class RunInput(BaseModel):
    initial_input: str = Field(min_length=1, max_length=12000)


class DecisionInput(BaseModel):
    """The reviewer's reason. Required to reject, optional to approve."""
    justification: str = Field(default="", max_length=2000)


def _record_decision(step, outcome: str, justification: str, owner: str) -> dict:
    """Freeze the human verdict on the step so it survives the browser."""
    decision = {"outcome": outcome, "justification": justification.strip(),
                "by": owner, "at": utcnow_naive().isoformat()}
    step.decision = json.dumps(decision)
    return decision


def _owned_run(db, run_id, owner):
    run = db.query(CMHWorkflowRun).filter(CMHWorkflowRun.id == run_id,
                                          CMHWorkflowRun.owner == owner).first()
    if not run:
        raise HTTPException(404, "Workflow run not found")
    return run


def _snapshot(db, owner, project_id, spec):
    agent = db.query(CMHAgent).filter(CMHAgent.id == spec["agent_id"],
                                      CMHAgent.owner == owner,
                                      CMHAgent.project_id == project_id).first()
    if not agent or agent.status != "active" or not agent.task_id:
        raise HTTPException(400, f"Step {spec['key']} requires an active linked agent")
    task = db.query(ScheduledTask).filter(ScheduledTask.id == agent.task_id,
                                           ScheduledTask.owner == owner,
                                           ScheduledTask.task_type == "llm").first()
    if not task or not task.endpoint_url or task.model != agent.model:
        raise HTTPException(400, f"Step {spec['key']} needs a matching configured model endpoint")
    # Validator failures are configuration problems of this step: report them
    # as 400 instead of letting PermissionError/TaskWorkspaceError become 500.
    try:
        tools = validate_task_tools(json.loads(agent.allowed_tools or "null"), owner)
        workspace = validate_task_workspace(agent.workspace, owner, persisted=True)
    except (PermissionError, TaskWorkspaceError, TypeError, ValueError) as exc:
        raise HTTPException(400, f"Step {spec['key']} has an invalid tool or workspace policy") from exc
    if tools is None or not tools <= READ_TOOLS:
        raise HTTPException(400, "Workflow steps may use only read-only file tools")
    if not workspace:
        raise HTTPException(400, "Workflow step requires a workspace")
    area = protected_area(workspace)
    if area:
        raise HTTPException(400, f"Step {spec['key']} workspace lies in or contains the protected area {area}")
    return {"owner": owner, "name": agent.name, "agent_id": agent.id,
            "instructions": agent.instructions, "instructions_version": agent.instructions_version,
            "model": agent.model, "endpoint_url": task.endpoint_url,
            "workspace": workspace, "allowed_tools": sorted(tools)}


def setup_cmh_workflow_routes() -> APIRouter:
    router = APIRouter(prefix="/api/cmh", tags=["cmh-workflows"])

    @router.get("/workflows")
    def definitions(request: Request):
        owner = _owner(request); _admin(owner)
        with SessionLocal() as db:
            rows = db.query(CMHWorkflowDefinition).filter(CMHWorkflowDefinition.owner == owner).all()
            return {"workflows": [{"id": row.id, "name": row.name, "project_id": row.project_id,
                                    "version": row.version, "steps": json.loads(row.steps)} for row in rows]}

    @router.post("/workflows", status_code=201)
    def create_definition(request: Request, body: DefinitionInput):
        owner = _owner(request); _admin(owner)
        if body.project_id not in {p["id"] for p in catalog()}:
            raise HTTPException(400, "Unknown project")
        try:
            steps = validate_dag(body.steps)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        with SessionLocal() as db:
            row = CMHWorkflowDefinition(id=str(uuid.uuid4()), owner=owner,
                                        project_id=body.project_id, name=body.name.strip(),
                                        version=1, steps=json.dumps(steps))
            db.add(row); db.commit()
            return {"id": row.id, "project_id": row.project_id, "steps": steps}

    @router.post("/workflows/{definition_id}/runs", status_code=201)
    async def create_run(request: Request, definition_id: str, body: RunInput):
        owner = _owner(request); _admin(owner)
        with SessionLocal() as db:
            definition = db.query(CMHWorkflowDefinition).filter(
                CMHWorkflowDefinition.id == definition_id,
                CMHWorkflowDefinition.owner == owner).first()
            if not definition:
                raise HTTPException(404, "Workflow not found")
            specs = json.loads(definition.steps)
            snapshots = [_snapshot(db, owner, definition.project_id, spec) for spec in specs]
            for spec, config in zip(specs, snapshots):
                config["requires_approval"] = spec["requires_approval"]
                config["approved"] = False
            run = CMHWorkflowRun(id=str(uuid.uuid4()), owner=owner,
                                 definition_id=definition_id, project_id=definition.project_id,
                                 status="pending", initial_input=body.initial_input)
            db.add(run)
            for spec, config in zip(specs, snapshots):
                db.add(CMHWorkflowStep(id=str(uuid.uuid4()), run_id=run.id,
                                       step_key=spec["key"], agent_id=spec["agent_id"],
                                       config=json.dumps(config),
                                       dependencies=json.dumps(spec["depends_on"]),
                                       status="pending"))
            event(db, run.id, "run_created", definition_id=definition_id)
            db.commit()
            run_id = run.id
        start(run_id)
        return {"id": run_id, "status": "pending"}

    @router.get("/runs")
    def list_runs(request: Request, project_id: str | None = None):
        owner = _owner(request); _admin(owner)
        with SessionLocal() as db:
            query = db.query(CMHWorkflowRun).filter(CMHWorkflowRun.owner == owner)
            if project_id:
                query = query.filter(CMHWorkflowRun.project_id == project_id)
            rows = query.order_by(CMHWorkflowRun.created_at.desc()).limit(50).all()
            return {"runs": [{"id": r.id, "definition_id": r.definition_id,
                              "project_id": r.project_id, "status": r.status,
                              "created_at": r.created_at.isoformat() if r.created_at else None}
                             for r in rows]}

    @router.get("/runs/{run_id}")
    def run_detail(request: Request, run_id: str):
        owner = _owner(request); _admin(owner)
        with SessionLocal() as db:
            run = _owned_run(db, run_id, owner)
            steps = db.query(CMHWorkflowStep).filter(CMHWorkflowStep.run_id == run_id).all()
            artifacts = db.query(CMHWorkflowArtifact).filter(CMHWorkflowArtifact.run_id == run_id).all()
            return {"id": run.id, "status": run.status, "project_id": run.project_id,
                    "steps": [{"key": s.step_key, "status": s.status, "agent_id": s.agent_id,
                               "model": json.loads(s.config)["model"], "dependencies": json.loads(s.dependencies),
                               "error": s.error,
                               "decision": json.loads(s.decision) if s.decision else None} for s in steps],
                    "artifacts": [{"id": a.id, "step_key": a.step_key, "model": a.model,
                                   "content": a.content} for a in artifacts]}

    # stop/resume/approve must be async: start() and Task.cancel() need the
    # event loop thread, and FastAPI runs plain ``def`` handlers in a threadpool.
    @router.post("/runs/{run_id}/stop")
    async def stop_run(request: Request, run_id: str):
        owner = _owner(request); _admin(owner)
        with SessionLocal() as db:
            run = _owned_run(db, run_id, owner)
            # An "error" run can still have a sibling step executing.
            if run.status not in {"running", "pending", "waiting_approval"} and not (
                    run.status == "error" and is_active(run_id)):
                raise HTTPException(409, "Run is not active")
            # A step waiting for approval goes back to pending; resuming asks
            # for the approval again because it was never granted.
            for step in db.query(CMHWorkflowStep).filter(CMHWorkflowStep.run_id == run_id,
                                                        CMHWorkflowStep.status == "waiting_approval").all():
                step.status = "pending"
            run.status = "interrupted"
            event(db, run.id, "run_stop_requested")
            db.commit()
        stop(run_id)
        return {"id": run_id, "status": "interrupted"}

    @router.post("/runs/{run_id}/resume")
    async def resume_run(request: Request, run_id: str):
        owner = _owner(request); _admin(owner)
        with SessionLocal() as db:
            run = _owned_run(db, run_id, owner)
            if run.status not in {"interrupted", "error", "paused"}:
                raise HTTPException(409, "Run cannot be resumed")
            if is_active(run_id):
                raise HTTPException(409, "Run is still stopping; try again")
            for step in db.query(CMHWorkflowStep).filter(CMHWorkflowStep.run_id == run_id,
                                                        CMHWorkflowStep.status == "error").all():
                step.status = "interrupted"
            run.status = "interrupted"
            event(db, run.id, "run_resume_requested")
            db.commit()
        # No task executes this run, so a step still marked "running" is stranded.
        release_stranded_steps(run_id)
        start(run_id)
        return {"id": run_id, "status": "interrupted"}

    def _pending_step(db, run, step_key):
        step = db.query(CMHWorkflowStep).filter(CMHWorkflowStep.run_id == run.id,
                                                CMHWorkflowStep.step_key == step_key).first()
        if not step or run.status != "waiting_approval" or step.status != "waiting_approval":
            raise HTTPException(409, "No approval pending for this step")
        return step

    @router.post("/runs/{run_id}/steps/{step_key}/approve")
    async def approve_step(request: Request, run_id: str, step_key: str,
                           body: DecisionInput | None = None):
        owner = _owner(request); _admin(owner)
        with SessionLocal() as db:
            run = _owned_run(db, run_id, owner)
            step = _pending_step(db, run, step_key)
            config = json.loads(step.config)
            config["approved"] = True
            step.config = json.dumps(config)
            step.status = "pending"
            run.status = "interrupted"
            _record_decision(step, "approved", (body.justification if body else ""), owner)
            event(db, run_id, "step_approved", step_key)
            db.commit()
        start(run_id)
        return {"id": run_id, "step_key": step_key, "status": "approved"}

    @router.post("/runs/{run_id}/steps/{step_key}/reject")
    async def reject_step(request: Request, run_id: str, step_key: str, body: DecisionInput):
        """Refuse the step and end the run. Terminal on purpose: a rejected
        step was never approved, so resuming it would silently re-ask instead
        of keeping the refusal. Artifacts already produced are preserved."""
        owner = _owner(request); _admin(owner)
        justification = (body.justification or "").strip()
        if not justification:
            raise HTTPException(400, "A rejection needs a justification")
        with SessionLocal() as db:
            run = _owned_run(db, run_id, owner)
            step = _pending_step(db, run, step_key)
            step.status = "rejected"
            step.finished_at = utcnow_naive()
            decision = _record_decision(step, "rejected", justification, owner)
            run.status = "rejected"
            run.finished_at = utcnow_naive()
            event(db, run_id, "step_rejected", step_key)
            event(db, run_id, "run_rejected")
            db.commit()
        # Defense in depth, not a live path: today `execute()` sets
        # waiting_approval and RETURNS before its gather, so no task is running
        # when a decision arrives and this is a no-op. It stays so that a
        # future engine which can approve mid-flight cannot leave a sibling
        # step outliving the refusal. Verified no-op, not assumed.
        stop(run_id)
        return {"id": run_id, "step_key": step_key, "status": "rejected", "decision": decision}

    @router.get("/runs/{run_id}/events")
    async def stream_events(request: Request, run_id: str, after: int = 0,
                            last_event_id: str | None = Header(default=None, alias="Last-Event-ID")):
        owner = _owner(request); _admin(owner)
        with SessionLocal() as db:
            _owned_run(db, run_id, owner)
        try:
            cursor = max(after, int(last_event_id or 0))
        except ValueError:
            raise HTTPException(400, "Invalid event cursor")

        async def events():
            nonlocal cursor
            idle = 0
            while not await request.is_disconnected():
                with SessionLocal() as db:
                    rows = db.query(CMHWorkflowEvent).filter(
                        CMHWorkflowEvent.run_id == run_id,
                        CMHWorkflowEvent.seq > cursor).order_by(CMHWorkflowEvent.seq).limit(100).all()
                    payloads = [(r.seq, r.kind, r.step_key, r.payload, r.created_at) for r in rows]
                for seq, kind, key, payload, created_at in payloads:
                    cursor = seq
                    # "at" (naive UTC in the database) lets a replayed stream rebuild real timings.
                    at = created_at.isoformat() + "Z" if created_at else None
                    yield f"id: {seq}\nevent: {kind}\ndata: {json.dumps({'step_key': key, 'payload': json.loads(payload), 'at': at})}\n\n"
                if len(payloads) == 100:
                    continue  # still replaying a backlog: no pause between pages
                idle = 0 if payloads else idle + 1
                if idle >= _HEARTBEAT_POLLS:
                    idle = 0
                    yield ": keep-alive\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    return router
