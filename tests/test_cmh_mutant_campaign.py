"""The mutation campaign loop, measured on a toy repo: what it counts, what it refuses,
and that it leaves every file byte for byte as it found it.

The independent review of 2026-09-29 found that the loop everything else leans on
had no test of its own: its ``finally`` could become ``pass``, its exit status could
become ``return 0``, it ran no baseline (so with one red test in the tree every mutant
"fell", even one that changed nothing), it accepted the live tree if a runner skipped
``resolve_repo``, and it restored files with ``write_text``, which rewrites CRLF as
the platform default. Each of those is a test here, on a repo small enough to read.
"""

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cmh_mutant_target_campaign",
                                              REPO / "scripts" / "cmh_mutants" / "_target.py")
target = importlib.util.module_from_spec(spec)
spec.loader.exec_module(target)

MOD = "def double(x):\n    return x * 2\n\n\ndef measure(label):\n    return len(label)\n\n\ndef unused(x):\n    return x + 1\n"
TESTS = ["tests/test_mod.py"]
TEST_MOD = '''import os

import pytest
from mod import double, measure


def test_double():
    assert double(3) == 6


def test_no_poison_left_behind():
    assert not os.path.exists("poison")


@pytest.mark.parametrize("label", ["[fe80::1]"])
def test_measure_a_label_with_colons(label):
    assert measure(label) == len(label)
'''


def toy(tmp_path, *, red=False, crlf=False, git=False):
    root = tmp_path / "toy"
    (root / "tests").mkdir(parents=True)
    (root / "conftest.py").write_text("", encoding="utf-8")
    body = MOD.replace("\n", "\r\n") if crlf else MOD
    (root / "mod.py").write_bytes(body.encode("utf-8"))
    test = TEST_MOD + ("\n\ndef test_always_red():\n    assert False\n" if red else "")
    (root / "tests" / "test_mod.py").write_text(test, encoding="utf-8")
    if git:
        (root / ".git").mkdir()
    return root


def mutant(name, old, new, tests=TESTS):
    return (name, "mod.py", old, new, tests)


def run(root, *mutants):
    return target.campaign(list(mutants), root, pathlib.Path(sys.executable))


def test_a_mutant_a_test_notices_is_caught_and_the_exit_status_is_zero(tmp_path, capsys):
    root = toy(tmp_path)
    assert run(root, mutant("M1", "return x * 2", "return x * 3")) == 0
    out = capsys.readouterr().out
    assert "M1: CAUGHT - cae: test_double" in out
    assert "1 CAUGHT - 0 SURVIVED - 0 INVALIDOS - 0 NO APLICABLE" in out


def test_a_mutant_no_test_notices_survives_and_the_exit_status_says_so(tmp_path, capsys):
    root = toy(tmp_path)
    assert run(root, mutant("M1", "return x + 1", "return x + 2")) == 1
    assert "M1: *** SURVIVED ***" in capsys.readouterr().out


def test_a_mutant_that_breaks_collection_is_invalid_not_caught(tmp_path, capsys):
    root = toy(tmp_path)
    assert run(root, mutant("M1", "return x * 2", "return x *")) == 1
    out = capsys.readouterr().out
    assert "M1: *** INVALIDO - rompe la coleccion" in out and "CAUGHT" not in out.split("\n\n")[0]


def test_a_pattern_that_is_not_there_is_not_applicable_and_fails_the_exit_status(tmp_path, capsys):
    root = toy(tmp_path)
    assert run(root, mutant("M1", "return x * 99", "return x * 100")) == 1
    assert "M1: NO APLICABLE" in capsys.readouterr().out


def test_a_mutant_that_changes_nothing_is_invalid(tmp_path, capsys):
    """With a red test in the tree it used to be counted CAUGHT."""
    root = toy(tmp_path)
    assert run(root, mutant("M1", "return x * 2", "return x * 2")) == 1
    assert "el mutante no cambia nada" in capsys.readouterr().out


def test_a_red_baseline_stops_the_campaign_before_it_mutates_anything(tmp_path, capsys):
    root = toy(tmp_path, red=True)
    before = (root / "mod.py").read_bytes()
    assert run(root, mutant("M1", "return x * 2", "return x * 3")) == 4
    out = capsys.readouterr().out
    assert "LINEA BASE ROJA" in out and "CAUGHT" not in out
    assert (root / "mod.py").read_bytes() == before


@pytest.mark.parametrize("crlf", [False, True])
def test_every_file_comes_back_byte_for_byte_including_its_line_endings(tmp_path, crlf, capsys):
    root = toy(tmp_path, crlf=crlf)
    before = (root / "mod.py").read_bytes()
    assert (b"\r\n" in before) is crlf
    assert run(root, mutant("M1", "return x * 2", "return x * 3"),
               mutant("M2", "return x + 1", "return x + 2")) == 1     # M2 survives
    assert (root / "mod.py").read_bytes() == before
    assert "M1: CAUGHT" in capsys.readouterr().out                   # and the pattern still applied


def test_a_multiline_pattern_still_applies_to_a_file_that_uses_crlf(tmp_path, capsys):
    """The rounds' patterns span lines; the file on disk may not use the same ending."""
    root = toy(tmp_path, crlf=True)
    assert run(root, mutant("M1", "def double(x):\n    return x * 2",
                            "def double(x):\n    return x * 3")) == 0
    assert "M1: CAUGHT" in capsys.readouterr().out


def test_a_restored_tree_that_is_not_green_fails_the_exit_status_even_if_all_were_caught(
        tmp_path, capsys):
    """A mutant can leave something behind that is not the file it patched."""
    root = toy(tmp_path)
    poison = 'return open("poison", "w").write("x") or x * 3'
    assert run(root, mutant("M1", "return x * 2", poison)) == 1
    out = capsys.readouterr().out
    assert "M1: CAUGHT" in out and "El arbol restaurado NO esta verde." in out


def test_campaign_itself_refuses_a_working_tree_even_when_the_runner_skipped_resolve_repo(
        tmp_path, monkeypatch):
    monkeypatch.delenv("CMH_MUTANT_ALLOW_LIVE", raising=False)
    root = toy(tmp_path, git=True)
    before = (root / "mod.py").read_bytes()
    with pytest.raises(SystemExit, match="arbol vivo"):
        run(root, mutant("M1", "return x * 2", "return x * 3"))
    assert (root / "mod.py").read_bytes() == before


def test_the_test_id_of_a_parameter_with_colons_is_not_cut(tmp_path, capsys):
    root = toy(tmp_path)
    assert run(root, mutant("M1", "return len(label)", "return len(label) + 1")) == 0
    assert "cae: test_measure_a_label_with_colons[[fe80::1]]" in capsys.readouterr().out


def test_failed_id_takes_everything_after_the_first_double_colon():
    line = "FAILED tests/test_x.py::test_a[[fe80::1]] - AssertionError: assert False"
    assert target.failed_id(line) == "test_a[[fe80::1]]"
    assert target.failed_id("FAILED tests/test_x.py::test_plain - boom") == "test_plain"
