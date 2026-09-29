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
             "requires_approval": bool(s.get("requires_approval", False)),
             "require_tool_evidence": bool(s["require_tool_evidence"])
             if s.get("require_tool_evidence") is not None
             else default_tool_evidence(s["key"]),
             "provider_policy": _checked_policy(s.get("provider_policy"), s["key"])}
            for s in steps]


def _checked_policy(value, step_key: str):
    """A recognised policy name, None, or a refusal.

    `local_only` with an underscore used to be accepted, degraded to None and
    silently routed to the cloud. The one setting whose whole purpose is that
    nothing leaves the machine cannot fail open on a typo.
    """
    from src.cmh_provider_router import PROVIDER_POLICIES, normalize_policy

    if value in (None, ""):
        return None
    policy = normalize_policy(value)
    if policy is None:
        raise ValueError(
            f"Step {step_key}: provider_policy '{value}' no existe. "
            f"Validos: {', '.join(sorted(PROVIDER_POLICIES))}")
    return policy


#: Steps that work on the artifacts they were handed rather than on files, so
#: demanding a successful tool call from them would fail every run. Their own
#: derived instructions tell them to read the input artifacts, not the disk.
_NO_EVIDENCE_ROLES = frozenset({"revisor", "revisor-cmh", "documentador"})


def default_tool_evidence(step_key: str) -> bool:
    """Whether a step must ground its artifact in a successful tool call.

    True for everything except the reviewer and the documenter. The default
    lives here, not in the browser: a definition created by script, by the API
    or by a future screen must land on the same answer, and an earlier version
    of this defaulted every step to True — which would have failed the reviewer
    on every single run while the commit message claimed it was "per role".
    """
    return str(step_key or "").strip().lower() not in _NO_EVIDENCE_ROLES


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


def _frozen_candidates(config: dict) -> list[dict]:
    """The step's candidate list, as the run froze it.

    A run created before the router existed froze a single ``endpoint_url`` and
    ``model``; it is read as a one-entry list, so an old run still executes.

    Every entry is completed with ``endpoint_id`` and ``host``, because the
    quota accounting and the fallback events index on them. Leaving the legacy
    shape incomplete made ``CMH_ZERO_COST=false`` die with ``KeyError:
    'endpoint_id'`` in the one branch that is supposed to degrade to logging.
    """
    from src.cmh_cost_policy import endpoint_host

    candidates = config.get("candidates") or [
        {"endpoint_url": config["endpoint_url"], "model": config["model"]}
    ]
    complete = []
    for candidate in candidates:
        entry = dict(candidate)
        # Assignment, not setdefault. A frozen candidate can carry the key with
        # value None, and setdefault leaves None in place — which then reaches
        # record_usage and violates cmh_provider_quota.endpoint_id NOT NULL
        # AFTER the step has already produced its artifact, losing the work.
        if not entry.get("endpoint_id"):
            entry["endpoint_id"] = entry.get("endpoint_url")
        if not entry.get("host"):
            entry["host"] = endpoint_host(entry.get("endpoint_url"))
        complete.append(entry)
    return complete


def _zero_cost_candidates(config: dict, record) -> list[dict]:
    """The step's candidates that are free to call, in order (D1).

    Every rejected candidate emits ``zero_cost_blocked`` whether or not the
    gate is enforcing, so ``CMH_ZERO_COST=false`` is diagnosable and not silent.
    Each survivor is completed with the endpoint id and host the quota
    accounting needs, so the row we charge is the row we called.
    """
    from src.cmh_cost_policy import endpoint_for_url, endpoint_host, is_zero_cost_endpoint

    allowed = []
    with SessionLocal() as db:
        for candidate in _frozen_candidates(config):
            url, model = candidate.get("endpoint_url"), candidate.get("model")
            row = endpoint_for_url(db, url, config.get("owner"), model)
            endpoint = row or {"base_url": url, "endpoint_kind": "auto", "id": "no registrado"}
            if not is_zero_cost_endpoint(endpoint, model):
                record("zero_cost_blocked", endpoint_url=url, candidate_model=model)
                continue
            # A registered row's id wins over the URL placeholder that
            # _frozen_candidates filled in: quota is charged per endpoint row,
            # and charging a URL string would split one provider's counter.
            if getattr(row, "id", None):
                candidate["endpoint_id"] = row.id
            candidate.setdefault("endpoint_id", url)
            candidate["host"] = endpoint_host(url)
            allowed.append(candidate)
    return allowed


