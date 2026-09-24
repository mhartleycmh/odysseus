"""Durable, artifact-only CMH workflow execution."""

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from core.database import CMHWorkflowArtifact, CMHWorkflowEvent, CMHWorkflowRun, CMHWorkflowStep, SessionLocal

logger = logging.getLogger(__name__)
READ_TOOLS = frozenset({"read_file", "ls", "grep", "glob"})
# Per-artifact share of a downstream prompt. Longer artifacts are cut with an
# explicit marker and a step_input_truncated event, never silently.
MAX_ARTIFACT_INPUT_CHARS = 40_000
_ACTIVE: dict[str, asyncio.Task] = {}


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def validate_dag(steps: list[dict]) -> list[dict]:
    if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
        raise ValueError("Workflow needs 1 to 20 steps")
    keys = set()
    for step in steps:
        if not isinstance(step, dict) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,49}", str(step.get("key", ""))):
            raise ValueError("Invalid step key")
        if step["key"] in keys:
            raise ValueError("Duplicate step key")
        keys.add(step["key"])
        if not isinstance(step.get("agent_id"), str) or not step["agent_id"]:
            raise ValueError("Step requires an agent")
        for field in ("depends_on", "independent_of"):
            refs = step.get(field, [])
            if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
                raise ValueError(f"{field} must be a list of step keys")
    by_key = {step["key"]: step for step in steps}
    for step in steps:
        # independent_of: the named steps must be done by a different agent,
        # e.g. the reviewer is never the builder evaluating its own work.
        for ref in step.get("independent_of", []):
            if ref not in by_key or ref == step["key"]:
                raise ValueError("Invalid independence reference")
            if by_key[ref]["agent_id"] == step["agent_id"]:
                raise ValueError(f"Step {step['key']} must use a different agent than {ref}")
    visited, visiting = set(), set()

    def visit(key):
        if key in visiting:
            raise ValueError("Workflow contains a cycle")
        if key in visited:
            return
        visiting.add(key)
        deps = by_key[key].get("depends_on", [])
        if len(deps) != len(set(deps)) or any(dep not in by_key for dep in deps):
            raise ValueError("Invalid dependency")
        for dep in deps:
            visit(dep)
        visiting.remove(key)
        visited.add(key)

    for key in by_key:
        visit(key)
    return [{"key": s["key"], "agent_id": s["agent_id"],
             "depends_on": s.get("depends_on", []),
             "independent_of": s.get("independent_of", []),
             "requires_approval": bool(s.get("requires_approval", False))} for s in steps]


def event(db, run_id, kind, step_key=None, **payload):
    db.add(CMHWorkflowEvent(run_id=run_id, kind=kind, step_key=step_key,
                            payload=json.dumps(payload, ensure_ascii=False)))


def _release_stranded_steps(db, run_id, reason):
    """Turn "running" steps of a run with no live task back into resumable ones."""
    for step in db.query(CMHWorkflowStep).filter(CMHWorkflowStep.run_id == run_id,
                                                CMHWorkflowStep.status == "running").all():
        step.status = "interrupted"
        step.error = reason
        event(db, run_id, "step_interrupted", step.step_key)


def reconcile_interrupted_runs():
    # At startup nothing is executing. A "running" step is stranded whatever
    # its run's status (a sibling may have failed the run first), and a
    # "pending" run was never picked up; all of them become resumable.
    with SessionLocal() as db:
        stranded = {row[0] for row in db.query(CMHWorkflowStep.run_id).filter(
            CMHWorkflowStep.status == "running").distinct()}
        for run_id in stranded:
            _release_stranded_steps(db, run_id, "Server restarted during this step")
        runs = db.query(CMHWorkflowRun).filter(CMHWorkflowRun.status.in_(("running", "pending"))).all()
        for run in runs:
            run.status = "interrupted"
            event(db, run.id, "run_interrupted")
        db.commit()


def release_stranded_steps(run_id):
    """Resume helper: only valid when no task is executing this run."""
    with SessionLocal() as db:
        _release_stranded_steps(db, run_id, "Step had no live task when the run was resumed")
        db.commit()


