"""Create the five CMH chain agents and their flow definition, idempotently, on the
active database.

Writing to the live database is a §6.4 decision, so the default is a dry run
that changes nothing and prints exactly what it would do. Applying needs
``--apply`` **and** ``--authorized-by``, which records who said yes.

What it guarantees:

* **Idempotent.** An agent is matched by owner and name. A second run updates
  the fields that drifted and creates nothing. Running it twice never produces
  ten agents, and never a second copy of the definition.
* **`CMH Researcher` is preserved.** It is neither deleted nor reused nor
  reactivated: it stays `paused`, as the brief requires.
* **Backed up first.** A copy goes to ``%LOCALAPPDATA%\\Odysseus\\backups``,
  outside the repo and outside OneDrive, with ``integrity_check`` on the source
  before and on the copy after. The copy is taken before the first write, not
  after — a copy taken afterwards records the damage, not the state to restore.
  The name carries seconds and is never reused: two seedings in one minute used
  to overwrite the first copy with the state after the first run.
* **Zero cost.** Each agent's twin task is pointed at the first free candidate
  the router resolves, and never at a paid endpoint.
* **The policy is stored.** Every agent carries the ``--policy`` it was seeded
  under. It used to be validated, used to resolve candidates and then dropped, so
  ``--policy local-only`` left ``NULL`` on the agents and the run resolved
  free-cloud-first: five agents in the cloud under a banner that said local.
* **It does not seed an empty chain.** With no free endpoint registered the five
  agents would have no model and no flow could run, so ``--apply`` stops; it needs
  ``--allow-pending`` to go ahead. Register the endpoints first (U1, U4, U5).
* **The flow definition is created here**, once, with the shape /cmh builds:
  five steps, independence for verifier and reviewer, evidence required except
  for reviewer and documenter, and the human gate before the reviewer until step
  5.4 replaces it with the counts gate. A definition that already exists is left
  alone when identical; when it differs, a NEW VERSION is written: definitions
  are never edited in place.

Usage:
    python scripts/cmh_seed_agents.py                     # dry run
    python scripts/cmh_seed_agents.py --apply --authorized-by "<nombre>"
"""

import argparse
import datetime
import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import uuid

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

WORKSPACES = pathlib.Path(os.environ.get("CMH_AGENT_WORKSPACES")
                          or REPO / "data" / "agent_workspace")
READ_TOOLS = ["glob", "grep", "ls", "read_file"]
PRESERVE = "CMH Researcher"

#: role -> (display name, role description). Order is the chain's order.
AGENTS = [
    ("investigador", "Investigador", "Resuelve dudas de contexto de la cadena CMH"),
    ("constructor", "Constructor", "Construye el artefacto del entregable"),
    ("verificador", "Verificador", "Cuenta y reporta, sin interpretar"),
    ("revisor", "Revisor", "Emite veredicto independiente sobre el artefacto"),
    ("documentador", "Documentador", "Cierra el ciclo y prepara el registro"),
]

#: The definition, in the shape /cmh builds (static/cmh-control.js: flowDeps and
#: flowDefinitionBody). The brief writes an arrow in the name; it is spelled "a"
#: here because a Windows console in cp1252 cannot print U+2192, and printing the
#: name crashed the script AFTER it had written to the database, in the summary.
DEFINITION_NAME = "Cadena CMH: investigación a documentación"
FLOW_DEPENDS = {
    "investigador": [], "constructor": ["investigador"], "verificador": ["constructor"],
    "revisor": ["constructor", "verificador"], "documentador": ["constructor", "revisor"],
}
INDEPENDENT_OF = {"verificador": ["constructor"], "revisor": ["constructor"]}
#: Reviewer and documenter work on the artifacts they receive, not on files
#: (ADR-023), so a tool-evidence guard would fail them for doing their job.
NO_TOOL_EVIDENCE = {"revisor", "documentador"}
#: The human gate before the reviewer. Until step 5.4 there is no counts gate.
HUMAN_GATE = {"revisor"}


