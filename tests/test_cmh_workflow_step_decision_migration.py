"""The `decision` column reaches an EXISTING app.db, not just a fresh one.

Every other CMH test builds its schema with `create_all` on a new in-memory
database, so the upgrade path of a deployed file was measured by nothing: a
missing ALTER TABLE would surface only in production, as
`no such column: cmh_workflow_steps.decision` on every GET /runs/{id}.
"""
import json
import os
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The table exactly as it shipped before the column existed.
OLD_SCHEMA = """
CREATE TABLE cmh_workflow_steps (
    id VARCHAR NOT NULL PRIMARY KEY,
    run_id VARCHAR NOT NULL,
    step_key VARCHAR NOT NULL,
    agent_id VARCHAR NOT NULL,
    config TEXT NOT NULL,
    dependencies TEXT NOT NULL,
    status VARCHAR NOT NULL,
    started_at DATETIME,
    finished_at DATETIME,
    error TEXT,
    CONSTRAINT uq_cmh_workflow_step_key UNIQUE (run_id, step_key)
);
"""


def _old_database(path):
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.execute(
        "INSERT INTO cmh_workflow_steps (id, run_id, step_key, agent_id, config, dependencies, status)"
        " VALUES ('s1', 'r1', 'revisor', 'a1', '{\"model\": \"m\"}', '[]', 'completed')")
    conn.commit()
    columns = [row[1] for row in conn.execute("PRAGMA table_info(cmh_workflow_steps)")]
    conn.close()
    assert "decision" not in columns, "the fixture must start WITHOUT the column"


def _run_init_db(db_path, tmp_path):
    env = os.environ.copy()
    env.update({
        "AUTH_ENABLED": "true", "CHROMADB_CONNECT_TIMEOUT": "0.01", "CHROMADB_HOST": "127.0.0.1",
        "CHROMADB_PORT": "9", "DATABASE_URL": f"sqlite:///{db_path}", "ODYSSEUS_DATA_DIR": str(tmp_path),
        "ODYSSEUS_DISABLE_MCP": "1", "PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1",
    })
    probe = textwrap.dedent("""
        from core.database import init_db
        init_db()
        init_db()          # idempotent: a second boot must not fail
        print("INIT_OK")
    """)
    result = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=300)
    assert "INIT_OK" in result.stdout, result.stderr[-2000:]


def test_an_existing_database_gains_the_column_without_losing_rows(tmp_path):
    db_path = tmp_path / "app.db"
    _old_database(db_path)
    _run_init_db(db_path, tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(cmh_workflow_steps)")]
        rows = conn.execute("SELECT id, status, decision FROM cmh_workflow_steps").fetchall()
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()
    assert "decision" in columns, columns
    # The pre-existing row survives untouched, with no decision recorded.
    assert rows == [("s1", "completed", None)], rows


def test_the_migrated_column_round_trips_a_decision(tmp_path):
    """A migrated database behaves like a freshly created one."""
    db_path = tmp_path / "app.db"
    _old_database(db_path)
    _run_init_db(db_path, tmp_path)
    decision = {"outcome": "rejected", "justification": "Sin evidencia.", "by": "admin", "at": "2026-09-25T00:00:00"}
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("UPDATE cmh_workflow_steps SET decision = ? WHERE id = 's1'",
                     (json.dumps(decision, ensure_ascii=False),))
        conn.commit()
        stored = conn.execute("SELECT decision FROM cmh_workflow_steps WHERE id = 's1'").fetchone()[0]
    finally:
        conn.close()
    assert json.loads(stored) == decision
