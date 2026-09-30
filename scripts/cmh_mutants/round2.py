"""Re-run the 9 mutants the SECOND review left alive, plus 4 for the new fixes.

The reviewer's point about traceability was fair: the mutants of round 1 lived
only in a scratch file. This one is committed under scripts/ so the figure can
be reproduced.
"""

import pathlib
import sys

from _target import resolve_repo
from _target import campaign

# Was a hard-coded absolute path to the LIVE tree that ignored CMH_MUTANT_REPO:
# a campaign launched on an export mutated the working tree instead. resolve_repo
# takes the export from CMH_MUTANT_REPO and refuses any directory with a .git.
REPO = resolve_repo(pathlib.Path(__file__).resolve().parents[2])
PY = pathlib.Path(sys.executable)
if not PY.exists() or "python" not in PY.name.lower():
    PY = REPO.parent.parent / ".venv" / "Scripts" / "python.exe"

TESTS = ["tests/test_cmh_review_findings.py", "tests/test_cmh_provider_router.py",
         "tests/test_cmh_cost_policy.py", "tests/test_cmh_seed_scripts.py",
         "tests/test_cmh_workflow_routes.py", "tests/test_cmh_control_routes.py"]

MUTANTS = [
    # --- the nine that survived round 2 -------------------------------------
    ("M05b _frozen_candidates deja de rellenar host", "src/cmh_workflows.py",
     '        if not entry.get("host"):\n            entry["host"] = endpoint_host(entry.get("endpoint_url"))',
     '        pass'),
    ("M06 _zero_cost_candidates vuelve al setdefault previo", "src/cmh_workflows.py",
     '            if getattr(row, "id", None):\n                candidate["endpoint_id"] = row.id',
     '            pass'),
    ("M13 _snapshot pierde la guarda de lista vacia", "routes/cmh_workflow_routes.py",
     '    if not candidates:\n        raise HTTPException(400, f"Step {spec[\'key\']}: la politica \'{policy}\' no deja "\n                                 f"ningun candidato gratuito disponible")',
     '    pass'),
    ("M17b actualizar agente no guarda provider_policy", "routes/cmh_control_routes.py",
     "            agent.provider_policy = normalize_policy(body.provider_policy)",
     "            pass"),
    ("M19 el guion deja de validar entradas primero", "scripts/cmh_seed_agents.py",
     "    for role, _, _ in AGENTS:\n        instructions_for(role)",
     "    pass"),
    ("M20 la simulacion vuelve a abrir la base real", "scripts/cmh_seed_agents.py",
     '        os.environ["DATABASE_URL"] = f"sqlite:///{scratch.as_posix()}"',
     '        pass'),
    ("M22 se retira la migracion de provider_policy", "core/database.py",
     '            if agent_columns and "provider_policy" not in agent_columns:\n                conn.execute(text("ALTER TABLE cmh_agents ADD COLUMN provider_policy VARCHAR"))',
     '            pass'),
    ("M24 default_tool_evidence deja de bajar a minusculas", "src/cmh_workflows.py",
     '    return str(step_key or "").strip().lower() not in _NO_EVIDENCE_ROLES',
     '    return str(step_key or "").strip() not in _NO_EVIDENCE_ROLES'),
    # M25 (already_listed and -> or) and M26 (dedup ignoring the port) were RETIRED
    # on 2026-09-29: the fourth round replaced the code they mutated with
    # _provider_key/_canonical_route, so their patterns no longer exist. What they
    # guarded is covered by round3's R02, R02b and R17. They stayed in the list as
    # patterns that matched nothing, and a runner that skips a pattern that
    # matches nothing reports a smaller number than the one it was asked for.
    ("M27 resolved_model no se persiste en el config del paso", "src/cmh_workflows.py",
     '            if config.get("resolved_model"):\n                step.config = json.dumps(config)',
     '            pass'),
    # --- four against what this round changed -------------------------------
    # Repointed on 2026-09-29: the id is now built from the row or the canonical URL.
    ("N1 el id congelado vuelve a poder ser None", "routes/cmh_workflow_routes.py",
     '"endpoint_id": (getattr(task_row, "id", None)\n'
     '                                       or _canonical_route(task.endpoint_url)),',
     '"endpoint_id": None,'),
    ("N2 create_run vuelve a su propio default True", "routes/cmh_workflow_routes.py",
     '                config["require_tool_evidence"] = (\n                    bool(stated) if stated is not None\n                    else default_tool_evidence(spec["key"]))',
     '                config["require_tool_evidence"] = True'),
    ("N3 el artefacto vuelve a rotular con el primer candidato", "src/cmh_workflows.py",
     '                model=config.get("resolved_model") or config["model"],',
     '                model=config["model"],'),
    ("N4 una politica desconocida vuelve a aceptarse", "src/cmh_workflows.py",
     '    policy = normalize_policy(value)\n    if policy is None:',
     '    policy = normalize_policy(value)\n    if False:'),
]


if __name__ == "__main__":
    # The mutants of this round are (name, file, old, new); they all answer to TESTS.
    sys.exit(campaign([(*m, TESTS) for m in MUTANTS], REPO, PY))
