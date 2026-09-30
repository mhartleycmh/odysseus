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
WF_ROUTES = "routes/cmh_workflow_routes.py"
ENDPOINT_RESOLVER = "src/endpoint_resolver.py"
ROUTER = "src/cmh_provider_router.py"
MODEL_ROUTES = "routes/model_routes.py"
LLM_CORE = "src/llm_core.py"
SEED = "scripts/cmh_seed_agents.py"

#: (name, file, text to replace, replacement, test modules that must fall)
MUTANTS = [
    # --- what a run freezes carries no credential ----------------------------------
    ("F01 has_userinfo nunca ve una credencial", POLICY,
     '        return "@" in urlparse(base_url or "").netloc',
     "        return False",
     POLICY_TESTS + FREEZE_TESTS),
    ("F02 has_userinfo busca la arroba en toda la URL y no solo en la autoridad", POLICY,
     '        return "@" in urlparse(base_url or "").netloc',
     '        return "@" in (base_url or "")',
     POLICY_TESTS),
    ("F03 la fila de nube con credencial se congela", ROUTER,
     '                if has_userinfo(row.base_url):\n'
     '                    _note_dropped(dropped, row, host, "credential_in_url")\n'
     '                    continue\n',
     "",
     FREEZE_TESTS),
    ("F04 la fila local con credencial se congela", ROUTER,
     '        if has_userinfo(row.base_url):\n'
     '            _note_dropped(dropped, row, endpoint_host(row.base_url), "credential_in_url")\n'
     '            continue\n',
     "",
     FREEZE_TESTS),
    ("F05 la fila que rechaza la compuerta se descarta sin decirlo", ROUTER,
     '                    _note_dropped(dropped, row, host, "cost_gate")',
     "                    pass",
     FREEZE_TESTS),
    ("F06 un run con una fila de credencial ya no se rechaza", WF_ROUTES,
     '        if note["reason"] == "credential_in_url":',
     "        if False:",
     FREEZE_TESTS),
    ("F07 el run no deja evento de la fila descartada", WF_ROUTES,
     "            for note in dropped_notes:",
     "            for note in []:",
     FREEZE_TESTS),
    ("F08 el descubrimiento consulta una URL que lleva credencial", ROUTER,
     '    if has_userinfo(getattr(row, "base_url", "")):\n        # httpx would turn',
     '    if False:\n        # httpx would turn',
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

    ("P06 la ruta PATCH deja de llamar al ayudante que levanta la credencial", MODEL_ROUTES,
     "                _apply_base_url_update(ep, body)",
     "                pass",
     PATCH_TESTS),
    ("P07 build_headers envuelve siempre en Bearer, tambien un Basic ya armado", ENDPOINT_RESOLVER,
     '        headers["Authorization"] = (api_key if api_key.startswith("Basic ")\n'
     '                                    else f"Bearer {api_key}")',
     '        headers["Authorization"] = f"Bearer {api_key}"',
     PATCH_TESTS),
    ("P08 la ruta POST deja la credencial en la URL", MODEL_ROUTES,
     "        base_url, url_key = split_url_credentials(base_url)",
     "        url_key = None",
     PATCH_TESTS),
    ("P09 build_headers deja pasar cualquier clave sin Bearer", ENDPOINT_RESOLVER,
     '        headers["Authorization"] = (api_key if api_key.startswith("Basic ")',
     '        headers["Authorization"] = (api_key if True',
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
     '    return any(candidate.get("host") in FREE_HOSTS\n'
     '               and (keyed is None or candidate.get("endpoint_id") in keyed)\n'
     '               for candidate in candidates)',
     "    return bool(candidates)",
     SEED_TESTS),
    ("Z05 bajo local-only se exige un endpoint de nube", SEED,
     "    if policy == LOCAL_ONLY:\n        return bool(candidates)",
     "    if False:\n        return bool(candidates)",
     SEED_TESTS),
    # Z06 and Z07 were SD08 and SD09 of round7 under another name (same file, pattern and
    # replacement): counted twice in r7's "239". They stay in round7 only.
    ("Z08 el mensaje vuelve a decir que la copia previa se puede borrar", SEED,
     '        print("Abrir la base para calcular esto pudo migrarla (init_db): la copia previa de "\n'
     '              "arriba es de ANTES de abrirla. Conservala.")',
     '        print("La copia previa de arriba se hizo antes de abrir la base; puedes borrarla.")',
     SEED_TESTS),
    ("Z09 la simulacion abre la base con una URI sin escapar", SEED,
     '        source = _read_only(db_path)\n        destination = sqlite3.connect(str(scratch))',
     '        source = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)\n'
     '        destination = sqlite3.connect(str(scratch))',
     SEED_TESTS),
    ("Z10 la comprobacion posterior a --apply abre la base con una URI sin escapar", SEED,
     '        check = _read_only(db_path)\n        print("integrity_check posterior:",',
     '        check = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)\n'
     '        print("integrity_check posterior:",',
     SEED_TESTS),
    ("Z11 --apply sobre una base que no existe la siembra en memoria", SEED,
     "    elif not args.apply:",
     "    elif True:",
     SEED_TESTS),
    ("Z12 un endpoint de nube sin clave cuenta como ruta utilizable", SEED,
     '               and (keyed is None or candidate.get("endpoint_id") in keyed)',
     "               and True",
     SEED_TESTS),
    ("Z13 la guarda de la siembra no mira que claves hay", SEED,
     '    usable = has_usable_route(rows[0]["candidates"], policy, keyed)',
     '    usable = has_usable_route(rows[0]["candidates"], policy)',
     SEED_TESTS),
    ("Z14 la simulacion no dice que fila se descarto", SEED,
     '    for note in rows[0]["dropped"]:',
     "    for note in []:",
     SEED_TESTS),
]


if __name__ == "__main__":
    sys.exit(campaign(MUTANTS, REPO, PY))
