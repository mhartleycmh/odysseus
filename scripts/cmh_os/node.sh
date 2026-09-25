#!/usr/bin/env bash
# Run Node for the CMH OS checks. Uses `node` from PATH when present; otherwise
# the Node 24 embedded in VS Code (Electron with ELECTRON_RUN_AS_NODE=1), so the
# checks need no installation on this machine. Override with CMH_OS_NODE.
set -euo pipefail
if [[ -n "${CMH_OS_NODE:-}" ]]; then exec "$CMH_OS_NODE" "$@"; fi
if command -v node >/dev/null 2>&1; then exec node "$@"; fi
base="${LOCALAPPDATA:-}"
if command -v cygpath >/dev/null 2>&1 && [[ -n "$base" ]]; then base="$(cygpath -u "$base")"; fi
code="$base/Programs/Microsoft VS Code/Code.exe"
if [[ ! -f "$code" ]]; then
  echo "node.sh: no node on PATH and no VS Code at '$code'; set CMH_OS_NODE" >&2
  exit 127
fi
ELECTRON_RUN_AS_NODE=1 exec "$code" "$@"