def backup_database(db_path: pathlib.Path, reason: str) -> pathlib.Path:
    """Copy the live database outside the repo and OneDrive, verifying both ends."""
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError("LOCALAPPDATA no definido: no hay ruta de copias segura")
    target_dir = pathlib.Path(local) / "Odysseus" / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = target_dir / f"app-{reason}-{stamp}.db"
    # Never reuse a name. The minute-resolution stamp let a second seeding within
    # the same minute overwrite the first copy with the state AFTER the first run,
    # which is exactly the case the copy exists to protect against.
    counter = 1
    while target.exists():
        counter += 1
        target = target_dir / f"app-{reason}-{stamp}-{counter}.db"

    source = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    before = source.execute("PRAGMA integrity_check").fetchone()[0]
    if before != "ok":
        source.close()
        raise RuntimeError(f"La base activa no pasa integrity_check: {before}")
    destination = sqlite3.connect(str(target))
    source.backup(destination)
    destination.close()
    source.close()
    check = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True)
    after = check.execute("PRAGMA integrity_check").fetchone()[0]
    check.close()
    if after != "ok":
        raise RuntimeError(f"La copia no pasa integrity_check: {after}")
    print(f"Copia previa: {target} ({target.stat().st_size} bytes), "
          f"integrity origen={before} copia={after}")
    return target


def instructions_for(role: str) -> str:
    path = WORKSPACES / role / "_sistema" / "instrucciones_v1.md"
    if not path.is_file():
        raise SystemExit(
            f"Faltan las instrucciones derivadas de '{role}'. "
            f"Corre antes: python scripts/cmh_seed/scrub_instructions.py")
    return path.read_text(encoding="utf-8")


def live_database_path() -> pathlib.Path:
    """Where the live database is, WITHOUT importing core.database.

    Importing it runs ``init_db()``, which applies migrations to whatever
    ``DATABASE_URL`` points at. Measured on 2026-09-28: a bare import created a
    new table on a file-backed copy. So the backup has to be taken before the
    import, which means resolving the path without it.
    """
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("sqlite:///"):
        tail = url[len("sqlite:///"):]
        if tail == ":memory:":
            return pathlib.Path("")
        path = pathlib.Path(tail)
        # core.database resolves a relative path against the app root; so do we.
        return path if path.is_absolute() else REPO / path
    # The same rule core.database follows when DATABASE_URL is not set: the file
    # lives in ODYSSEUS_DATA_DIR. Ignoring the variable meant that, after the data
    # folder was moved out of OneDrive (BLOCKING decision 22.1), --apply would back
    # up the OLD file or none at all, and then write to the new one with no copy.
    data_dir = os.environ.get("ODYSSEUS_DATA_DIR")
    return (pathlib.Path(data_dir) if data_dir else REPO / "data") / "app.db"


def plan(db, owner: str, project_id: str, policy: str) -> list[dict]:
    """What each of the five agents should look like. No writes."""
    from core.database import CMHAgent
    from src.cmh_provider_router import resolve_candidates

    candidates = resolve_candidates(db, policy, owner)
    model = candidates[0]["model"] if candidates else None
    endpoint_url = candidates[0]["endpoint_url"] if candidates else None
    rows = []
    for role, name, description in AGENTS:
        workspace = WORKSPACES / role
        existing = db.query(CMHAgent).filter(CMHAgent.owner == owner,
                                             CMHAgent.name == name).first()
        rows.append({
            "role": role, "name": name, "description": description,
            "workspace": str(workspace), "model": model, "endpoint_url": endpoint_url,
            "instructions": instructions_for(role),
            "candidates": candidates, "policy": policy,
            "project_id": project_id,
            "action": "actualizar" if existing else "crear",
            "existing_id": existing.id if existing else None,
        })
    return rows


