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
