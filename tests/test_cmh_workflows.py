"""Workflow dependencies, parallel cap, durable artifacts, and resume."""

import asyncio
import json
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as cdb
from src import cmh_workflows as flow


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(flow, "SessionLocal", factory)
    yield factory
    engine.dispose()


def seed(factory, specs):
    run_id = str(uuid.uuid4())
    with factory() as session:
        session.add(cdb.CMHWorkflowRun(id=run_id, owner="admin", definition_id="definition",
                                       project_id="project", status="pending", initial_input="synthetic"))
        for key, dependencies in specs:
            session.add(cdb.CMHWorkflowStep(id=str(uuid.uuid4()), run_id=run_id, step_key=key,
                                            agent_id=key, config=json.dumps({"owner": "admin", "name": key,
                                            "model": key, "instructions_version": 1}),
                                            dependencies=json.dumps(dependencies), status="pending"))
        session.commit()
    return run_id


def test_validate_dag_rejects_cycles_and_unknown_dependencies():
    with pytest.raises(ValueError, match="cycle"):
        flow.validate_dag([{"key": "a", "agent_id": "1", "depends_on": ["b"]},
                           {"key": "b", "agent_id": "2", "depends_on": ["a"]}])
    with pytest.raises(ValueError, match="dependency"):
        flow.validate_dag([{"key": "a", "agent_id": "1", "depends_on": ["missing"]}])


async def test_parallel_steps_join_then_resume_without_duplicate_artifacts(db):
    run_id = seed(db, [("research", []), ("construct", []), ("verify", ["research", "construct"])])
    active = 0
    peak = 0
    calls = []

    async def fake(config, prompt):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        calls.append(config["model"])
        await asyncio.sleep(0.01)
        active -= 1
        if config["model"] == "verify":
            assert "artifact" in prompt and "research" in prompt and "construct" in prompt
        return config["model"] + " evidence"

    await flow.execute(run_id, model_call=fake)
    with db() as session:
        assert session.get(cdb.CMHWorkflowRun, run_id).status == "completed"
        assert session.query(cdb.CMHWorkflowArtifact).filter_by(run_id=run_id).count() == 3
        assert session.query(cdb.CMHWorkflowEvent).filter_by(run_id=run_id).count() >= 8
    assert peak == 2
    await flow.execute(run_id, model_call=fake)
    assert calls == ["research", "construct", "verify"]


async def test_restart_marks_only_inflight_step_interrupted(db):
    run_id = seed(db, [("a", []), ("b", ["a"])])
    with db() as session:
        run = session.get(cdb.CMHWorkflowRun, run_id)
        run.status = "running"
        a = session.query(cdb.CMHWorkflowStep).filter_by(run_id=run_id, step_key="a").one()
        a.status = "completed"
        a.started_at = flow.now()
        a.finished_at = flow.now()
        session.add(cdb.CMHWorkflowArtifact(id="artifact-a", run_id=run_id, step_key="a", agent_id="a",
                                            model="a", instructions_version=1, content="done"))
        b = session.query(cdb.CMHWorkflowStep).filter_by(run_id=run_id, step_key="b").one()
        b.status = "running"
        session.commit()
    flow.reconcile_interrupted_runs()
    with db() as session:
        assert session.get(cdb.CMHWorkflowRun, run_id).status == "interrupted"
        assert session.query(cdb.CMHWorkflowStep).filter_by(run_id=run_id, step_key="a").one().status == "completed"
    calls = []

    async def fake(config, prompt):
        calls.append(config["model"])
        return "resumed"

    await flow.execute(run_id, model_call=fake)
    assert calls == ["b"]
    with db() as session:
        assert session.query(cdb.CMHWorkflowArtifact).filter_by(run_id=run_id).count() == 2


async def test_stop_before_task_starts_does_not_leave_run_marked_active(db):
    run_id = seed(db, [("a", [])])
    flow.start(run_id)
    flow.stop(run_id)  # cancelled before the coroutine body ever runs: its finally never executes
    for _ in range(50):
        if not flow.is_active(run_id):
            break
        await asyncio.sleep(0.01)
    assert not flow.is_active(run_id)
    assert run_id not in flow._ACTIVE


