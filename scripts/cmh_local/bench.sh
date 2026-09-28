#!/usr/bin/env bash
# Equivalente POSIX de bench.ps1, para correrlo desde Git Bash.
# La medicion real vive en el .ps1: este envoltorio existe para no cambiar de
# shell a mitad de trabajo, no para duplicar la logica.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec powershell -NoProfile -ExecutionPolicy Bypass -File "$here/bench.ps1" "$@"
