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

import functools
import os
import pathlib
import re
import subprocess
import tempfile

#: A campaign runs for tens of minutes with its output redirected to a file: without a
#: flush nothing shows until the end, and a killed run loses every line.
say = functools.partial(print, flush=True)


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
    if failed:
        return "CAUGHT"
    # pytest did not end by itself: a status pytest never returns (a signal, Windows'
    # STATUS_CONTROL_C_EXIT), a Ctrl+C it caught, or no closing summary line. A pytest killed
    # with taskkill /F or Popen.terminate() exits 1, a status pytest does return, with the dots
    # it had already flushed ("..."): kill_probe.py of the r11 review, P2, measured both. A run
    # that ended by itself always prints the summary, a collection error too ("1 error in
    # 0.21s"); without one, whatever stopped it is unknown. The round9 campaign of the r10
    # verification ran from 14:15 to 20:58, printed "Z16 ... INVALIDO - rompe la coleccion"
    # and died during Z17, leaving Z17 applied in its copy; Z16 and Z17 alone are CAUGHT.
    # Nothing about such a mutant is known, and the run that called it broken carried on as
    # if something were.
    if (returncode not in PYTEST_EXIT_CODES or "KeyboardInterrupt" in stdout
            or not any(_PYTEST_SUMMARY.match(line) for line in stdout.splitlines())):
        return "INTERRUMPIDO"
    return "INVALIDO"


#: pytest's own exit statuses: passed, failed, interrupted or collection error, internal
#: error, usage error, nothing collected.
PYTEST_EXIT_CODES = range(6)

#: The line pytest closes a run with, measured with the campaign's own flags (-q --no-header):
#: "1 failed in 0.08s", "1 error in 0.21s", "no tests ran in 0.00s", "1 passed, 1 warning in
#: 0.01s", "170 passed, 1 warning in 324.80s (0:05:24)".
_PYTEST_SUMMARY = re.compile(r"^(?:no tests ran|\d+ [a-z]+(?:, \d+ [a-z]+)*) in \d+(?:\.\d+)?s\b")


def _tail(result, lines: int = 6) -> None:
    """The last lines pytest printed, so a log says WHY a mutant has no verdict."""
    for line in (result.stdout or "").splitlines()[-lines:]:
        say(f"      | {line}")


