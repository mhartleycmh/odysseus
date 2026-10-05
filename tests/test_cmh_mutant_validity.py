"""Every mutant of every campaign must be applicable and valid Python, and the
runners must only call a mutant caught when a test actually failed.

Round3's R17 appended ``_skip = `` with no value: a SyntaxError. The module
never collected, pytest exited non-zero, and the runner counted that as "caught"
for as long as the campaign existed - it stood in the "13 of 13 mutants caught"
of commit 4fca1184 while no test had ever been shown to notice the deduplication
it claimed to remove.

Two guards. The runners now separate a broken mutant (INVALIDO) from a caught
one. And this module applies every mutant IN MEMORY to the current source and
compiles the result, so a stale pattern or a broken patch fails in seconds
instead of after a campaign of minutes. Nothing here writes a file.
"""

import ast
import importlib.util
import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
MUTANTS_DIR = REPO / "scripts" / "cmh_mutants"
RUNNERS = sorted(path.name for path in MUTANTS_DIR.glob("round*.py"))


def _verdict():
    spec = importlib.util.spec_from_file_location("cmh_mutant_target", MUTANTS_DIR / "_target.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verdict


def _mutants(runner: str):
    """(name, file, old, new) of every mutant, read from the runner's source.

    Parsed, not imported: importing a runner resolves REPO and PY, and this only needs the
    mutant lists. (round2 used to run its whole campaign at import time; it no longer does.)
    """
    tree = ast.parse((MUTANTS_DIR / runner).read_text(encoding="utf-8"))
    constants = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            constants[node.targets[0].id] = node.value.value

    def text(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return constants[node.id]
        raise AssertionError(f"{runner}: unsupported mutant element {ast.dump(node)[:60]}")

    for node in tree.body:
        if (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "MUTANTS"):
            return [tuple(text(element) for element in entry.elts[:4]) for entry in node.value.elts]
    raise AssertionError(f"{runner}: no MUTANTS list")


def test_the_runners_are_the_ones_this_module_covers():
    assert {"round2.py", "round3.py", "round4.py"} <= set(RUNNERS)


#: Returned when a mutant could not be checked because the tool that checks its file type is
#: missing. It is neither "valid" (None) nor "broken" (a message): the test skips instead of
#: passing, because a mutant nobody compiled is not a mutant that compiles.
UNCHECKED = object()


def _syntax_problem(relative: str, mutated: str, workdir: pathlib.Path):
    """Why the mutated source is not valid, None if it is, or UNCHECKED. Python is
    compiled; a PowerShell script goes through PowerShell's own parser and a shell
    script through ``bash -n``. With no such tool the answer is UNCHECKED."""
    if relative.endswith(".py"):
        try:
            compile(mutated, relative, "exec")
        except SyntaxError as exc:
            return f"no compila ({exc.msg}, linea {exc.lineno})"
        return None
    if relative.endswith(".ps1"):
        powershell = shutil.which("powershell.exe")
        if not powershell:
            return UNCHECKED
        target = workdir / "mutant.ps1"
        target.write_text(mutated, encoding="ascii" if mutated.isascii() else "utf-8-sig")
        script = ("$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile("
                  f"'{target}', [ref]$null, [ref]$e); "
                  "if ($e.Count) { $e | ForEach-Object { $_.Message + ' (linea ' + "
                  "$_.Extent.StartLineNumber + ')' }; exit 1 }")
        result = subprocess.run([powershell, "-NoProfile", "-Command", script],
                                capture_output=True, text=True)
        return None if result.returncode == 0 else "no compila: " + result.stdout.strip()[:200]
    if relative.endswith(".sh"):
        bash = shutil.which("bash")
        if not bash:
            return UNCHECKED
        target = workdir / "mutant.sh"
        target.write_text(mutated, encoding="utf-8", newline="\n")
        result = subprocess.run([bash, "-n", str(target)], capture_output=True, text=True)
        return None if result.returncode == 0 else "no compila: " + result.stderr.strip()[:200]
    return f"tipo de archivo sin comprobacion de sintaxis: {relative}"


@pytest.mark.parametrize("runner", RUNNERS)
def test_every_mutant_is_applicable_and_compiles(runner, tmp_path):
    broken, unchecked = [], []
    mutants = _mutants(runner)
    assert mutants, runner
    for name, relative, old, new in mutants:
        source = (REPO / relative).read_text(encoding="utf-8")
        if old not in source:
            broken.append(f"{name}: el patron ya no existe en {relative}")
            continue
        if source.count(old) > 1:
            # The campaign mutates the FIRST occurrence. r11 added a line to _target.py that
            # repeated the text of T15 (round4) above the summary it targets: T15 went on
            # compiling, mutated the new line and survived.
            broken.append(f"{name}: el patron aparece {source.count(old)} veces en {relative}; "
                          "el mutante cae solo en la primera")
            continue
        mutated = source.replace(old, new, 1)
        if mutated == source:
            broken.append(f"{name}: el mutante no cambia nada")
            continue
        problem = _syntax_problem(relative, mutated, tmp_path)
        if problem is UNCHECKED:
            unchecked.append(name)
        elif problem:
            broken.append(f"{name}: {problem}")
    assert not broken, "\n".join(broken)
    if unchecked:
        pytest.skip(f"{len(unchecked)} mutante(s) sin comprobar (falta PowerShell o bash): "
                    + ", ".join(unchecked[:5]))


def test_a_mutant_that_could_not_be_checked_is_neither_valid_nor_broken(tmp_path, monkeypatch):
    """With no PowerShell the check used to return None, which the caller reads as 'no
    problem': the mutants were declared valid without anyone having parsed them."""
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert _syntax_problem("scripts/x.ps1", "Write-Host 1", tmp_path) is UNCHECKED
    assert _syntax_problem("scripts/x.sh", "echo 1", tmp_path) is UNCHECKED
    assert _syntax_problem("scripts/x.py", "x = 1", tmp_path) is None       # Python needs no tool
    assert _syntax_problem("scripts/x.py", "x = ", tmp_path).startswith("no compila")


def test_a_shell_mutant_goes_through_bash_and_a_broken_one_is_reported(tmp_path):
    if not shutil.which("bash"):
        pytest.skip("no bash on this machine")
    assert _syntax_problem("scripts/x.sh", "echo 1\n", tmp_path) is None
    assert "no compila" in _syntax_problem("scripts/x.sh", "if then fi\n", tmp_path)


def test_a_mutant_that_does_not_compile_is_reported_as_broken_and_not_as_caught():
    verdict = _verdict()
    collection_error = "ERROR tests/x.py - SyntaxError: invalid syntax\n1 error in 0.10s"
    assert verdict(2, collection_error) == "INVALIDO"
    assert verdict(1, "FAILED tests/x.py::test_it - assert 1 == 2\n1 failed") == "CAUGHT"
    assert verdict(0, "24 passed") == "SURVIVED"


def test_the_verdict_needs_a_failing_test_not_just_a_non_zero_exit():
    verdict = _verdict()
    for code in (1, 2, 3, 4, 5):
        # r12: with pytest's closing line; without it the run did not end by itself (r11, P2).
        assert verdict(code, "no tests ran in 0.00s") == "INVALIDO", code


@pytest.mark.parametrize("code, stdout", [
    (2, "..\n!!!!!!!!!!!!!!!!!!!!!!!!!!!! KeyboardInterrupt !!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
        "2 passed in 3.10s"),
    (3221225786, "..."),     # STATUS_CONTROL_C_EXIT: a console closed under the campaign
    (-9, "..."),             # a POSIX signal
    (-9, "..\n2 passed in 1.00s"),   # killed after the summary, before it exited
    # taskkill /F and Popen.terminate(), measured by kill_probe.py of the r11 review: status 1
    # and the dots already flushed. The case here used to be (1, ""), which nobody had measured.
    (1, "..."),
], ids=["ctrl_c", "windows_ctrl_c_exit", "signal", "signal_after_the_summary",
        "taskkill_or_terminate"])
def test_a_pytest_that_did_not_end_by_itself_is_interrupted_not_invalid(code, stdout):
    """Z16 of the r10 verification: INVALIDO, then the campaign died in Z17; alone, both are
    CAUGHT. Calling it broken said something about the mutant that nobody knew."""
    assert _verdict()(code, stdout) == "INTERRUMPIDO"


def test_a_failure_seen_before_the_interruption_is_still_a_catch():
    assert _verdict()(2, "FAILED tests/x.py::test_it - assert 1 == 2\nKeyboardInterrupt") == "CAUGHT"


# What pytest prints when it ends by itself without a failing test, measured on this machine with
# the campaign's flags (-q --no-header, 2026-10-05): each one is a broken mutant, not an
# interruption, because pytest wrote its closing line.
@pytest.mark.parametrize("code, stdout", [
    (2, "E   SyntaxError: invalid syntax\n=========================== short test summary info "
        "===========================\nERROR test_a.py\n!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during "
        "collection !!!!!!!!!!!!!!!!!!!!\n1 error in 0.21s\n"),
    (1, "test_a.py:4: RuntimeError\n=========================== short test summary info "
        "===========================\nERROR test_a.py::test_a - RuntimeError: x\n1 error in 0.07s\n"),
    (1, "ERROR test_a.py::test_a - RuntimeError: x\n1 error, 1 warning in 0.07s\n"),
    (5, "\nno tests ran in 0.00s\n"),
    (1, "ERROR test_a.py::test_a - RuntimeError: x\n1 error, 169 passed in 324.80s (0:05:24)\n"),
], ids=["collection_error", "fixture_error", "with_a_warning", "no_tests_ran", "long_run"])
def test_a_pytest_that_ended_by_itself_without_a_failure_is_invalid(code, stdout):
    assert _verdict()(code, stdout) == "INVALIDO"
