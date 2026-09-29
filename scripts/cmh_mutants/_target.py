"""Where a mutant campaign is allowed to write: an export, never the live tree.

A mutant rewrites versioned files and restores them afterwards. Pointed at the
live tree, a killed run leaves a mutant behind, and any edit made meanwhile is
either mutated or overwritten on restore. round2.py hard-coded the live path and
ignored CMH_MUTANT_REPO, so a campaign launched "on the export" mutated the
working tree for several minutes (2026-09-29, found because git status showed a
file nobody had edited).

An export has no ``.git``; the working tree does. That is the whole test, and it
cannot be fooled by a path that merely looks like a copy.
"""

import os
import pathlib


def verdict(returncode: int, stdout: str) -> str:
    """CAUGHT only when a test actually failed.

    pytest exits non-zero for two very different reasons: a test failed (the
    mutant was caught) or the module could not even be collected (the mutant is
    not valid Python, or breaks an import). The runners counted both as caught,
    so a mutant that is a SyntaxError "fell" to every test in the suite at
    once. That is what round3's R17 did: its patch left ``_skip = `` with no
    value, it never compiled, and it stood in the "13 of 13 caught" of commit
    4fca1184 while no test had ever been shown to notice the deduplication it
    was meant to remove.
    """
    if returncode == 0:
        return "SURVIVED"
    failed = any(line.startswith("FAILED") for line in stdout.splitlines())
    return "CAUGHT" if failed else "INVALIDO"


def campaign(mutants, repo: pathlib.Path, py: pathlib.Path) -> int:
    """Run a list of ``(name, file, old, new, tests)`` mutants against ``repo``.

    One place for the loop that rounds 2-4 each carry a copy of. The file is
    restored in a ``finally``, an obsolete pattern is NO APLICABLE and a broken
    mutant is INVALIDO: neither leaves the denominator, and either makes the exit
    status non-zero.
    """
    import subprocess

    def run(tests):
        return subprocess.run([str(py), "-m", "pytest", *tests, "-p", "no:cacheprovider",
                               "-q", "--no-header"], cwd=str(repo),
                              capture_output=True, text=True)

    print(f"Repositorio bajo mutacion: {repo}")
    caught = survived = skipped = invalid = 0
    for name, relative, old, new, tests in mutants:
        path = repo / relative
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
            outcome = verdict(result.returncode, result.stdout)
            if outcome == "CAUGHT":
                caught += 1
                print(f"{name}: CAUGHT - cae: {failed[0]}")
            elif outcome == "INVALIDO":
                invalid += 1
                print(f"{name}: *** INVALIDO - rompe la coleccion, ninguna prueba falla ***")
            else:
                survived += 1
                print(f"{name}: *** SURVIVED ***")
        finally:
            path.write_text(original, encoding="utf-8")

    total = caught + survived + skipped + invalid
    print(f"\n{caught} CAUGHT - {survived} SURVIVED - {invalid} INVALIDOS - {skipped} NO APLICABLE "
          f"(de {total}; un patron obsoleto o un mutante roto NO salen del denominador)")
    every = sorted({t for *_, tests in mutants for t in tests})
    final = run(every)
    print("Arbol restaurado:", [l for l in final.stdout.splitlines()
                                if "passed" in l or "failed" in l][-1:])
    return 1 if survived or skipped or invalid else 0


def resolve_repo(default: pathlib.Path) -> pathlib.Path:
    """The directory a campaign may mutate, or SystemExit if it is the live tree."""
    override = os.environ.get("CMH_MUTANT_REPO")
    repo = pathlib.Path(override) if override else pathlib.Path(default)
    if (repo / ".git").exists() and os.environ.get("CMH_MUTANT_ALLOW_LIVE") != "1":
        raise SystemExit(
            f"Se niega a mutar {repo}: contiene .git, es el arbol vivo.\n"
            "Exporte primero:  git archive <commit> | tar -x -C <carpeta>\n"
            "y apunte la campana ahi con CMH_MUTANT_REPO=<carpeta>.")
    return repo