def _fail_step(run_id, step_id, message):
    """Record a step failure; never raises, so no sibling step is orphaned."""
    try:
        with SessionLocal() as db:
            run = db.get(CMHWorkflowRun, run_id)
            step = db.get(CMHWorkflowStep, step_id)
            step.status = "error"
            step.error = message[:1000]
            step.finished_at = now()
            event(db, run_id, "step_error", step.step_key, error=step.error)
            if run.status == "running":
                run.status = "error"
                run.finished_at = now()
                event(db, run_id, "run_error", error=step.error)
            db.commit()
    except Exception:
        # The step stays "running" in the database; resume or the next
        # startup releases it.
        logger.exception("Could not record failure of CMH workflow step %s", step_id)


def _dependency_input(db, run_id, key, artifact):
    content = artifact.content
    if len(content) <= MAX_ARTIFACT_INPUT_CHARS:
        return f"[{key} / artifact {artifact.id}]\n{content}"
    event(db, run_id, "step_input_truncated", key, artifact_id=artifact.id,
          included=MAX_ARTIFACT_INPUT_CHARS, total=len(content))
    return (f"[{key} / artifact {artifact.id}]\n{content[:MAX_ARTIFACT_INPUT_CHARS]}\n"
            f"[TRUNCADO: se incluyen {MAX_ARTIFACT_INPUT_CHARS} de {len(content)} caracteres "
            f"del artefacto {artifact.id}; el resto no fue visto por este paso]")


async def call_model(config: dict, prompt: str) -> str:
    from src.task_scheduler import TaskScheduler
    def record(kind, **payload):
        with SessionLocal() as db:
            event(db, config["run_id"], kind, config["step_key"],
                  agent_id=config["agent_id"], model=config["model"], **payload)
            db.commit()
    task = SimpleNamespace(
        owner=config["owner"], name=config["name"], prompt=prompt,
        workspace=config["workspace"], allowed_tools=json.dumps(config["allowed_tools"]),
        max_steps=12,
    )
    return await TaskScheduler(None)._run_agent_loop(
        config["endpoint_url"], config["model"], task, str(uuid.uuid4()),
        system_prompt=config["instructions"], override_user_message=prompt,
        foreground_controlled=True, event_sink=record,
    )


async def _one(run_id: str, step_id: str, model_call):
    with SessionLocal() as db:
        run = db.get(CMHWorkflowRun, run_id)
        step = db.get(CMHWorkflowStep, step_id)
        if run.status != "running" or step.status != "pending":
            return
        config = json.loads(step.config)
        config["run_id"] = run_id
        config["step_key"] = step.step_key
        dependencies = json.loads(step.dependencies)
        artifacts = db.query(CMHWorkflowArtifact).filter(
            CMHWorkflowArtifact.run_id == run_id,
            CMHWorkflowArtifact.step_key.in_(dependencies),
        ).all() if dependencies else []
        if len(artifacts) != len(dependencies):
            step.status = "error"
            step.error = "Dependency artifact missing"
            step.finished_at = now()
            run.status = "error"
            run.finished_at = now()
            event(db, run_id, "step_error", step.step_key, error=step.error)
            event(db, run_id, "run_error", error=step.error)
            db.commit()
            return
        ordered = {a.step_key: a for a in artifacts}
        source = "\n\n".join(_dependency_input(db, run_id, key, ordered[key]) for key in dependencies)
        prompt = f"Authorized initial input:\n{run.initial_input[:12000]}\n\nCompleted artifact inputs:\n{source}\n\nProduce your own final artifact with evidence and limits. Do not quote private reasoning."
        step.status = "running"
        step.started_at = now()
        event(db, run_id, "step_started", step.step_key, agent_id=step.agent_id,
              model=config["model"])
        db.commit()
    try:
        output = await model_call(config, prompt)
        if not isinstance(output, str) or not output.strip():
            raise RuntimeError("Step produced no artifact")
    except asyncio.CancelledError:
        with SessionLocal() as db:
            step = db.get(CMHWorkflowStep, step_id)
            step.status = "interrupted"
            step.error = "Stopped during model call"
            step.finished_at = now()
            event(db, run_id, "step_interrupted", step.step_key)
            db.commit()
        raise
    except Exception as exc:
        _fail_step(run_id, step_id, f"{type(exc).__name__}: {exc}")
        return
    try:
        # Artifact and "completed" commit together: resume never repeats a
        # step whose output was stored, and never skips one whose output was not.
        with SessionLocal() as db:
            step = db.get(CMHWorkflowStep, step_id)
            artifact = CMHWorkflowArtifact(
                id=str(uuid.uuid4()), run_id=run_id, step_key=step.step_key,
                agent_id=step.agent_id, model=config["model"],
                instructions_version=config["instructions_version"], content=output,
            )
            db.add(artifact)
            step.status = "completed"
            step.finished_at = now()
            event(db, run_id, "step_completed", step.step_key, artifact_id=artifact.id,
                  duration_seconds=(step.finished_at-step.started_at).total_seconds())
            db.commit()
    except Exception as exc:
        _fail_step(run_id, step_id, f"Artifact could not be stored: {type(exc).__name__}: {exc}")


