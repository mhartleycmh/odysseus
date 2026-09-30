"""Mutants for the corrections of the independent review of 2026-09-29 (r7) that live
outside the gate, the discovery, the sink and the two local scripts: what a run freezes,
what a PATCH stores, what the shared HTTP client does with a proxy, and the seed script.

Each capability names the test module that must fall. A mutant that does not fall is a
test that cannot fail: that is the only reason this file exists.

Run it against an EXPORT of a commit, never the live tree. The runner refuses a
directory that contains .git (see _target.py).

    git archive <commit> | tar -x -C /tmp/export
    CMH_MUTANT_REPO=/tmp/export python scripts/cmh_mutants/round9.py
"""

import pathlib
import sys

from _target import resolve_repo
from _target import campaign

REPO = resolve_repo(pathlib.Path(__file__).resolve().parents[2])
PY = pathlib.Path(sys.executable)
if not PY.exists() or "python" not in PY.name.lower():
    PY = REPO.parent.parent / ".venv" / "Scripts" / "python.exe"

POLICY_TESTS = ["tests/test_cmh_cost_policy.py"]
FREEZE_TESTS = ["tests/test_cmh_provider_discovery.py"]
PATCH_TESTS = ["tests/test_cmh_endpoint_patch.py"]
PROXY_TESTS = ["tests/test_cmh_llm_core_proxy.py"]
SEED_TESTS = ["tests/test_cmh_seed_scripts.py"]

POLICY = "src/cmh_cost_policy.py"
ROUTER = "src/cmh_provider_router.py"
MODEL_ROUTES = "routes/model_routes.py"
LLM_CORE = "src/llm_core.py"
SEED = "scripts/cmh_seed_agents.py"

#: (name, file, text to replace, replacement, test modules that must fall)
MUTANTS = [
    # --- what a run freezes carries no credential ----------------------------------
    ("F01 strip_userinfo conserva usuario y clave", POLICY,
     '    return parts._replace(netloc=parts.netloc.rsplit("@", 1)[-1]).geturl()',
     "    return base_url",
     POLICY_TESTS),
    ("F02 strip_userinfo tambien borra la query", POLICY,
     '    return parts._replace(netloc=parts.netloc.rsplit("@", 1)[-1]).geturl()',
     '    return parts._replace(netloc=parts.netloc.rsplit("@", 1)[-1], query="").geturl()',
     POLICY_TESTS),
    ("F03 el candidato de nube se congela con la URL de la fila tal cual", ROUTER,
     '                                   "endpoint_url": strip_userinfo(row.base_url),\n'
     '                                   "model": model, "host": host})',
     '                                   "endpoint_url": row.base_url,\n'
     '                                   "model": model, "host": host})',
     FREEZE_TESTS),
    ("F04 el candidato local se congela con la URL de la fila tal cual", ROUTER,
     '                           "endpoint_url": strip_userinfo(row.base_url),\n'
     '                           "model": model, "host": endpoint_host(row.base_url)})',
     '                           "endpoint_url": row.base_url,\n'
     '                           "model": model, "host": endpoint_host(row.base_url)})',
     FREEZE_TESTS),

    # --- PATCH lifts the credential out of a base_url -------------------------------
    ("P01 PATCH guarda la URL con su credencial", MODEL_ROUTES,
     "    return split_url_credentials(_normalize_base(base))",
     "    return _normalize_base(base), None",
     PATCH_TESTS),
    ("P02 la clave de la URL pisa a la clave explicita del mismo PATCH", MODEL_ROUTES,
     "    if url_key and not explicit:",
     "    if url_key:",
     PATCH_TESTS),
    ("P03 un PATCH sin credencial en la URL borra la clave guardada", MODEL_ROUTES,
     "    if url_key and not explicit:",
     "    if not explicit:",
     PATCH_TESTS),
    ("P04 una clave en blanco cuenta como explicita", MODEL_ROUTES,
     '    explicit = isinstance(body.get("api_key"), str) and body["api_key"].strip()',
     '    explicit = isinstance(body.get("api_key"), str)',
     PATCH_TESTS),
    ("P05 un base_url vacio borra el guardado", MODEL_ROUTES,
     "    if not base:\n        return\n    ep.base_url = base",
     "    ep.base_url = base",
     PATCH_TESTS),

    # --- a local route never goes through a system proxy ----------------------------
    ("X01 el cliente compartido vuelve a ser un AsyncClient sin mas", LLM_CORE,
     "        _http_client = _LocalDirectClient(",
     "        _http_client = httpx.AsyncClient(",
     PROXY_TESTS),
    ("X02 el cliente ya no distingue una ruta local", LLM_CORE,
     "        if is_reachable_without_leaving_the_network(url.host):",
     "        if False:",
     PROXY_TESTS),
    ("X03 toda ruta se manda directa, tambien la de la nube", LLM_CORE,
     "        if is_reachable_without_leaving_the_network(url.host):",
     "        if True:",
     PROXY_TESTS),

    # --- the seed script -------------------------------------------------------------
    ("Z01 la URI de la copia se arma a mano sin escapar la ruta", SEED,
     '    return sqlite3.connect(f"{pathlib.Path(path).resolve().as_uri()}?mode=ro", uri=True)',
     '    return sqlite3.connect(f"file:{pathlib.Path(path).as_posix()}?mode=ro", uri=True)',
     SEED_TESTS),
    ("Z02 la copia ya no se compara con el origen", SEED,
     "    if found != expected:",
     "    if False:",
     SEED_TESTS),
    ("Z03 la simulacion sobre una base que no existe crea la base", SEED,
     '        os.environ["DATABASE_URL"] = "sqlite:///:memory:"',
     "        pass",
     SEED_TESTS),
    ("Z04 un endpoint local basta para sembrar bajo free-cloud-first", SEED,
     "    return any(candidate.get(\"host\") in FREE_HOSTS for candidate in candidates)",
     "    return bool(candidates)",
     SEED_TESTS),
    ("Z05 bajo local-only se exige un endpoint de nube", SEED,
     "    if policy == LOCAL_ONLY:\n        return bool(candidates)",
     "    if False:\n        return bool(candidates)",
     SEED_TESTS),
    ("Z06 sembrar sin candidato utilizable ya no se detiene", SEED,
     "    if not usable and not args.allow_pending:",
     "    if False:",
     SEED_TESTS),
    ("Z07 --allow-pending deja de permitir sembrar", SEED,
     "    if not usable and not args.allow_pending:",
     "    if not usable:",
     SEED_TESTS),
    ("Z08 el mensaje vuelve a decir que la copia previa se puede borrar", SEED,
     '        print("Abrir la base para calcular esto pudo migrarla (init_db): la copia previa de "\n'
     '              "arriba es de ANTES de abrirla. Conservala.")',
     '        print("La copia previa de arriba se hizo antes de abrir la base; puedes borrarla.")',
     SEED_TESTS),
]


if __name__ == "__main__":
    sys.exit(campaign(MUTANTS, REPO, PY))