def definition_steps(agent_ids: dict) -> list[dict]:
    """The five steps as /cmh builds them, before validate_dag normalises them."""
    return [{"key": role, "agent_id": agent_ids[role], "depends_on": FLOW_DEPENDS[role],
             "independent_of": INDEPENDENT_OF.get(role, []),
             "requires_approval": role in HUMAN_GATE,
             "require_tool_evidence": role not in NO_TOOL_EVIDENCE}
            for role, _, _ in AGENTS]


def ensure_definition(db, owner: str, project_id: str, agent_ids: dict) -> dict:
    """Create the flow definition once; write a new VERSION when it differs.

    Definitions are never edited in place: a run freezes the steps it started
    from, and a stored definition that changed under it would no longer say what
    ran. An identical one is left alone, which is what makes a second seeding a
    no-op instead of a second copy.
    """
    from core.database import CMHWorkflowDefinition
    from src.cmh_workflows import validate_dag

    steps = validate_dag(definition_steps(agent_ids))
    existing = (db.query(CMHWorkflowDefinition)
                .filter(CMHWorkflowDefinition.owner == owner,
                        CMHWorkflowDefinition.project_id == project_id,
                        CMHWorkflowDefinition.name == DEFINITION_NAME)
                .order_by(CMHWorkflowDefinition.version).all())
    latest = existing[-1] if existing else None
    if latest is not None and json.loads(latest.steps) == steps:
        return {"id": latest.id, "version": latest.version, "action": "igual"}
    row = CMHWorkflowDefinition(id=str(uuid.uuid4()), owner=owner, project_id=project_id,
                                name=DEFINITION_NAME,
                                version=(latest.version + 1) if latest else 1,
                                steps=json.dumps(steps))
    db.add(row)
    db.flush()
    return {"id": row.id, "version": row.version,
            "action": "nueva version" if latest else "creada"}


def apply(db, rows: list[dict], owner: str) -> dict:
    from core.database import CMHAgent, ScheduledTask

    agent_ids = {}
    for row in rows:
        agent = (db.query(CMHAgent).filter(CMHAgent.id == row["existing_id"]).first()
                 if row["existing_id"] else None)
        # The task is resolved first, because creating it needs a flush and a
        # flush would push a half-built agent to a NOT NULL column. Measured:
        # adding the agent first failed on cmh_agents.role.
        task = (db.query(ScheduledTask).filter(ScheduledTask.id == agent.task_id).first()
                if agent is not None and agent.task_id else None)
        if task is None:
            task = ScheduledTask(id=str(uuid.uuid4()), owner=owner, task_type="llm",
                                 prompt="Gestionada por el motor de flujos CMH.",
                                 trigger_type="manual", email_results=False,
                                 notifications_enabled=False)
            db.add(task)
            db.flush()
        if agent is None:
            agent = CMHAgent(id=uuid.uuid4().hex, owner=owner, name=row["name"],
                             role=row["description"], instructions=row["instructions"],
                             instructions_version=1)
            db.add(agent)
        elif agent.instructions != row["instructions"]:
            # A changed instruction is a new version, never a silent overwrite:
            # a frozen run records the version it ran under.
            agent.instructions_version = (agent.instructions_version or 1) + 1
        task.name = f"{row['name']} (agente CMH)"
        task.status = "paused"
        task.model = row["model"]
        task.endpoint_url = row["endpoint_url"]
        task.workspace = row["workspace"]
        task.allowed_tools = json.dumps(READ_TOOLS)

        agent.project_id = row["project_id"]
        agent.role = row["description"]
        agent.instructions = row["instructions"]
        agent.model = row["model"]
        agent.allowed_tools = json.dumps(READ_TOOLS)
        agent.workspace = row["workspace"]
        agent.status = "active"
        agent.task_id = task.id
        # Stored, not just used to resolve the candidates: NULL here meant "no
        # opinion", and the run then resolved free-cloud-first.
        agent.provider_policy = row["policy"]
        db.flush()
        agent_ids[row["role"]] = agent.id
    definition = ensure_definition(db, owner, rows[0]["project_id"], agent_ids)
    db.commit()
    return definition


