#!/usr/bin/env bash
# One command for every front-end check of the Agentic OS page (/cmh/os).
#   bash scripts/cmh_os/check.sh            typecheck, lint, build, unit, e2e
#   bash scripts/cmh_os/check.sh --no-e2e   skip the browser tests
#   bash scripts/cmh_os/check.sh --screens  also save screenshots to data/cmh-os-screens/
# Stops at the first failing stage and exits non-zero.
set -euo pipefail
cd "$(dirname "$0")/../.."
NODE=(bash scripts/cmh_os/node.sh)
run_e2e=1
screens=()
for arg in "$@"; do
  case "$arg" in
    --no-e2e) run_e2e=0 ;;
    --screens) screens=(--screens) ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done
stage() { printf '\n== %s ==\n' "$1"; }
stage "Tipos (TypeScript strict sobre JSDoc)"; "${NODE[@]}" scripts/cmh_os/typecheck.mjs
stage "Lint (reglas propias)";                 "${NODE[@]}" scripts/cmh_os/lint.mjs
stage "Build (grafo de módulos y presupuesto)"; "${NODE[@]}" scripts/cmh_os/build.mjs
stage "Unitarias (node --test)";               "${NODE[@]}" --test tests/cmh_os/unit/*.test.mjs
if [[ $run_e2e == 1 ]]; then
  stage "End-to-end, componentes, a11y y responsive (Edge sin ventana)"
  "${NODE[@]}" tests/cmh_os/e2e/run.mjs "${screens[@]}"
fi
printf '\ncheck: todas las etapas aprobadas\n'