def failed_id(line: str) -> str:
    """The test id of a ``FAILED`` line, parameters included.

    Splitting on the last ``::`` cut ``[fe80::1]`` to ``1]``: an id may contain
    ``::`` itself. The module part ends at the FIRST ``::``. And an id may contain
    `` - `` inside its brackets (``[carpeta OneDrive-guardado en OneDrive - CMH]``), so
    when the id opens a bracket the message starts after the bracket that closes it.
    """
    rest = line[len("FAILED "):]
    head = rest.split(" - ")[0]
    if "[" in head:
        closed = re.match(r"(.*?\])(?: - |$)", rest)
        body = closed.group(1) if closed else head
    else:
        body = head
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
    * a pytest that did not end by itself is INTERRUMPIDO, not INVALIDO: the file is
      restored and the campaign stops with status 3, the remaining mutants unjudged;
    * files are read and written as bytes, so a file that used CRLF comes back
      CRLF (write_text turned it into the platform default), and the restore is
      compared to the original;
    * the exit status is 0 only when every mutant was caught AND the restored tree
      is green.
    """
    assert_not_live(repo)
    root = pathlib.Path(repo).resolve()
    for _, relative, *_ in mutants:
        if not (root / relative).resolve().is_relative_to(root):
            # The guard above looks only at ``repo``. A relative path with ``..`` or an
            # absolute one was opened, mutated and restored OUTSIDE the export.
            raise SystemExit(f"El mutante apunta fuera del repositorio bajo mutacion: {relative}")

    def run(tests):
        # -B stops writes but still reads timestamp-based bytecode. A fresh
        # prefix also excludes stale caches after same-size edits in one second.
        with tempfile.TemporaryDirectory(prefix="cmh-mutant-pyc-") as pycache:
            return subprocess.run([str(py), "-B", "-X", f"pycache_prefix={pycache}",
                                   "-m", "pytest", *tests, "-p", "no:cacheprovider",
                                   "-q", "--no-header"], cwd=str(repo),
                                  capture_output=True, text=True)

    every = sorted({t for *_, tests in mutants for t in tests})
    say(f"Repositorio bajo mutacion: {repo}")
    baseline = run(every)
    if baseline.returncode != 0:
        say("LINEA BASE ROJA: las pruebas fallan SIN mutar nada; ningun veredicto valdria.")
        say("\n".join(baseline.stdout.splitlines()[-12:]))
        return 4

    caught = survived = skipped = invalid = 0
    for name, relative, old, new, tests in mutants:
        path = pathlib.Path(repo) / relative
        raw = path.read_bytes()
        crlf = b"\r\n" in raw
        text = raw.decode("utf-8").replace("\r\n", "\n")
        if old not in text:
            say(f"{name}: NO APLICABLE (patron no encontrado)")
            skipped += 1
            continue
        mutated = text.replace(old, new, 1)
        if mutated == text:
            say(f"{name}: *** INVALIDO - el mutante no cambia nada ***")
            invalid += 1
            continue
        # Killed from outside (a timeout, the task manager) the ``finally`` below does not run
        # and the file stays mutated: say which one is, before it is.
        say(f"   (mutando {relative} para {name})")
        path.write_bytes((mutated.replace("\n", "\r\n") if crlf else mutated).encode("utf-8"))
        try:
            result = run(tests)
            failed = [failed_id(l) for l in result.stdout.splitlines() if l.startswith("FAILED")]
            outcome = verdict(result.returncode, result.stdout)
            if outcome == "CAUGHT":
                caught += 1
                say(f"{name}: CAUGHT - cae: {failed[0]}")
            elif outcome == "INVALIDO":
                invalid += 1
                say(f"{name}: *** INVALIDO - rompe la coleccion, ninguna prueba falla "
                    f"(pytest salio con {result.returncode}) ***")
                _tail(result)
            elif outcome == "INTERRUMPIDO":
                say(f"{name}: *** INTERRUMPIDO - pytest no termino por si mismo "
                    f"(salio con {result.returncode}) ***")
                _tail(result)
            else:
                survived += 1
                say(f"{name}: *** SURVIVED ***")
        finally:
            path.write_bytes(raw)
            if path.read_bytes() != raw:
                raise RuntimeError(f"No se pudo restaurar {relative} byte a byte")
        if outcome == "INTERRUMPIDO":
            # Whatever stopped pytest is still around: every verdict after this one would be
            # as unknown. The file is already restored; stop here and say so.
            # Commas, not the " - " of the closing summary: round4's T15 mutates the FIRST
            # occurrence of that summary's text, and this line used to be it.
            say(f"\nCAMPANA INTERRUMPIDA en {name}: hasta aqui {caught} CAUGHT, {survived} SURVIVED, "
                f"{invalid} INVALIDOS, {skipped} NO APLICABLE; los "
                f"{len(mutants) - caught - survived - invalid - skipped} restantes no tienen "
                "veredicto. Repita la campana.")
            return 3

    total = caught + survived + skipped + invalid
    say(f"\n{caught} CAUGHT - {survived} SURVIVED - {invalid} INVALIDOS - {skipped} NO APLICABLE "
        f"(de {total}; un patron obsoleto o un mutante roto NO salen del denominador)")
    final = run(every)
    summary = [l for l in final.stdout.splitlines() if "passed" in l or "failed" in l][-1:]
    # The pytest line counts the tests the mutants DESIGNATE (the union in ``every``), not the
    # whole module: round7 restores on 9 of its module's 45 tests.
    say("Arbol restaurado (las pruebas que designan los mutantes, no el modulo entero):", summary)
    if final.returncode != 0:
        say("El arbol restaurado NO esta verde.")
    return 0 if not (survived or skipped or invalid) and final.returncode == 0 else 1


def resolve_repo(default: pathlib.Path) -> pathlib.Path:
    """The directory a campaign may mutate, or SystemExit if it is the live tree."""
    override = os.environ.get("CMH_MUTANT_REPO")
    repo = pathlib.Path(override) if override else pathlib.Path(default)
    assert_not_live(repo)
    return repo
