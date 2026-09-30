"""A mutant campaign may only write into an export (no .git), never the live tree.

round2.py hard-coded the path of the live tree and ignored CMH_MUTANT_REPO, so a
campaign launched "on the export" mutated the working tree for several minutes,
and every test run made in that window measured a tree with a mutant in it.

The guarantee is checked twice, because the failure mode of a test that RUNS a
runner to see whether it refuses is that a broken runner starts mutating:
``resolve_repo`` is exercised as a pure function, and each runner is checked
statically for going through it and for not carrying an absolute path.
"""

import importlib.util
import pathlib
import re

import pytest

MUTANTS = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "cmh_mutants"
# Whatever runners exist: a new round must not escape the check by being new.
RUNNERS = sorted(path.name for path in MUTANTS.glob("round*.py"))


def _target():
    spec = importlib.util.spec_from_file_location("cmh_mutant_target", MUTANTS / "_target.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_directory_with_git_is_refused_even_when_pointed_at_explicitly(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("CMH_MUTANT_REPO", str(tmp_path))
    monkeypatch.delenv("CMH_MUTANT_ALLOW_LIVE", raising=False)
    with pytest.raises(SystemExit, match="arbol vivo"):
        _target().resolve_repo(pathlib.Path("."))


def test_the_default_location_is_refused_when_it_is_the_live_tree(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.delenv("CMH_MUTANT_REPO", raising=False)
    monkeypatch.delenv("CMH_MUTANT_ALLOW_LIVE", raising=False)
    with pytest.raises(SystemExit):
        _target().resolve_repo(tmp_path)


def test_an_export_is_accepted_and_the_override_wins_over_the_default(tmp_path, monkeypatch):
    export = tmp_path / "export"
    export.mkdir()
    monkeypatch.setenv("CMH_MUTANT_REPO", str(export))
    monkeypatch.delenv("CMH_MUTANT_ALLOW_LIVE", raising=False)
    assert _target().resolve_repo(pathlib.Path("/not/used")) == export


def test_the_explicit_escape_hatch_is_the_only_way_to_mutate_a_tree_with_git(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("CMH_MUTANT_REPO", str(tmp_path))
    monkeypatch.setenv("CMH_MUTANT_ALLOW_LIVE", "1")
    assert _target().resolve_repo(pathlib.Path(".")) == tmp_path


@pytest.mark.parametrize("runner", RUNNERS)
def test_every_runner_takes_its_target_from_resolve_repo(runner):
    source = (MUTANTS / runner).read_text(encoding="utf-8")
    assert re.search(r"^REPO = resolve_repo\(", source, re.MULTILINE), runner
    assert "from _target import resolve_repo" in source, runner


# A drive letter, a separator, a component of two or more characters and another
# separator. Looser than that matches "s:\n" inside a mutant's search pattern.
_DRIVE_PATH = re.compile(r"\b[A-Za-z]:(?:\\{1,2}|/{1,2})[A-Za-z0-9_.-]{2,}(?:\\{1,2}|/{1,2})")


def test_the_path_pattern_recognises_the_defect_it_guards_against():
    """Positive control: without it the next test could pass because it sees nothing."""
    defect = r'REPO = pathlib.Path(r"c:\Users\someone\OneDrive - CMH S.R.L\Claude\odysseus")'
    assert _DRIVE_PATH.search(defect)
    assert _DRIVE_PATH.search('REPO = "C:/Users/someone/odysseus"')
    assert not _DRIVE_PATH.search("'    if not candidates:\\n        raise HTTPException(400)'")


@pytest.mark.parametrize("runner", RUNNERS)
def test_no_runner_carries_an_absolute_path_to_a_tree(runner):
    """The defect itself: a drive-letter path literal that pointed at the live tree."""
    source = (MUTANTS / runner).read_text(encoding="utf-8")
    assert not _DRIVE_PATH.search(source), runner


@pytest.mark.parametrize("runner", RUNNERS)
def test_every_runner_hands_its_mutants_to_campaign_and_has_no_loop_of_its_own(runner):
    """Replacing each round's private loop with campaign() closed P2 n16, and nothing held it:
    a runner ending in sys.exit(0) would mutate nothing and exit green, and pass every test
    here."""
    source = (MUTANTS / runner).read_text(encoding="utf-8")
    assert re.search(r"^\s*sys\.exit\(campaign\(.*\bREPO, PY\)\)", source, re.MULTILINE), runner
    assert "subprocess" not in source and "write_text" not in source, runner
