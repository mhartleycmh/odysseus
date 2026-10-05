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
RETURNED = f"{REPORT}::test_a_returned_verdict_in_any_form_keeps_an_approval_from_closing_the_phase"

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
    # --- P1-2: any line pairing "veredicto" with DEVUELTO keeps APROBADO from closing ----------
    ("D01 un DEVUELTO fuera de la primera linea vuelve a ignorarse", REPORT_SCRIPT,
     '    if found[0] == "APROBADO":\n',
     '    if False:\n',
     [RETURNED]),
    ("D02 solo cuenta 'veredicto:' seguido de DEVUELTO (se pierden 'final', la tabla y el guion)",
     REPORT_SCRIPT,
     'r"\\bveredictos?\\b.*\\bdevuelto\\b|\\bdevuelto\\b.*\\bveredictos?\\b"',
     'r"\\bveredictos?\\b\\s*:\\s*devuelto\\b"',
     [RETURNED]),
    ("D03 la busqueda distingue mayusculas (se pierden 'Veredicto' y la prosa en minusculas)",
     REPORT_SCRIPT,
     'r"\\bveredictos?\\b.*\\bdevuelto\\b|\\bdevuelto\\b.*\\bveredictos?\\b", re.IGNORECASE)',
     'r"\\bVEREDICTOS?\\b.*\\bDEVUELTO\\b|\\bDEVUELTO\\b.*\\bVEREDICTOS?\\b")',
     [RETURNED]),
    ("D04 la busqueda se ancla al inicio de la linea (se pierden vineta, lista, tabla y cita)",
     REPORT_SCRIPT,
     '            if _RETURNED.search(re.sub(r"[*_`~]", "", line)):',
     '            if _RETURNED.match(re.sub(r"[*_`~]", "", line)):',
     [RETURNED]),
    ("D05 la busqueda deja de quitar las marcas markdown (se pierde _Veredicto_)", REPORT_SCRIPT,
     '            if _RETURNED.search(re.sub(r"[*_`~]", "", line)):',
     '            if _RETURNED.search(line):',
     [RETURNED]),
    ("D06 solo cuenta 'veredicto' antes de DEVUELTO (se pierde el orden inverso)", REPORT_SCRIPT,
     '|\\bdevuelto\\b.*\\bveredictos?\\b"',
     '"',
     [RETURNED]),
    ("D07 cualquier DEVUELTO, sin la palabra veredicto, impide el APROBADO", REPORT_SCRIPT,
     'r"\\bveredictos?\\b.*\\bdevuelto\\b|\\bdevuelto\\b.*\\bveredictos?\\b"',
     'r"\\bdevuelto\\b"',
     [f"{REPORT}::test_an_approval_that_never_pairs_the_word_with_devuelto_still_closes_the_phase"]),
]


if __name__ == "__main__":
    sys.exit(campaign(MUTANTS, REPO, PY))
