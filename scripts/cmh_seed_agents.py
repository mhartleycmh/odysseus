"""Create the five CMH chain agents, idempotently, on the active database.

Writing to the live database is a §6.4 decision, so the default is a dry run
that changes nothing and prints exactly what it would do. Applying needs
``--apply`` **and** ``--authorized-by``, which records who said yes.

What it guarantees:

* **Idempotent.** An agent is matched by owner and name. A second run updates
  the fields that drifted and creates nothing. Running it twice never produces
  ten agents.
* **`CMH Researcher` is preserved.** It is neither deleted nor reused nor
  reactivated: it stays `paused`, as the brief requires.
* **Backed up first.** A copy goes to ``%LOCALAPPDATA%\\Odysseus\\backups``,
  outside the repo and outside OneDrive, with ``integrity_check`` on the source
  before and on the copy after. The copy is taken before the first write, not
  after — a copy taken afterwards records the damage, not the state to restore.
* **Zero cost.** Each agent's twin task is pointed at the first free candidate
  the router resolves, and never at a paid endpoint.

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
import uuid

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

WORKSPACES = REPO / "data" / "agent_workspace"
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


def backup_database(db_path: pathlib.Path, reason: str) -> pathlib.Path:
    """Copy the live database outside the repo and OneDrive, verifying both ends."""
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError("LOCALAPPDATA no definido: no hay ruta de copias segura")
    target_dir = pathlib.Path(local) / "Odysseus" / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    target = target_dir / f"app-{reason}-{stamp}.db"

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
        return pathlib.Path("") if tail == ":memory:" else pathlib.Path(tail)
    return REPO / "data" / "app.db"


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


def apply(db, rows: list[dict], owner: str) -> None:
    from core.database import CMHAgent, ScheduledTask

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
    db.commit()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="write to the live database (needs --authorized-by)")
    parser.add_argument("--authorized-by", default="",
                        help="who authorised this write, recorded in the output")
    parser.add_argument("--owner", default=None, help="defaults to the single account")
    parser.add_argument("--project", default="ecosistema-de-agentes")
    parser.add_argument("--policy", default="free-cloud-first")
    args = parser.parse_args()

    if args.apply and not args.authorized_by.strip():
        print("Escribir en la base activa exige --authorized-by (decision §6.4).")
        return 2

    # Before the import, not after: importing core.database migrates the file.
    db_path = live_database_path()
    if db_path.is_file():
        backup_database(db_path, "before-seed-agents")

    from core.database import CMHAgent, SessionLocal

    with SessionLocal() as db:
        owner = args.owner or (db.query(CMHAgent.owner).first() or ("mijhael hartley",))[0]
        rows = plan(db, owner, args.project, args.policy)
        preserved = db.query(CMHAgent).filter(CMHAgent.name == PRESERVE).first()

    print(f"Base: {db_path}")
    print(f"Owner: {owner} · proyecto: {args.project} · politica: {args.policy}")
    print(f"Candidatos resueltos: "
          f"{[c['endpoint_id'] for c in rows[0]['candidates']] or 'NINGUNO'}")
    if not rows[0]["candidates"]:
        print("  PENDIENTE: no hay ningun endpoint gratuito registrado todavia. "
              "Los agentes quedarian sin modelo y ningun flujo podria ejecutarse.")
    print(f"\n{'accion':12} {'rol':14} {'nombre':14} {'instrucciones':>13}  workspace")
    for row in rows:
        print(f"{row['action']:12} {row['role']:14} {row['name']:14} "
              f"{len(row['instructions'].splitlines()):13}  {row['workspace']}")
    if preserved:
        print(f"\nSe conserva sin tocar: '{PRESERVE}' (id {preserved.id}, "
              f"estado {preserved.status}).")

    if not args.apply:
        print("\nSIMULACION: no se escribio nada. Para aplicar:")
        print('  python scripts/cmh_seed_agents.py --apply --authorized-by "<nombre>"')
        return 0

    with SessionLocal() as db:
        apply(db, rows, owner)
        total = db.query(CMHAgent).filter(CMHAgent.owner == owner).count()
        active = db.query(CMHAgent).filter(CMHAgent.owner == owner,
                                           CMHAgent.status == "active").count()
        still = db.query(CMHAgent).filter(CMHAgent.name == PRESERVE).first()
    print(f"\nAplicado, autorizado por: {args.authorized_by}")
    print(f"Agentes del owner: {total} · activos: {active}")
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
