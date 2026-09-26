#!/usr/bin/env bash
# Real mode end to end: a browser with a real session against a REAL Odysseus.
#
# The e2e suite in tests/cmh_os/e2e drives the UI against a fake API. This one
# closes the gap that leaves: it stands up a THROWAWAY Odysseus with its own
# database and data directory, creates a disposable account through the
# product's own first-run setup, seeds synthetic CMH data, and drives Edge
# against the real FastAPI handlers.
#
# It never touches an existing instance: the port, the database, the data
# directory and the account are all created here and deleted on exit. Every
# name and figure in the seed is invented.
#
#   bash scripts/cmh_os/realmode/run.sh [puerto]
set -euo pipefail

cd "$(dirname "$0")/../../.."
REPO="$PWD"
PORT="${1:-7101}"
PY="${CMH_OS_PYTHON:-../../.venv/Scripts/python.exe}"
WORK_POSIX="$(mktemp -d -t cmh-os-realmode-XXXXXX)"
# SQLite on Windows cannot open a POSIX-style path, and the runner is Git Bash:
# keep a native path for the env vars and the POSIX one for rm.
if command -v cygpath >/dev/null 2>&1; then WORK="$(cygpath -m "$WORK_POSIX")"; else WORK="$WORK_POSIX"; fi
USERNAME="prueba"
# Random, never stored: the instance dies with this script.
PASSWORD="$("$PY" -c "import secrets; print(secrets.token_urlsafe(18))")"
SERVER_PID=""

cleanup() {
  if [ -n "$SERVER_PID" ]; then kill "$SERVER_PID" 2>/dev/null || true; fi
  sleep 1
  rm -rf "$WORK_POSIX" 2>/dev/null || true
}
trap cleanup EXIT

export PYTHONPATH="$REPO"
export AUTH_ENABLED=true CMH_OS_UI_ENABLED=true DEBUG=false
export CHROMADB_CONNECT_TIMEOUT=0.01 CHROMADB_HOST=127.0.0.1 CHROMADB_PORT=9
export ODYSSEUS_DISABLE_MCP=1 PYTHON_DOTENV_DISABLED=1
export DATABASE_URL="sqlite:///$WORK/app.db"
export ODYSSEUS_DATA_DIR="$WORK"
export SEED_WORKSPACE="$WORK/workspace"

mkdir -p "$WORK/workspace/input"
echo "dato sintetico de prueba" > "$WORK/workspace/input/sintetico.txt"

echo "sembrando datos sinteticos"
"$PY" scripts/cmh_os/realmode/seed.py "$USERNAME"

echo "arrancando Odysseus desechable en el puerto $PORT"
"$PY" -m uvicorn app:app --host 127.0.0.1 --port "$PORT" > "$WORK/server.log" 2>&1 &
SERVER_PID=$!
for _ in $(seq 1 60); do
  if curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/api/health"; then break; fi
  sleep 2
done
curl -s -o /dev/null --max-time 5 "http://127.0.0.1:$PORT/api/health" || { echo "el servidor no arranco"; tail -20 "$WORK/server.log"; exit 1; }

if grep -q Traceback "$WORK/server.log"; then echo "hay tracebacks en el arranque"; exit 1; fi

echo "creando la cuenta desechable"
curl -s -X POST "http://127.0.0.1:$PORT/api/auth/setup" -H "Content-Type: application/json" \
  -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}" --max-time 20 | grep -q '"ok":true' \
  || { echo "no se pudo crear la cuenta"; exit 1; }

echo
bash scripts/cmh_os/node.sh scripts/cmh_os/realmode/checks.mjs "http://127.0.0.1:$PORT" "$USERNAME" "$PASSWORD"
STATUS=$?

echo
echo "estado final en la base desechable:"
"$PY" - "$WORK/app.db" <<'PYEOF'
import json, sqlite3, sys
c = sqlite3.connect(sys.argv[1])
print("  ejecucion:", c.execute("SELECT status FROM cmh_workflow_runs").fetchone()[0])
for key, status, decision in c.execute("SELECT step_key, status, decision FROM cmh_workflow_steps ORDER BY step_key"):
    print(f"  paso {key:14} {status:12}", json.loads(decision) if decision else None)
print("  eventos:", [r[0] for r in c.execute("SELECT kind FROM cmh_workflow_events ORDER BY seq")])
print("  artefactos:", c.execute("SELECT count(*) FROM cmh_workflow_artifacts").fetchone()[0])
c.close()
PYEOF

exit $STATUS
