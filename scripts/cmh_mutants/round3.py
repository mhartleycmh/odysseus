"""The 10 mutants the third independent review left alive, plus 4 of my own.

Run it against an EXPORT of the tag, never the live tree: the third review had
to repoint round2.py by hand because it wrote mutations into versioned files
while a review needed the tree still. CMH_MUTANT_REPO overrides the target.

    git archive <tag> | tar -x -C /tmp/export
    CMH_MUTANT_REPO=/tmp/export python scripts/cmh_mutants/round3.py

A mutant whose pattern stops matching is reported as NO APLICABLE and counted
separately: round 2's runner let a stale pattern quietly leave the denominator.
"""

import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(os.environ.get("CMH_MUTANT_REPO") or
                    pathlib.Path(__file__).resolve().parents[2])
PY = pathlib.Path(sys.executable)
if not PY.exists() or "python" not in PY.name.lower():
    PY = REPO.parent.parent / ".venv" / "Scripts" / "python.exe"

TESTS = ["tests/test_cmh_review_findings.py", "tests/test_cmh_seed_scripts.py",
         "tests/test_cmh_provider_router.py", "tests/test_cmh_cost_policy.py",
         "tests/test_cmh_workflow_routes.py", "tests/test_cmh_control_routes.py"]

WF = "routes/cmh_workflow_routes.py"
FLOW = "src/cmh_workflows.py"
SEED = "scripts/cmh_seed_agents.py"

#: Three mutants were measured to be EQUIVALENT and retired from the campaign
#: rather than left as permanent survivors, which would rot the figure:
#:
#: * R01 `_provider_key` losing `.lower()` — `_canonical_route` already lowered
#:   the host, so the call could never see an uppercase character. The dead code
#:   was removed instead.
#: * R13 the dry run opening the source read-write — SQLite opens a read-only
#:   file read-write happily until something writes, so the change has no
#:   observable effect here. `mode=ro` stays as defence, declared unmeasured.
#: * R16 local-only judging the URL instead of the registered row — unreachable,
#:   because the cost gate refuses an api-labelled loopback at definition time,
#:   before the policy check runs. Pinned by
#:   test_a_loopback_endpoint_labelled_as_external_is_refused_outright.
MUTANTS = [

    ("R02 _canonical_route deja de quitar el punto final", WF,
     '    host = (parsed.hostname or "").strip().lower().rstrip(".")',
     '    host = (parsed.hostname or "").strip().lower()'),
    ("R02b _canonical_route deja de quitar el puerto por defecto", WF,
     '    if port is not None and port != _DEFAULT_PORTS.get((parsed.scheme or "").lower()):',
     '    if port is not None:'),
    ("R03 el id congelado ignora la fila y usa siempre la URL", WF,
     '        candidates = [{"endpoint_id": (getattr(task_row, "id", None)\n'
     '                                       or _canonical_route(task.endpoint_url)),',
     '        candidates = [{"endpoint_id": _canonical_route(task.endpoint_url),'),
    ("R03b la URL del candidato vuelve a la cruda (con credencial)", WF,
     '                       "endpoint_url": _canonical_route(task.endpoint_url),',
     '                       "endpoint_url": task.endpoint_url,'),
    ("R09 _checked_policy rechaza la cadena vacia", FLOW,
     '    if value in (None, ""):\n        return None',
     '    if value is None:\n        return None'),
    ("R10 _checked_policy guarda el valor crudo, sin normalizar", FLOW,
     '    return policy', '    return value'),
    ("R12 _snapshot no pasa local_model", WF,
     '    candidates = resolve_candidates(db, policy, owner, local_model=agent.model)',
     '    candidates = resolve_candidates(db, policy, owner)'),

    ("R14 la copia de simulacion usa nombre fijo, no el pid", SEED,
     'f"cmh-seed-dryrun-{os.getpid()}.db"', '"cmh-seed-dryrun.db"'),
    ("R15 apply() borra el agente preservado", SEED,
     "    for row in rows:\n        agent = (db.query(CMHAgent)",
     "    db.query(CMHAgent).filter(CMHAgent.name == PRESERVE).delete()\n"
     "    for row in rows:\n        agent = (db.query(CMHAgent)"),

    # Repointed after the fourth round rewrote the deduplication: the old
    # pattern matched code that no longer exists, and an obsolete pattern is
    # reported as NO APLICABLE precisely so it cannot vanish from the count.
    ("R17 la deduplicacion por proveedor se retira", WF,
     "    seen, unique = set(), []",
     "    seen, unique = set(), []\n    candidates = list(candidates)\n    _skip = "),
    ("R18 --policy deja de validarse en el guion", SEED,
     '    policy = normalize_policy(args.policy)\n    if policy is None:',
     '    policy = args.policy\n    if False:'),
    ("R19 la guarda de carpeta protegida del guion se retira", SEED,
     '    area = protected_area(WORKSPACES) if WORKSPACES.exists() else None',
     '    area = None'),
    ("R20 la copia de simulacion deja de borrarse", SEED,
     '                _SCRATCH[0].unlink(missing_ok=True)', '                pass'),
]


def run():
    return subprocess.run([str(PY), "-m", "pytest", *TESTS, "-p", "no:cacheprovider",
                           "-q", "--no-header"], cwd=str(REPO),
                          capture_output=True, text=True)


def main() -> int:
    print(f"Repositorio bajo mutacion: {REPO}")
    caught = survived = skipped = 0
    for name, relative, old, new in MUTANTS:
        path = REPO / relative
        original = path.read_text(encoding="utf-8")
        if old not in original:
            print(f"{name}: NO APLICABLE (patron no encontrado)")
            skipped += 1
            continue
        path.write_text(original.replace(old, new, 1), encoding="utf-8")
        try:
            result = run()
            failed = [l.split("::")[-1] for l in result.stdout.splitlines()
                      if l.startswith("FAILED")]
            if result.returncode:
                caught += 1
                print(f"{name}: CAUGHT - cae: {failed[0] if failed else '?'}")
            else:
                survived += 1
                print(f"{name}: *** SURVIVED ***")
        finally:
            path.write_text(original, encoding="utf-8")

    total = caught + survived + skipped
    print(f"\n{caught} CAUGHT - {survived} SURVIVED - {skipped} NO APLICABLE "
          f"(de {total}; un patron obsoleto NO sale del denominador)")
    final = run()
    print("Arbol restaurado:", [l for l in final.stdout.splitlines()
                                if "passed" in l or "failed" in l][-1:])
    return 1 if survived or skipped else 0


if __name__ == "__main__":
    sys.exit(main())
