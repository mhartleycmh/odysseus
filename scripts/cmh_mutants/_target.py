"""Where a mutant campaign is allowed to write, and how a verdict is reached.

A mutant rewrites versioned files and restores them afterwards. Pointed at the
live tree, a killed run leaves a mutant behind, and any edit made meanwhile is
either mutated or overwritten on restore. round2.py hard-coded the live path and
ignored CMH_MUTANT_REPO, so a campaign launched "on the export" mutated the
working tree for several minutes (2026-09-29, found because git status showed a
file nobody had edited).

An export has no ``.git``; the working tree does. That is the whole test, and it
cannot be fooled by a path that merely looks like a copy. The check lives in
``campaign`` itself and not only in ``resolve_repo``: a runner that skipped
``resolve_repo`` and handed ``campaign`` the live tree used to be obeyed.
"""

import os
import pathlib
import subprocess


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


def failed_id(line: str) -> str:
    """The test id of a ``FAILED`` line, parameters included.

    Splitting on the last ``::`` cut ``[fe80::1]`` to ``1]``: an id may contain
    ``::`` itself. The module part ends at the FIRST ``::``.
    """
    body = line[len("FAILED "):].split(" - ")[0]
    return body.split("::", 1)[1] if "::" in body else body


def assert_not_live(repo: pathlib.Path) -> None:
    """SystemExit if ``repo`` is a working tree (it has a ``.git``)."""
    if (pathlib.Path(repo) / ".git").exists() and os.environ.get("CMH_MUTANT_ALLOW_LIVE") != "1":
        raise SystemExit(
            f"Se niega a mutar {repo}: contiene .git, es el arbol vivo.\n"
            "Exporte primero:  git archive <commit> | tar -x -C <carpeta>\n"
            "y apunte la campana ahi con CMH_MUTANT_REPO=<carpeta>.")


def campaign(mutants, repo: pathlib.Path, py: pathlib.Path) -> int:
    """Run a list of ``(name, file, old, new, tests)`` mutants against ``repo``.

    The one loop that every round uses. What it guarantees, each of it measured
    by a test on a toy repo rather than by reading this function:

    * it refuses a directory with ``.git``;
    * it runs the tests UNMUTATED first and stops if they are not green: with a
      red test already in the tree every mutant "falls", and a mutant that
      changes nothing was counted as caught;
    * an obsolete pattern is NO APLICABLE, a mutant that breaks collection or
      changes nothing is INVALIDO, and none of them leaves the denominator;
    * files are read and written as bytes, so a file that used CRLF comes back
      CRLF (write_text turned it into the platform default), and the restore is
      compared to the original;
    * the exit status is 0 only when every mutant was caught AND the restored tree
      is green.
    """
    assert_not_live(repo)

    def run(tests):
        return subprocess.run([str(py), "-m", "pytest", *tests, "-p", "no:cacheprovider",
                               "-q", "--no-header"], cwd=str(repo),
                              capture_output=True, text=True)

    every = sorted({t for *_, tests in mutants for t in tests})
    print(f"Repositorio bajo mutacion: {repo}")
    baseline = run(every)
    if baseline.returncode != 0:
        print("LINEA BASE ROJA: las pruebas fallan SIN mutar nada; ningun veredicto valdria.")
        print("\n".join(baseline.stdout.splitlines()[-12:]))
        return 4

    caught = survived = skipped = invalid = 0
    for name, relative, old, new, tests in mutants:
        path = pathlib.Path(repo) / relative
        raw = path.read_bytes()
        crlf = b"\r\n" in raw
        text = raw.decode("utf-8").replace("\r\n", "\n")
        if old not in text:
            print(f"{name}: NO APLICABLE (patron no encontrado)")
            skipped += 1
            continue
        mutated = text.replace(old, new, 1)
        if mutated == text:
            print(f"{name}: *** INVALIDO - el mutante no cambia nada ***")
            invalid += 1
            continue
        path.write_bytes((mutated.replace("\n", "\r\n") if crlf else mutated).encode("utf-8"))
        try:
            result = run(tests)
            failed = [failed_id(l) for l in result.stdout.splitlines() if l.startswith("FAILED")]
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
            path.write_bytes(raw)
            if path.read_bytes() != raw:
                raise RuntimeError(f"No se pudo restaurar {relative} byte a byte")

    total = caught + survived + skipped + invalid
    print(f"\n{caught} CAUGHT - {survived} SURVIVED - {invalid} INVALIDOS - {skipped} NO APLICABLE "
          f"(de {total}; un patron obsoleto o un mutante roto NO salen del denominador)")
    final = run(every)
    summary = [l for l in final.stdout.splitlines() if "passed" in l or "failed" in l][-1:]
    print("Arbol restaurado:", summary)
    if final.returncode != 0:
        print("El arbol restaurado NO esta verde.")
    return 0 if not (survived or skipped or invalid) and final.returncode == 0 else 1


def resolve_repo(default: pathlib.Path) -> pathlib.Path:
    """The directory a campaign may mutate, or SystemExit if it is the live tree."""
    override = os.environ.get("CMH_MUTANT_REPO")
    repo = pathlib.Path(override) if override else pathlib.Path(default)
    assert_not_live(repo)
    return repo
