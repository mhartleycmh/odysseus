#!/usr/bin/env bash
# Equivalente POSIX de start.ps1, para correrlo desde Git Bash.
# La logica vive en el .ps1: este envoltorio existe para no cambiar de shell a
# mitad de trabajo y porque en esta maquina la politica de ejecucion es Restricted,
# de modo que `powershell -File start.ps1` a secas no empieza. Aqui va con Bypass.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec powershell -NoProfile -ExecutionPolicy Bypass -File "$here/start.ps1" "$@"
