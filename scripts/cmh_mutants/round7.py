"""Mutants for step 3.5: the seeding script (five agents and their flow definition).

Each mutant names the ONE test that must fall, by node id. The script is never
run against the user's database here: these tests seed throwaway databases.

Run it against an EXPORT of a commit, never the live tree. The runner refuses a
directory that contains .git (see _target.py).

    git archive <commit> | tar -x -C /tmp/export
    CMH_MUTANT_REPO=/tmp/export python scripts/cmh_mutants/round7.py
"""

import pathlib
import sys

from _target import resolve_repo
from _target import campaign

REPO = resolve_repo(pathlib.Path(__file__).resolve().parents[2])
PY = pathlib.Path(sys.executable)
if not PY.exists() or "python" not in PY.name.lower():
    PY = REPO.parent.parent / ".venv" / "Scripts" / "python.exe"

MODULE = "tests/test_cmh_seed_scripts.py"
SEED = "scripts/cmh_seed_agents.py"


def only(name):
    return [f"{MODULE}::{name}"]


POLICY = only("test_the_policy_is_stored_on_every_agent")
TWICE = only("test_seeding_twice_gives_five_agents_and_one_definition_and_the_second_run_changes_nothing")
SHAPE = only("test_the_definition_has_the_shape_the_control_view_builds")
VERSION = only("test_a_stored_definition_that_differs_gets_a_new_version_and_the_old_one_is_left_alone")
EMPTY = only("test_it_refuses_to_seed_an_empty_chain_and_writes_nothing")
PENDING = only("test_allow_pending_seeds_anyway_and_the_agents_have_no_model_until_it_is_run_again")
DATA_DIR = only("test_the_live_path_follows_odysseus_data_dir_like_core_database_does")
BACKUP = only("test_a_second_backup_in_the_same_second_does_not_overwrite_the_first")
CONSOLE = only("test_a_console_that_cannot_print_the_names_does_not_end_the_script")

#: (name, file, text to replace, replacement, test node ids that must fall)
MUTANTS = [
    ("SD01 la politica se valida pero no se guarda en el agente", SEED,
     '        agent.provider_policy = row["policy"]',
     '        pass',
     POLICY),
    ("SD02 la siembra ya no crea la definicion", SEED,
     '    definition = ensure_definition(db, owner, rows[0]["project_id"], agent_ids)',
     '    definition = {"id": "-", "version": 0, "action": "omitida"}',
     SHAPE),
    ("SD03 una definicion identica se vuelve a crear en cada siembra", SEED,
     '    if latest is not None and json.loads(latest.steps) == steps:',
     '    if False:',
     TWICE),
    ("SD04 una definicion distinta reutiliza la version 1", SEED,
     'version=(latest.version + 1) if latest else 1,',
     'version=1,',
     VERSION),
    ("SD05 la compuerta humana tambien cae sobre el verificador", SEED,
     'HUMAN_GATE = {"revisor"}',
     'HUMAN_GATE = {"revisor", "verificador"}',
     SHAPE),
    ("SD06 el revisor deja de ser independiente del constructor", SEED,
     'INDEPENDENT_OF = {"verificador": ["constructor"], "revisor": ["constructor"]}',
     'INDEPENDENT_OF = {"verificador": ["constructor"]}',
     SHAPE),
    ("SD07 el documentador pasa a exigir evidencia de herramientas", SEED,
     'NO_TOOL_EVIDENCE = {"revisor", "documentador"}',
     'NO_TOOL_EVIDENCE = {"revisor"}',
     SHAPE),
    ("SD08 se siembra una cadena sin ningun endpoint gratuito", SEED,
     '    if not rows[0]["candidates"] and not args.allow_pending:',
     '    if False:',
     EMPTY),
    ("SD09 --allow-pending deja de permitir sembrar", SEED,
     '    if not rows[0]["candidates"] and not args.allow_pending:',
     '    if not rows[0]["candidates"]:',
     PENDING),
    ("SD10 la ruta de la base ignora ODYSSEUS_DATA_DIR", SEED,
     '    data_dir = os.environ.get("ODYSSEUS_DATA_DIR")',
     '    data_dir = None',
     DATA_DIR),
    ("SD11 una ruta relativa de DATABASE_URL no se resuelve contra la raiz", SEED,
     '        return path if path.is_absolute() else REPO / path',
     '        return path',
     DATA_DIR),
    ("SD12 la copia previa reutiliza un nombre que ya existe", SEED,
     '    while target.exists():',
     '    while False:',
     BACKUP),
    ("SD13 una consola que no puede imprimir un caracter termina el guion", SEED,
     '            stream.reconfigure(errors="replace")',
     '            pass',
     CONSOLE),
]


if __name__ == "__main__":
    sys.exit(campaign(MUTANTS, REPO, PY))