def test_restart_recovers_runs_that_never_started(db):
    run_id = seed(db, [("a", [])])
    flow.reconcile_interrupted_runs()
    with db() as session:
        assert session.get(cdb.CMHWorkflowRun, run_id).status == "interrupted"


async def test_cmh_five_step_chain_gives_reviewer_deliverable_and_verification_only(db):
    run_id = seed(db, [("investigador", []), ("constructor", ["investigador"]),
                       ("verificador", ["constructor"]), ("revisor", ["constructor", "verificador"]),
                       ("documentador", ["constructor", "revisor"])])
    prompts = {}

    async def fake(config, prompt):
        prompts[config["model"]] = prompt
        return config["model"].upper() + "-ARTIFACT"

    await flow.execute(run_id, model_call=fake)
    assert list(prompts) == ["investigador", "constructor", "verificador", "revisor", "documentador"]
    reviewer = prompts["revisor"]
    assert "CONSTRUCTOR-ARTIFACT" in reviewer and "VERIFICADOR-ARTIFACT" in reviewer
    assert "INVESTIGADOR-ARTIFACT" not in reviewer
    assert "REVISOR-ARTIFACT" in prompts["documentador"]
    with db() as session:
        assert session.get(cdb.CMHWorkflowRun, run_id).status == "completed"
        assert session.query(cdb.CMHWorkflowArtifact).filter_by(run_id=run_id).count() == 5


def test_validate_dag_rejects_reviewer_sharing_the_builders_agent():
    steps = [{"key": "constructor", "agent_id": "same"},
             {"key": "revisor", "agent_id": "same", "depends_on": ["constructor"],
              "independent_of": ["constructor"]}]
    with pytest.raises(ValueError, match="different agent"):
        flow.validate_dag(steps)
    steps[1]["agent_id"] = "other"
    assert flow.validate_dag(steps)[1]["independent_of"] == ["constructor"]
    with pytest.raises(ValueError, match="list of step keys"):
        flow.validate_dag([{"key": "a", "agent_id": "1", "depends_on": [1]}])


async def test_failed_sibling_leaves_no_running_step_and_resume_completes(db):
    run_id = seed(db, [("a", []), ("b", []), ("c", ["a", "b"])])
    b_started = asyncio.Event()

    async def first(config, prompt):
        if config["model"] == "a":
            await b_started.wait()
            raise RuntimeError("401 invalid x-api-key")
        b_started.set()
        await asyncio.sleep(0.01)
        return "b evidence"

    await flow.execute(run_id, model_call=first)
    with db() as session:
        steps = {s.step_key: s.status for s in session.query(cdb.CMHWorkflowStep).filter_by(run_id=run_id)}
        assert session.get(cdb.CMHWorkflowRun, run_id).status == "error"
        # A crash while b was still executing would have left it "running".
        session.query(cdb.CMHWorkflowStep).filter_by(run_id=run_id, step_key="b").one().status = "running"
        session.query(cdb.CMHWorkflowArtifact).filter_by(run_id=run_id, step_key="b").delete()
        session.commit()
    assert steps == {"a": "error", "b": "completed", "c": "pending"}
    flow.reconcile_interrupted_runs()  # the run is "error", yet its running step is released
    with db() as session:
        assert session.query(cdb.CMHWorkflowStep).filter_by(run_id=run_id, step_key="b").one().status == "interrupted"
        session.query(cdb.CMHWorkflowStep).filter_by(run_id=run_id, step_key="a").one().status = "interrupted"
        session.get(cdb.CMHWorkflowRun, run_id).status = "interrupted"
        session.commit()

    async def healthy(config, prompt):
        return config["model"] + " evidence"
    await flow.execute(run_id, model_call=healthy)
    with db() as session:
        assert session.get(cdb.CMHWorkflowRun, run_id).status == "completed"
        assert session.query(cdb.CMHWorkflowArtifact).filter_by(run_id=run_id).count() == 3


