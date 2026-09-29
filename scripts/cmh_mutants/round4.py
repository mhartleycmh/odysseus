"""Mutants for the fixes of the 2026-09-29 audit (step 3.3b and what surrounds it).

Each capacity adds its mutants here, in the same commit as its fix, and names the
test module that must fall. A mutant that does not fall is a test that cannot
fail: that is the only reason this file exists.

Run it against an EXPORT of a commit, never the live tree. The runner refuses a
directory that contains .git (see _target.py).

    git archive <commit> | tar -x -C /tmp/export
    CMH_MUTANT_REPO=/tmp/export python scripts/cmh_mutants/round4.py

A mutant whose pattern stops matching is reported as NO APLICABLE and counted
separately, so an obsolete pattern cannot quietly leave the denominator.
"""

import pathlib
import subprocess
import sys

from _target import resolve_repo

REPO = resolve_repo(pathlib.Path(__file__).resolve().parents[2])
PY = pathlib.Path(sys.executable)
if not PY.exists() or "python" not in PY.name.lower():
    PY = REPO.parent.parent / ".venv" / "Scripts" / "python.exe"

TARGET_TESTS = ["tests/test_cmh_mutant_target.py"]

TARGET = "scripts/cmh_mutants/_target.py"
ROUND2 = "scripts/cmh_mutants/round2.py"

#: (name, file, text to replace, replacement, test modules that must fall)
MUTANTS = [
    # --- the campaign runners refuse the live tree -----------------------------
    ("T01 resolve_repo deja de mirar .git", TARGET,
     '    if (repo / ".git").exists() and os.environ.get("CMH_MUTANT_ALLOW_LIVE") != "1":',
     '    if False and (repo / ".git").exists():',
     TARGET_TESTS),
    ("T02 resolve_repo ignora CMH_MUTANT_REPO", TARGET,
     '    override = os.environ.get("CMH_MUTANT_REPO")',
     '    override = None',
     TARGET_TESTS),
    ("T03 round2 vuelve a fijar su propia ruta sin pasar por resolve_repo", ROUND2,
     "REPO = resolve_repo(pathlib.Path(__file__).resolve().parents[2])",
     "REPO = pathlib.Path(__file__).resolve().parents[2]",
     TARGET_TESTS),
]


def run(tests):
    return subprocess.run([str(PY), "-m", "pytest", *tests, "-p", "no:cacheprovider",
                           "-q", "--no-header"], cwd=str(REPO),
                          capture_output=True, text=True)


def main() -> int:
    print(f"Repositorio bajo mutacion: {REPO}")
    caught = survived = skipped = 0
    for name, relative, old, new, tests in MUTANTS:
        path = REPO / relative
        original = path.read_text(encoding="utf-8")
        if old not in original:
            print(f"{name}: NO APLICABLE (patron no encontrado)")
            skipped += 1
            continue
        path.write_text(original.replace(old, new, 1), encoding="utf-8")
        try:
            result = run(tests)
            failed = [l.split("::")[-1] for l in result.stdout.splitlines()
                      if l.startswith("FAILED")]
            if result.returncode:
                caught += 1
                print(f"{name}: CAUGHT - cae: {failed[0] if failed else '?'}")
            else:
                survived += 1
                print(f"{name}: *** SURVIVED ***")
        finally:
            path.write_text(original, encoding="utf-8")

    total = caught + survived + skipped
    print(f"\n{caught} CAUGHT - {survived} SURVIVED - {skipped} NO APLICABLE "
          f"(de {total}; un patron obsoleto NO sale del denominador)")
    every = sorted({t for *_, tests in MUTANTS for t in tests})
    final = run(every)
    print("Arbol restaurado:", [l for l in final.stdout.splitlines()
                                if "passed" in l or "failed" in l][-1:])
    return 1 if survived or skipped else 0


if __name__ == "__main__":
    sys.exit(main())