async def _run_one_candidate(config: dict, candidate: dict, prompt: str, record) -> str:
    from src.task_scheduler import TaskScheduler
    task = SimpleNamespace(
        owner=config["owner"], name=config["name"], prompt=prompt,
        workspace=config["workspace"], allowed_tools=json.dumps(config["allowed_tools"]),
        max_steps=config.get("max_rounds", 12),
    )
    return await TaskScheduler(None)._run_agent_loop(
        candidate["endpoint_url"], candidate["model"], task, str(uuid.uuid4()),
        system_prompt=config["instructions"], override_user_message=prompt,
        foreground_controlled=True, event_sink=record,
        # Canon 06 pending of 2026-09-24: call_model never switched this on, so
        # a step that made zero tool calls still passed. Now the definition
        # decides it per role and the run freezes the answer.
        require_tool_evidence=bool(config.get("require_tool_evidence", True)),
    )


async def call_model(config: dict, prompt: str) -> str:
    """Walk the step's frozen candidates until one answers (D1, D3).

    Order of elimination is deliberate: cost first, because a paid route must
    never be attempted even when everything else has failed; then quota, which
    is checked before sending so the call that would cross the line is never
    made; then reachability, which can only be learned by trying. A step whose
    candidates are all gone fails. It never falls back to a paid endpoint.
    """
    from src.cmh_cost_policy import ZeroCostViolation, enforced
    from src.cmh_provider_router import is_fallback_error, record_usage, usable_candidates

    # The model label follows whichever candidate is actually answering. It
    # used to report config["model"] always, so a fallback event was stamped
    # with the model that did NOT produce it.
    active = {"model": config["model"]}

    def record(kind, **payload):
        with SessionLocal() as db:
            event(db, config["run_id"], kind, config["step_key"],
                  agent_id=config["agent_id"], model=active["model"], **payload)
            db.commit()

    free = _zero_cost_candidates(config, record)
    if not free:
        if enforced():
            raise ZeroCostViolation(
                f"Costo cero (D1): el paso {config['step_key']} no tiene ningun "
                f"candidato gratuito; no se usa respaldo de pago.")
        free = _frozen_candidates(config)

    with SessionLocal() as db:
        ready, skipped = usable_candidates(db, free)
    for candidate in skipped:
        record("provider_fallback", **{"from": candidate.get("endpoint_id"),
                                       "to": None, "reason": candidate["reason"]})
    if not ready:
        raise RuntimeError(
            f"Todos los candidatos del paso {config['step_key']} estan sin cuota; "
            f"no se usa respaldo de pago.")

    last_error: Exception | None = None
    for index, candidate in enumerate(ready):
        active["model"] = candidate.get("model") or config["model"]
        try:
            output = await _run_one_candidate(config, candidate, prompt, record)
        except asyncio.CancelledError:
            raise  # a stop is not a provider failure
        except Exception as exc:
            reason = is_fallback_error(exc)
            if reason is None:
                raise  # a configuration fault the next provider would hit too
            following = ready[index + 1]["endpoint_id"] if index + 1 < len(ready) else None
            record("provider_fallback", **{"from": candidate.get("endpoint_id"),
                                           "to": following, "reason": reason})
            last_error = exc
            continue
        with SessionLocal() as db:
            record_usage(db, candidate["endpoint_id"], requests=1)
            db.commit()
        # Tell the caller which candidate produced this, so the artifact it
        # stores carries the model that wrote it rather than the first one on
        # the list. Mutating the step's live config is deliberate: `_one`
        # already holds it and reads it back when it writes the artifact.
        config["resolved_model"] = candidate.get("model") or config["model"]
        config["resolved_endpoint_id"] = candidate.get("endpoint_id")
        return output
    raise RuntimeError(
        f"Ningun candidato gratuito respondio en el paso {config['step_key']}: "
        f"{type(last_error).__name__}: {last_error}")


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
                agent_id=step.agent_id,
                # The candidate that answered, not the first one frozen. With a
                # fallback these differ, and the artifact is what a person opens.
                model=config.get("resolved_model") or config["model"],
                instructions_version=config["instructions_version"], content=output,
            )
            db.add(artifact)
            # Persist which candidate answered, or the run detail keeps showing
            # the first one frozen: call_model mutates the in-memory config and
            # `/runs/{id}` re-reads step.config from the database.
            if config.get("resolved_model"):
                step.config = json.dumps(config)
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