async def test_failed_artifact_write_marks_step_error_without_orphaning_sibling(db):
    run_id = seed(db, [("a", []), ("b", [])])
    with db() as session:
        # A pre-existing artifact makes a's completion commit violate the unique key.
        session.add(cdb.CMHWorkflowArtifact(id="clash", run_id=run_id, step_key="a", agent_id="a",
                                            model="a", instructions_version=1, content="old"))
        session.commit()
    finished = []

    async def fake(config, prompt):
        await asyncio.sleep(0.05 if config["model"] == "b" else 0)
        finished.append(config["model"])
        return config["model"] + " evidence"

    await flow.execute(run_id, model_call=fake)
    assert sorted(finished) == ["a", "b"]  # execute returned only after b settled
    with db() as session:
        steps = {s.step_key: s for s in session.query(cdb.CMHWorkflowStep).filter_by(run_id=run_id)}
        assert steps["a"].status == "error" and "could not be stored" in steps["a"].error
        assert steps["b"].status == "completed"
        assert session.get(cdb.CMHWorkflowRun, run_id).status == "error"
        kinds = [e.kind for e in session.query(cdb.CMHWorkflowEvent).filter_by(run_id=run_id)]
    assert "run_error" in kinds
    assert not flow.is_active(run_id)


async def test_long_artifact_is_cut_with_a_visible_marker_and_event(db):
    run_id = seed(db, [("constructor", []), ("revisor", ["constructor"])])
    total = flow.MAX_ARTIFACT_INPUT_CHARS + 10_000
    prompts = {}

    async def fake(config, prompt):
        prompts[config["model"]] = prompt
        return "x" * (total - 4) + "COLA" if config["model"] == "constructor" else "veredicto"

    await flow.execute(run_id, model_call=fake)
    reviewer = prompts["revisor"]
    assert "COLA" not in reviewer
    assert f"[TRUNCADO: se incluyen {flow.MAX_ARTIFACT_INPUT_CHARS} de {total} caracteres" in reviewer
    with db() as session:
        stored = session.query(cdb.CMHWorkflowArtifact).filter_by(run_id=run_id, step_key="constructor").one()
        assert len(stored.content) == total
        truncated = session.query(cdb.CMHWorkflowEvent).filter_by(run_id=run_id, kind="step_input_truncated").one()
    assert json.loads(truncated.payload) == {"artifact_id": stored.id,
                                             "included": flow.MAX_ARTIFACT_INPUT_CHARS, "total": total}


async def test_a_restart_never_revives_a_rejected_run(db):
    """A refusal must outlive a server restart: recovery revives running and
    pending work, and a rejected run is neither."""
    run_id = seed(db, [("a", []), ("b", ["a"])])
    with db() as session:
        run = session.get(cdb.CMHWorkflowRun, run_id)
        run.status = "rejected"
        a = session.query(cdb.CMHWorkflowStep).filter_by(run_id=run_id, step_key="a").one()
        a.status = "completed"
        b = session.query(cdb.CMHWorkflowStep).filter_by(run_id=run_id, step_key="b").one()
        b.status = "rejected"
        b.decision = '{"outcome": "rejected", "justification": "Sin evidencia.", "by": "admin", "at": "2026-09-25T00:00:00"}'
        session.commit()
    flow.reconcile_interrupted_runs()
    calls = []

    async def fake(config, prompt):
        calls.append(config["model"])
        return "no debería ejecutarse"

    await flow.execute(run_id, model_call=fake)
    with db() as session:
        run = session.get(cdb.CMHWorkflowRun, run_id)
        step = session.query(cdb.CMHWorkflowStep).filter_by(run_id=run_id, step_key="b").one()
    assert run.status == "rejected"
    assert step.status == "rejected"
    assert step.decision and "Sin evidencia." in step.decision
    assert calls == [], f"the rejected run executed {calls}"