async def execute(run_id: str, model_call=None):
    model_call = model_call or call_model
    current = asyncio.current_task()
    other = _ACTIVE.get(run_id)
    if other is not None and other is not current and not other.done():
        return
    _ACTIVE[run_id] = current
    try:
        with SessionLocal() as db:
            run = db.get(CMHWorkflowRun, run_id)
            if not run or run.status not in {"pending", "interrupted", "paused"}:
                return
            run.status = "running"
            run.started_at = run.started_at or now()
            for step in db.query(CMHWorkflowStep).filter(CMHWorkflowStep.run_id == run_id,
                                                        CMHWorkflowStep.status == "interrupted").all():
                step.status = "pending"
            event(db, run_id, "run_started")
            db.commit()
        while True:
            with SessionLocal() as db:
                run = db.get(CMHWorkflowRun, run_id)
                if run.status != "running":
                    return
                steps = db.query(CMHWorkflowStep).filter(CMHWorkflowStep.run_id == run_id).all()
                done = {s.step_key for s in steps if s.status == "completed"}
                pending = [s for s in steps if s.status == "pending"]
                if not pending:
                    run.status = "completed" if len(done) == len(steps) else "error"
                    run.finished_at = now()
                    event(db, run_id, "run_completed" if run.status == "completed" else "run_error")
                    db.commit()
                    return
                ready = [s.id for s in pending if set(json.loads(s.dependencies)) <= done][:2]
                if not ready:
                    run.status = "error"
                    event(db, run_id, "run_error", error="No runnable step")
                    db.commit()
                    return
                for step in pending:
                    if step.id in ready:
                        config = json.loads(step.config)
                        if config.get("requires_approval") and not config.get("approved"):
                            step.status = "waiting_approval"
                            run.status = "waiting_approval"
                            event(db, run_id, "step_approval_requested", step.step_key)
                            db.commit()
                            return
            # return_exceptions: one failing step must not leave its sibling
            # running as an orphan that stop() can no longer reach.
            outcomes = await asyncio.gather(*(_one(run_id, step_id, model_call) for step_id in ready),
                                            return_exceptions=True)
            for outcome in outcomes:
                if isinstance(outcome, BaseException):
                    logger.error("CMH workflow run %s step failed outside its handler: %r", run_id, outcome)
    except asyncio.CancelledError:
        with SessionLocal() as db:
            run = db.get(CMHWorkflowRun, run_id)
            if run and run.status == "running":
                run.status = "interrupted"
                event(db, run_id, "run_interrupted")
                db.commit()
        raise
    except Exception as exc:
        # A background task has no caller to report to: record the failure so
        # the run never stays "running" until the next restart.
        logger.exception("CMH workflow run %s failed", run_id)
        with SessionLocal() as db:
            run = db.get(CMHWorkflowRun, run_id)
            if run and run.status == "running":
                run.status = "error"
                run.finished_at = now()
                event(db, run_id, "run_error", error=f"{type(exc).__name__}: {exc}"[:1000])
                db.commit()
    finally:
        if _ACTIVE.get(run_id) is current:
            _ACTIVE.pop(run_id, None)


def is_active(run_id) -> bool:
    task = _ACTIVE.get(run_id)
    return task is not None and not task.done()


def _forget(run_id, task):
    if _ACTIVE.get(run_id) is task:
        _ACTIVE.pop(run_id, None)


def start(run_id):
    """Schedule a run on the running event loop; call only from async handlers."""
    if not is_active(run_id):
        task = asyncio.create_task(execute(run_id))
        _ACTIVE[run_id] = task
        # A task cancelled before its first step never runs execute()'s
        # finally, so the registry is also cleaned when the task ends.
        task.add_done_callback(lambda done: _forget(run_id, done))


def stop(run_id):
    task = _ACTIVE.get(run_id)
    if task:
        task.cancel()
