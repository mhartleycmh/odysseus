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

    Parsed, not imported: round2 runs its whole campaign at import time.
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


@pytest.mark.parametrize("runner", RUNNERS)
def test_every_mutant_is_applicable_and_compiles(runner):
    broken = []
    mutants = _mutants(runner)
    assert mutants, runner
    for name, relative, old, new in mutants:
        source = (REPO / relative).read_text(encoding="utf-8")
        if old not in source:
            broken.append(f"{name}: el patron ya no existe en {relative}")
            continue
        mutated = source.replace(old, new, 1)
        if mutated == source:
            broken.append(f"{name}: el mutante no cambia nada")
            continue
        try:
            compile(mutated, relative, "exec")
        except SyntaxError as exc:
            broken.append(f"{name}: no compila ({exc.msg}, linea {exc.lineno})")
    assert not broken, "\n".join(broken)


def test_a_mutant_that_does_not_compile_is_reported_as_broken_and_not_as_caught():
    verdict = _verdict()
    collection_error = "ERROR tests/x.py - SyntaxError: invalid syntax\n1 error in 0.10s"
    assert verdict(2, collection_error) == "INVALIDO"
    assert verdict(1, "FAILED tests/x.py::test_it - assert 1 == 2\n1 failed") == "CAUGHT"
    assert verdict(0, "24 passed") == "SURVIVED"


def test_the_verdict_needs_a_failing_test_not_just_a_non_zero_exit():
    verdict = _verdict()
    for code in (1, 2, 3, 4, 5):
        assert verdict(code, "no test ran") == "INVALIDO", code
