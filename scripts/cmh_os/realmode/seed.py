"""Seed a THROWAWAY Odysseus database with synthetic CMH data.

Nothing here touches the user's instance: DATABASE_URL and ODYSSEUS_DATA_DIR
point at a scratch directory, and every name and number is invented.
"""
import json
import os
import sys

from core.database import (
    Base, CMHAgent, CMHWorkflowArtifact, CMHWorkflowDefinition, CMHWorkflowEvent,
    CMHWorkflowRun, CMHWorkflowStep, ScheduledTask, SessionLocal, engine, init_db, utcnow_naive,
)

OWNER = sys.argv[1]
PROJECT = "ecosistema-de-agentes"
WORKSPACE = os.environ["SEED_WORKSPACE"]

init_db()
Base.metadata.create_all(bind=engine)

STEPS = [
    {"key": "investigador", "agent_id": "agent-investigador", "depends_on": []},
    {"key": "revisor", "agent_id": "agent-revisor", "depends_on": ["investigador"],
     "requires_approval": True, "independent_of": ["investigador"]},
]

with SessionLocal() as db:
    for key, role in (("investigador", "Investigación"), ("revisor", "Revisión")):
        db.add(ScheduledTask(id=f"task-{key}", owner=OWNER, name=f"CMH {role} (sintético)",
                             task_type="llm", endpoint_url="http://modelo.invalido/v1/chat/completions",
                             model="modelo-sintetico", prompt="entrada sintética", status="paused"))
        db.add(CMHAgent(id=f"agent-{key}", owner=OWNER, name=f"CMH {role}", project_id=PROJECT,
                        role=role, instructions=f"Instrucciones sintéticas de {role}.",
                        instructions_version=1, model="modelo-sintetico",
                        allowed_tools=json.dumps(["read_file", "ls", "grep", "glob"]),
                        workspace=WORKSPACE, status="active", task_id=f"task-{key}"))

    db.add(CMHWorkflowDefinition(id="flow-1", owner=OWNER, project_id=PROJECT,
                                 name="Cadena sintética de dos pasos", version=1,
                                 steps=json.dumps(STEPS, ensure_ascii=False)))

    db.add(CMHWorkflowRun(id="run-sintetico", owner=OWNER, definition_id="flow-1",
                          project_id=PROJECT, status="waiting_approval",
                          initial_input="Entrada sintética para la prueba de modo real.",
                          started_at=utcnow_naive()))

    frozen = {"model": "modelo-sintetico", "endpoint_url": "http://modelo.invalido/v1/chat/completions",
              "workspace": WORKSPACE, "allowed_tools": ["read_file", "ls", "grep", "glob"],
              "instructions_version": 1, "instructions": "sintéticas"}
    db.add(CMHWorkflowStep(id="step-inv", run_id="run-sintetico", step_key="investigador",
                           agent_id="agent-investigador", config=json.dumps(frozen, ensure_ascii=False),
                           dependencies=json.dumps([]), status="completed",
                           started_at=utcnow_naive(), finished_at=utcnow_naive()))
    rev = dict(frozen, requires_approval=True, approved=False)
    db.add(CMHWorkflowStep(id="step-rev", run_id="run-sintetico", step_key="revisor",
                           agent_id="agent-revisor", config=json.dumps(rev, ensure_ascii=False),
                           dependencies=json.dumps(["investigador"]), status="waiting_approval"))

    db.add(CMHWorkflowArtifact(id="art-inv", run_id="run-sintetico", step_key="investigador",
                               agent_id="agent-investigador", model="modelo-sintetico",
                               instructions_version=1,
                               content="Nota de investigación sintética con evidencia inventada."))

    for kind, step_key in (("run_created", None), ("run_started", None),
                           ("step_started", "investigador"), ("step_completed", "investigador"),
                           ("step_approval_requested", "revisor")):
        db.add(CMHWorkflowEvent(run_id="run-sintetico", kind=kind, step_key=step_key,
                                payload=json.dumps({}, ensure_ascii=False)))
    db.commit()

with SessionLocal() as db:
    print("SEED_OK agentes=%d flujos=%d ejecuciones=%d pasos=%d eventos=%d" % (
        db.query(CMHAgent).count(), db.query(CMHWorkflowDefinition).count(),
        db.query(CMHWorkflowRun).count(), db.query(CMHWorkflowStep).count(),
        db.query(CMHWorkflowEvent).count()))
