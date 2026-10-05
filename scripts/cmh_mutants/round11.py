"""Mutants for the corrections of the independent review of r11 (2026-10-05, ADR-040).

Each mutant names the test module, or the test, that must fall. A mutant that does not
fall is a test that cannot fail: that is the only reason this file exists.

Run it against an EXPORT of a commit, never the live tree. The runner refuses a
directory that contains .git (see _target.py).

    git archive <commit> | tar -x -C /tmp/export
    CMH_MUTANT_REPO=/tmp/export python scripts/cmh_mutants/round11.py
"""

import pathlib
import sys

from _target import resolve_repo
from _target import campaign

REPO = resolve_repo(pathlib.Path(__file__).resolve().parents[2])
PY = pathlib.Path(sys.executable)
if not PY.exists() or "python" not in PY.name.lower():
    PY = REPO.parent.parent / ".venv" / "Scripts" / "python.exe"

REPORT = "tests/test_cmh_run_report.py"
READABLE = f"{REPORT}::test_a_verdict_nobody_can_read_is_not_an_approval"
QUOTED = f"{REPORT}::test_an_approval_the_reviewer_quotes_or_copies_does_not_close_the_phase"

REPORT_SCRIPT = "scripts/cmh_ops/run_report.py"

#: (name, file, text to replace, replacement, test modules or node ids that must fall)
MUTANTS = [
    # --- P1-1: the reviewer's verdict is the first non-empty line, never a quote ------------
    ("C01 una linea citada (>) vuelve a abrir el veredicto", REPORT_SCRIPT,
     '        re.sub(r"^[\\s#]+", "", re.sub(r"[*_`]", "", lines[first])).strip())',
     '        re.sub(r"^[\\s#>]+", "", re.sub(r"[*_`]", "", lines[first])).strip())',
     [READABLE, QUOTED]),
    ("C02 el veredicto vuelve a ser la primera linea que menciona VEREDICTO, este donde este",
     REPORT_SCRIPT,
     "    first = next((number for number, line in enumerate(lines) if line.strip()), None)",
     '    first = next((number for number, line in enumerate(lines) if "VEREDICTO" in line.upper()), None)',
     [READABLE, QUOTED]),
    ("C03 la primera linea vacia cuenta como la primera", REPORT_SCRIPT,
     "    first = next((number for number, line in enumerate(lines) if line.strip()), None)",
     "    first = next((number for number, line in enumerate(lines) if True), None)",
     [READABLE]),
    ("C04 la valla de un bloque de codigo se salta y lo copiado dentro abre el veredicto",
     REPORT_SCRIPT,
     "    first = next((number for number, line in enumerate(lines) if line.strip()), None)",
     "    first = next((number for number, line in enumerate(lines) if line.strip(\" `\")), None)",
     [QUOTED]),
    ("C05 una linea de veredicto posterior en minusculas vuelve a contradecir a la primera",
     REPORT_SCRIPT,
     "            found.append(match.group(1).upper())",
     "            found.append(match.group(1))",
     [READABLE]),
]


if __name__ == "__main__":
    sys.exit(campaign(MUTANTS, REPO, PY))
