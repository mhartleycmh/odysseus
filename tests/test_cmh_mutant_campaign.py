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


# --- review of revision-fase1-r7: what the first tests of the loop still let through ---------

def test_the_baseline_runs_the_union_of_every_mutants_tests_not_just_the_first(tmp_path, capsys):
    """Round4, round5 and round9 designate different modules per mutant. A baseline over only
    the first mutant's tests would miss a red test in another module, and with it every mutant
    of that module would 'fall' again, the defect of the baseline itself."""
    root = toy(tmp_path)
    (root / "tests" / "test_other.py").write_text("def test_red():\n    assert False\n",
                                                  encoding="utf-8")
    before = (root / "mod.py").read_bytes()
    code = run(root, mutant("M1", "return x * 2", "return x * 3"),
               mutant("M2", "return x + 1", "return x + 2", ["tests/test_other.py"]))
    assert code == 4
    assert "LINEA BASE ROJA" in capsys.readouterr().out
    assert (root / "mod.py").read_bytes() == before


def test_the_summary_line_counts_every_outcome_and_keeps_them_in_the_total(tmp_path, capsys):
    """Four DIFFERENT counts (1, 2, 3, 4): with one of each, swapping any two labels of the line
    printed the same text and the mutant T15 of round4 survived (measured on r8)."""
    root = toy(tmp_path)
    code = run(root,
               mutant("CAUGHT", "return x * 2", "return x * 3"),
               mutant("SURVIVED-1", "return x + 1", "return x + 2"),
               mutant("SURVIVED-2", "return x + 1", "return x + 3"),
               mutant("BROKEN-1", "return len(label)", "return len(label) +"),
               mutant("BROKEN-2", "return len(label)", "return len(label) -"),
               mutant("BROKEN-3", "return len(label)", "return len(label) *"),
               mutant("OBSOLETE-1", "return x * 99", "return x * 100"),
               mutant("OBSOLETE-2", "return x * 98", "return x * 100"),
               mutant("OBSOLETE-3", "return x * 97", "return x * 100"),
               mutant("OBSOLETE-4", "return x * 96", "return x * 100"))
    out = capsys.readouterr().out
    assert code == 1
    assert "1 CAUGHT - 2 SURVIVED - 3 INVALIDOS - 4 NO APLICABLE (de 10;" in out


@pytest.mark.parametrize("escape", ["../outside.py", "ABSOLUTE"])
def test_a_mutant_may_only_name_a_file_inside_the_export(tmp_path, escape):
    """The live-tree guard looks at the repo folder. A path with '..' or an absolute one was
    opened, mutated and restored OUTSIDE it."""
    root = toy(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("def f(x):\n    return x * 2\n", encoding="utf-8")
    relative = str(outside) if escape == "ABSOLUTE" else escape
    before = outside.read_bytes()
    with pytest.raises(SystemExit, match="fuera del repositorio"):
        run(root, ("ESC", relative, "x * 2", "x * 99", TESTS))
    assert outside.read_bytes() == before


@pytest.mark.parametrize("as_file", [False, True])
def test_a_git_file_or_folder_both_mark_a_working_tree(tmp_path, monkeypatch, as_file):
    """In a git worktree .git is a FILE: .is_dir() would have let it through."""
    monkeypatch.delenv("CMH_MUTANT_ALLOW_LIVE", raising=False)
    root = toy(tmp_path)
    (root / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8") if as_file \
        else (root / ".git").mkdir()
    with pytest.raises(SystemExit, match="arbol vivo"):
        run(root, mutant("M1", "return x * 2", "return x * 3"))


@pytest.mark.parametrize("value", ["0", "", "true", "yes"])
def test_only_the_value_one_lifts_the_working_tree_guard(tmp_path, monkeypatch, value):
    monkeypatch.setenv("CMH_MUTANT_ALLOW_LIVE", value)
    root = toy(tmp_path, git=True)
    with pytest.raises(SystemExit, match="arbol vivo"):
        run(root, mutant("M1", "return x * 2", "return x * 3"))


def test_the_value_one_does_lift_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CMH_MUTANT_ALLOW_LIVE", "1")
    root = toy(tmp_path, git=True)
    assert run(root, mutant("M1", "return x * 2", "return x * 3")) == 0


@pytest.mark.parametrize("line, expected", [
    ("FAILED tests/t.py::test_x[carpeta OneDrive-guardado en OneDrive - CMH] - AssertionError: assert False",
     "test_x[carpeta OneDrive-guardado en OneDrive - CMH]"),
    ("FAILED tests/t.py::test_x[a] - AssertionError: assert [1] == [2]", "test_x[a]"),
    ("FAILED tests/t.py::test_plain - boom [x]", "test_plain"),
    ("FAILED tests/t.py::test_a[[fe80::1]] - boom", "test_a[[fe80::1]]"),
    ("FAILED tests/t.py::test_bare", "test_bare"),
])
def test_failed_id_keeps_brackets_with_a_dash_inside_and_drops_the_message(line, expected):
    assert target.failed_id(line) == expected


class _Recorder(__import__("io").StringIO):
    flushes = 0

    def flush(self):
        type(self).flushes += 1
        super().flush()


def test_progress_is_flushed_and_the_file_being_mutated_is_announced(tmp_path, monkeypatch):
    """A campaign redirected to a file showed nothing until it ended, and a killed one left a
    mutant in place without a word: each line is flushed and the mutated file is named first."""
    root = toy(tmp_path)
    recorder = _Recorder()
    _Recorder.flushes = 0
    monkeypatch.setattr(sys, "stdout", recorder)
    assert run(root, mutant("M1", "return x * 2", "return x * 3")) == 0
    out = recorder.getvalue()
    assert "(mutando mod.py para M1)" in out
    assert "Arbol restaurado (las pruebas que designan los mutantes, no el modulo entero)" in out
    assert _Recorder.flushes >= 5          # header, announcement, verdict, summary, restored tree