def main() -> int:
    # A print must never be what stops this script. Its summary comes after the
    # database write, and a console that cannot encode a character (cp1252 has no
    # arrows) would otherwise end it with a traceback instead of a report.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        return _main()
    finally:
        if _SCRATCH[0] is not None:
            # Windows refuses to delete a file the engine still holds open, and
            # a failed unlink here is how 118 replicas of the database piled up
            # in %TEMP%. Close the pool first, then report loudly if the file
            # still survives rather than leaving it there in silence.
            try:
                import sys as _sys
                engine = getattr(_sys.modules.get("core.database"), "engine", None)
                if engine is not None:
                    engine.dispose()
            except Exception:
                pass
            try:
                _SCRATCH[0].unlink(missing_ok=True)
            except OSError as exc:
                print(f"AVISO: no se pudo borrar la copia de simulacion "
                      f"{_SCRATCH[0]}: {exc}. Borrala a mano: es una replica "
                      f"completa de la base.")
            _SCRATCH[0] = None


_SCRATCH = [None]


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="write to the live database (needs --authorized-by)")
    parser.add_argument("--authorized-by", default="",
                        help="who authorised this write, recorded in the output")
    parser.add_argument("--owner", default=None, help="defaults to the single account")
    parser.add_argument("--project", default="ecosistema-de-agentes")
    parser.add_argument("--policy", default="free-cloud-first")
    parser.add_argument("--allow-pending", action="store_true",
                        help="seed even when no free endpoint is registered yet (the agents "
                             "get no model until the script is run again)")
    args = parser.parse_args()

    if args.apply and not args.authorized_by.strip():
        print("Escribir en la base activa exige --authorized-by (decision §6.4).")
        return 2

    from src.cmh_provider_router import PROVIDER_POLICIES, normalize_policy
    policy = normalize_policy(args.policy)
    if policy is None:
        print(f"--policy '{args.policy}' no existe. "
              f"Validas: {', '.join(sorted(PROVIDER_POLICIES))}.")
        print("Un error de tecleo aqui apuntaria los cinco agentes a la nube.")
        return 2

    # BEFORE anything that can touch the database. The rules now live in
    # src.cmh_protected_areas, which imports no database, so refusing a
    # forbidden workspace root costs nothing: the previous version imported
    # routes.cmh_control_routes here and core.database's init_db() migrated the
    # live schema before printing "nothing was seeded".
    from src.cmh_protected_areas import protected_area
    area = protected_area(WORKSPACES) if WORKSPACES.exists() else None
    if area:
        print(f"La raiz de workspaces '{WORKSPACES}' esta dentro de, o contiene, "
              f"el area protegida '{area}'. No se siembra nada.")
        return 2

    # Validate the inputs before touching anything. An earlier version copied
    # the database and then aborted for missing instructions, leaving a backup
    # behind under a banner that said nothing was written.
    for role, _, _ in AGENTS:
        instructions_for(role)

    # Before the import, not after: importing core.database runs init_db(),
    # which MIGRATES whatever DATABASE_URL points at. Skipping the copy for a
    # dry run was wrong twice over — the import still migrated the live file,
    # and now without a backup. A dry run works on a throwaway copy instead, so
    # the live database is never opened at all and the plan is still computed
    # against real data. Measured on 2026-09-29: before this, a dry run
    # recreated cmh_provider_quota and left no copy behind.
    db_path = live_database_path()
    scratch = None
    if args.apply:
        if db_path.is_file():
            backup_database(db_path, "before-seed-agents")
    elif db_path.is_file():
        scratch = pathlib.Path(tempfile.gettempdir()) / f"cmh-seed-dryrun-{os.getpid()}.db"
        _SCRATCH[0] = scratch   # removed in main()'s finally, however this ends
        # mode=ro is defence, not a measurable guarantee: SQLite happily opens a
        # read-only file read-write until something writes, so a mutant that
        # drops it has no observable effect here. Kept, and declared as
        # unmeasured rather than covered by a test that cannot fail.
        source = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        destination = sqlite3.connect(str(scratch))
        source.backup(destination)
        destination.close()
        source.close()
        os.environ["DATABASE_URL"] = f"sqlite:///{scratch.as_posix()}"
        print(f"SIMULACION sobre una copia desechable: {scratch}")
        print(f"La base real ({db_path}) solo se lee para copiarla; no se migra.")

    from core.database import CMHAgent, SessionLocal

    with SessionLocal() as db:
        owner = args.owner or (db.query(CMHAgent.owner).first() or ("mijhael hartley",))[0]
        rows = plan(db, owner, args.project, policy)
        preserved = db.query(CMHAgent).filter(CMHAgent.name == PRESERVE).first()

    print(f"Base: {db_path}")
    print(f"Owner: {owner} · proyecto: {args.project} · politica: {policy}")
    print(f"Candidatos resueltos: "
          f"{[c['endpoint_id'] for c in rows[0]['candidates']] or 'NINGUNO'}")
    if not rows[0]["candidates"]:
        print("  PENDIENTE: no hay ningun endpoint gratuito registrado todavia. "
              "Los agentes quedarian sin modelo y ningun flujo podria ejecutarse.")
    print(f"\n{'accion':12} {'rol':14} {'nombre':14} {'instrucciones':>13}  workspace")
    for row in rows:
        print(f"{row['action']:12} {row['role']:14} {row['name']:14} "
              f"{len(row['instructions'].splitlines()):13}  {row['workspace']}")
    print(f"\nDefinicion de flujo: '{DEFINITION_NAME}' - se crea una vez; una version nueva "
          f"solo si sus pasos difieren de la guardada.")
    if preserved:
        print(f"Se conserva sin tocar: '{PRESERVE}' (id {preserved.id}, "
              f"estado {preserved.status}).")

    if not args.apply:
        print("\nSIMULACION: no se escribio nada. Para aplicar:")
        print('  python scripts/cmh_seed_agents.py --apply --authorized-by "<nombre>"')
        return 0

    if not rows[0]["candidates"] and not args.allow_pending:
        # After the backup, not before: the candidates need the database, and
        # opening it is what migrates it, so the copy has to exist first.
        print("\nNo se escribio nada: no hay ningun endpoint gratuito registrado, asi que "
              "los cinco agentes quedarian sin modelo y ningun flujo podria ejecutarse.")
        print("Registra antes Groq, LM Studio y deshabilita Ollama (U1, U4, U5), o usa "
              "--allow-pending para sembrar igual.")
        print("La copia previa de arriba se hizo antes de abrir la base; puedes borrarla.")
        return 2

    with SessionLocal() as db:
        definition = apply(db, rows, owner)
        total = db.query(CMHAgent).filter(CMHAgent.owner == owner).count()
        active = db.query(CMHAgent).filter(CMHAgent.owner == owner,
                                           CMHAgent.status == "active").count()
        still = db.query(CMHAgent).filter(CMHAgent.name == PRESERVE).first()
    print(f"\nAplicado, autorizado por: {args.authorized_by}")
    print(f"Agentes del owner: {total} · activos: {active}")
    print(f"Definicion '{DEFINITION_NAME}': {definition['action']} · "
          f"id {definition['id']} · version {definition['version']}")
    if still:
        print(f"'{PRESERVE}' sigue en estado: {still.status}")
    if db_path.is_file():
        check = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        print("integrity_check posterior:",
              check.execute("PRAGMA integrity_check").fetchone()[0])
        check.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
