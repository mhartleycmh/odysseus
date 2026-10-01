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
from src.cmh_cost_policy import (
    ZeroCostViolation, assert_zero_cost_url, endpoint_for_url, endpoint_host,
    is_local_endpoint,
)
from src.cmh_provider_router import (
    LOCAL_ONLY, discover_free_models, resolve_candidates, resolve_policy,
)
from src.cmh_workflows import (
    default_tool_evidence,
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


def _provider_key(url) -> str:
    """Host and port: what makes two routes the same server, for deduplication.

    ``endpoint_host`` drops the port because the quota config keys on the host,
    which is right for a provider's limits and wrong for telling two local
    runtimes apart.

    Built from ``redact_url``, the repository's own helper, rather than from raw
    ``netloc``: netloc carries any ``user:password@`` embedded in the URL, so
    the key differed per credential and — worse — that credential was persisted
    as a candidate id and emitted over SSE. ``redact_url`` also brackets IPv6
    literals and normalises the port, which a hand-rolled split does not.
    """
    from urllib.parse import urlparse
    try:
        parsed = urlparse(_canonical_route(url))
    except ValueError:
        return ""
    # No .lower() here: _canonical_route already lowered the host, so it
    # would be unreachable. Measured, not assumed.
    return (parsed.netloc or "").strip()


#: The port a scheme implies, so an explicit one does not look like a different
#: server. `https://api.groq.com:443/v1` and `https://api.groq.com/v1` are one
#: route; keying quota on the spelling split one provider's counter in two and
#: the free-tier limit stopped biting.
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _canonical_route(url) -> str:
    """One spelling per route: no credentials, no default port, no trailing dot.

    Built on ``redact_url`` (the repository's own helper, which also brackets
    IPv6 literals) and then normalised further, because two spellings of the
    same endpoint must produce the same quota counter and the same candidate id.
    """
    from core.log_safety import redact_url
    from urllib.parse import urlparse, urlunparse

    try:
        parsed = urlparse(redact_url(url or ""))
    except ValueError:
        return ""
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"                      # IPv6 literal
    port = parsed.port
    if port is not None and port != _DEFAULT_PORTS.get((parsed.scheme or "").lower()):
        host = f"{host}:{port}"
    return urlunparse(((parsed.scheme or "").lower(), host,
                       (parsed.path or "").rstrip("/"), "", "", ""))


def _assert_definition_zero_cost(db, owner, steps) -> None:
    """Refuse a definition whose steps already point at a paid route (D1).

    Only what is resolvable now is judged: a step whose agent has no linked
    task yet has no route to classify, and ``_snapshot`` gates it at run
    creation, where the route stops being hypothetical. Catching it here as
    well means the user is told at the moment they can still change the step,
    instead of at the moment they press run.
    """
    for spec in steps:
        agent = db.query(CMHAgent).filter(CMHAgent.id == spec["agent_id"],
                                          CMHAgent.owner == owner).first()
        if not agent or not agent.task_id:
            continue
        task = db.query(ScheduledTask).filter(ScheduledTask.id == agent.task_id,
                                              ScheduledTask.owner == owner).first()
        if not task or not task.endpoint_url:
            continue
        try:
            assert_zero_cost_url(db, task.endpoint_url, agent.model, owner)
        except ZeroCostViolation as exc:
            raise HTTPException(400, f"Step {spec['key']}: {exc}") from exc


def _snapshot(db, owner, project_id, spec, discovered=None, notes=None):
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
    # Zero cost (D1) on the route this step freezes. The strongest of the
    # gate's positions: whatever the definition said, this is what will run.
    try:
        assert_zero_cost_url(db, task.endpoint_url, agent.model, owner)
    except ZeroCostViolation as exc:
        raise HTTPException(400, f"Step {spec['key']}: {exc}") from exc
    # A credential embedded in the URL is refused loudly, not stripped
    # silently. Decision of 2026-09-29: it belongs in the endpoint's api_key,
    # where registration now puts it. Stripping it here would have removed
    # working authentication — measured, httpx turns userinfo into
    # Authorization: Basic at send time — and keeping it would persist the
    # secret in the run's frozen config and stream it to the browser.
    # The raw-authority check is mandatory when CMH_ZERO_COST=false: urlparse cannot assign a
    # host to a URL without a scheme, and the cost gate may be explicitly disabled.
    from src.cmh_cost_policy import carries_unliftable_credential, has_userinfo
    if (has_userinfo(task.endpoint_url or "")
            or carries_unliftable_credential(task.endpoint_url or "")):
        raise HTTPException(400, f"Step {spec['key']}: la URL de la tarea del agente lleva "
                                 f"credenciales embebidas. Corrigela: la credencial va en la "
                                 f"api_key del endpoint registrado, no en la URL. Aqui no se "
                                 f"recorta en silencio.")

    # Freeze the ordered candidate list here, where the run is born. Resolving
    # it per attempt would let a step's route change under it mid-run, which is
    # the guarantee of clean point 3. The step's own policy wins over the
    # agent's; both may be silent and the default applies.
    policy = resolve_policy(spec, {"provider_policy": agent.provider_policy})
    # The local candidate is NOT called with the agent's model. That name means
    # something only on the provider the agent was configured for: a Groq agent
    # carries `openai/gpt-oss-120b`, which no local runtime serves, so the local
    # fallback would have been asked for a model that is not there and the step
    # would have died at the end of the chain on a 404. The router names the
    # local model itself (config "local", else what the runtime has cached).
    # The artifact still says which model wrote it, so nothing is mislabelled.
    # An agent configured with a local endpoint keeps its own route: it is
    # prepended below with its own model.
    dropped = []
    candidates = resolve_candidates(db, policy, owner, discovered=discovered, dropped=dropped)
    # A registered row whose URL carries user:pass@ is refused the way the task's own URL
    # is above, and for the same reason: freezing it would persist the credential, and
    # stripping it would leave the runner unable to find the row by URL, so the step would
    # go out with no Authorization at all (where the URL form authenticated).
    #
    # Two limits, both declared in ADR-038. It applies to the row the router would have CHOSEN:
    # with a clean row for the same host listed first the run is created and the credentialed
    # row is ignored (it is never frozen, so nothing leaks). And it comes after the catalogue
    # query of discovery, which is a catalogue and not a chat: it costs nothing.
    for note in dropped:
        if note["reason"] == "credential_in_url":
            raise HTTPException(400, f"Step {spec['key']}: el endpoint {note['endpoint_id']} "
                                     f"lleva credenciales embebidas en su URL. Editalo (un PATCH "
                                     f"con esa misma URL pasa la credencial a su api_key), o "
                                     f"eliminalo o deshabilitalo: registrar otro nuevo no basta, "
                                     f"porque este sigue habilitado. Si la URL tiene un puerto "
                                     f"fuera de rango o no se puede leer, el PATCH la rechaza: "
                                     f"corrigela a mano. Aqui no se recorta en silencio.")
    # provider_dropped is per ROW: a provider can be dropped on one row and still be in the
    # frozen list through another (two Groq rows, one over http and one over https).
    if notes is not None:
        notes.extend(n for n in dropped if n not in notes)
    task_row = endpoint_for_url(db, task.endpoint_url, owner, agent.model)
    task_host = endpoint_host(task.endpoint_url)
    # Same PROVIDER and same model, not the same URL string. A registered row
    # for `https://api.groq.com` and a task pointed at
    # `https://api.groq.com/openai/v1` are the same provider, and comparing the
    # strings listed it twice — so a 429 retried the host that had just
    # refused, which is the exact failure the frozen list exists to avoid.
    #
    # The key carries the PORT, not just the host. Two local runtimes on
    # 127.0.0.1:59998 and 127.0.0.1:59999 are different servers; deduplicating
    # on the bare host silently dropped one of them. For a cloud provider there
    # is no port, so the key is the host and nothing changes.
    # By PROVIDER alone, not provider + model. A 429 is applied by the provider
    # to the account and host, not to the model, so two entries on one host are
    # two attempts at a door that just closed — the very failure the frozen list
    # exists to prevent. Measured by the third review: with the agent on one
    # model and the quota config naming another, api.groq.com appeared twice.
    task_key = _provider_key(task.endpoint_url)
    # The task's own route leads when the policy allows it: it is what the
    # agent was configured with and what the cost gate just cleared, and the
    # router's list is what the step falls back TO, not a silent replacement.
    # Under local-only it must NOT be prepended, or naming that policy would
    # send the first attempt to the cloud anyway — which is the whole thing
    # local-only exists to prevent.
    allowed_by_policy = policy != LOCAL_ONLY or is_local_endpoint(
        task_row or {"base_url": task.endpoint_url, "endpoint_kind": "auto"})
    if allowed_by_policy:
        # The task's route replaces the router's entry for the same provider
        # rather than joining it: the agent's own model is what the cost gate
        # cleared, and keeping both would put the same host in the list twice.
        # The id is a real endpoint id when one resolves and the canonical URL
        # otherwise — never None, because quota rows key on it under a NOT NULL
        # column and a None killed the step AFTER it had produced its artifact.
        candidates = [{"endpoint_id": (getattr(task_row, "id", None)
                                       or _canonical_route(task.endpoint_url)),
                       "endpoint_url": _canonical_route(task.endpoint_url),
                       "model": agent.model, "host": task_host}] + [
            c for c in candidates
            if _provider_key(c.get("endpoint_url")) != task_key]

    # One entry per provider across the WHOLE list, not just against the task's
    # key. Filtering only against the task left two ways for a provider to
    # appear twice: a row for a free host registered with endpoint_kind="local"
    # is emitted by both branches of resolve_candidates, and two enabled rows
    # can share a base URL. Measured by the fourth review; in both cases a 429
    # made the step retry the host that had just refused it.
    seen, unique = set(), []
    for candidate in candidates:
        key = _provider_key(candidate.get("endpoint_url"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    candidates = unique
    if not candidates:
        raise HTTPException(400, f"Step {spec['key']}: la politica '{policy}' no deja "
                                 f"ningun candidato gratuito disponible")
    return {"owner": owner, "name": agent.name, "agent_id": agent.id,
            "instructions": agent.instructions, "instructions_version": agent.instructions_version,
            "model": agent.model, "endpoint_url": task.endpoint_url,
            "workspace": workspace, "allowed_tools": sorted(tools),
            "provider_policy": policy, "candidates": candidates}


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
            _assert_definition_zero_cost(db, owner, steps)
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
            # OpenRouter's model is picked from its own catalogue with the
            # account's key, once per run, and frozen with the rest of the list.
            # Its config entry says model=null because the free catalogue turns
            # over; before this, nothing ever filled it in and the second link
            # of the chain never entered any list.
            #
            # Only when some step may leave the machine. Under local-only nothing
            # does, and a catalogue query is a call to the provider carrying the
            # account's key: the first version asked anyway, and the test that
            # pins local-only to "not even a catalogue query" caught it.
            agents = {a.id: a for a in db.query(CMHAgent).filter(
                CMHAgent.owner == owner,
                CMHAgent.id.in_([spec["agent_id"] for spec in specs])).all()}
            wants_cloud = any(resolve_policy(spec, agents.get(spec["agent_id"])) != LOCAL_ONLY
                              for spec in specs)
            discovered, discovery_notes = (
                await discover_free_models(db, owner) if wants_cloud else ({}, []))
            dropped_notes: list = []
            snapshots = [_snapshot(db, owner, definition.project_id, spec, discovered,
                                   dropped_notes) for spec in specs]
            for spec, config in zip(specs, snapshots):
                config["requires_approval"] = spec["requires_approval"]
                # Falls back to the per-role default, not to a second True written
                # here. A definition stored before that default existed carries
                # no field, or carries the old blanket True, and either way the
                # reviewer and the documenter would be asked for tool evidence
                # they cannot produce. The default has ONE home.
                stated = spec.get("require_tool_evidence")
                config["require_tool_evidence"] = (
                    bool(stated) if stated is not None
                    else default_tool_evidence(spec["key"]))
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
            # One event per discovery attempt, failures included: a provider
            # missing from the frozen lists must say why.
            for note in discovery_notes:
                event(db, run.id, "provider_discovery", **note)
            # A ROW the gate or the credential rule kept out of the frozen lists used to vanish
            # without a trace (the provider may still be there through another row): the run went
            # on with what was left and nobody could tell why a row of Groq was not there.
            for note in dropped_notes:
                event(db, run.id, "provider_dropped", **note)
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
                               # The candidate that answered when one did, so the run detail and
                               # the artifact agree on which model produced the step.
                               "model": (json.loads(s.config).get("resolved_model")
                                         or json.loads(s.config)["model"]),
                               "dependencies": json.loads(s.dependencies),
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
