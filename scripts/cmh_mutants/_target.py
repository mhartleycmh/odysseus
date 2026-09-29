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
