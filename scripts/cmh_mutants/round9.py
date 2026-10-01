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
STEP_TESTS = ["tests/test_cmh_step_provider_failures.py"]

POLICY = "src/cmh_cost_policy.py"
WF_ROUTES = "routes/cmh_workflow_routes.py"
ENDPOINT_RESOLVER = "src/endpoint_resolver.py"
ROUTER = "src/cmh_provider_router.py"
MODEL_ROUTES = "routes/model_routes.py"
LLM_CORE = "src/llm_core.py"
SEED = "scripts/cmh_seed_agents.py"
SCHEDULER = "src/task_scheduler.py"

#: (name, file, text to replace, replacement, test modules that must fall)
MUTANTS = [
    # --- what a run freezes carries no credential ----------------------------------
    ("F01 has_userinfo nunca ve una credencial", POLICY,
     "        return bool(parsed.username or parsed.password)",
     "        return False",
     POLICY_TESTS + FREEZE_TESTS),
    ("F02 has_userinfo busca la arroba en toda la URL y no solo en la autoridad", POLICY,
     "        return bool(parsed.username or parsed.password)",
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
     "    if not base:\n        return\n    from src.cmh_cost_policy import carries_unliftable_credential, has_userinfo",
     "    from src.cmh_cost_policy import carries_unliftable_credential, has_userinfo",
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
    ("Z11 --apply sobre una base que no existe se siembra en memoria (ninguna rama de memoria excluye ya a --apply)", SEED,
     ('    if args.apply:\n'
     '        if db_path.is_file():\n'
     '            backup_database(db_path, "before-seed-agents")\n'
     '        elif not args.allow_pending:\n'
     '            # The candidates come from this database: with no file there are none, and opening\n'
     '            # core.database below would CREATE an empty one at this path (a typo in DATABASE_URL\n'
     '            # left it in the wrong place and the message talked about a copy that never existed).\n'
     '            print(f"La base real ({db_path}) no existe: no hay endpoints que sembrar y abrirla la "\n'
     '                  f"crearia vacia. No se sembro nada.")\n'
     '            print("Revisa DATABASE_URL, o usa --allow-pending para crearla y sembrar igual.")\n'
     '            return 2\n'
     '    elif db_path.is_file():\n'
     '        scratch = pathlib.Path(tempfile.gettempdir()) / f"cmh-seed-dryrun-{os.getpid()}.db"\n'
     "        _SCRATCH[0] = scratch   # removed in main()'s finally, however this ends\n"
     '        # mode=ro is defence, not a measurable guarantee: SQLite happily opens a\n'
     '        # read-only file read-write until something writes, so a mutant that\n'
     '        # drops it has no observable effect here. Kept, and declared as\n'
     '        # unmeasured rather than covered by a test that cannot fail.\n'
     '        source = _read_only(db_path)\n'
     '        destination = sqlite3.connect(str(scratch))\n'
     '        source.backup(destination)\n'
     '        destination.close()\n'
     '        source.close()\n'
     '        os.environ["DATABASE_URL"] = f"sqlite:///{scratch.as_posix()}"\n'
     '        print(f"SIMULACION sobre una copia desechable: {scratch}")\n'
     '        print(f"La base real ({db_path}) solo se lee para copiarla; no se migra.")\n'
     '    elif not args.apply:\n'),
     ('    if args.apply and db_path.is_file():\n'
     '        backup_database(db_path, "before-seed-agents")\n'
     '    elif db_path.is_file():\n'
     '        scratch = pathlib.Path(tempfile.gettempdir()) / f"cmh-seed-dryrun-{os.getpid()}.db"\n'
     "        _SCRATCH[0] = scratch   # removed in main()'s finally, however this ends\n"
     '        # mode=ro is defence, not a measurable guarantee: SQLite happily opens a\n'
     '        # read-only file read-write until something writes, so a mutant that\n'
     '        # drops it has no observable effect here. Kept, and declared as\n'
     '        # unmeasured rather than covered by a test that cannot fail.\n'
     '        source = _read_only(db_path)\n'
     '        destination = sqlite3.connect(str(scratch))\n'
     '        source.backup(destination)\n'
     '        destination.close()\n'
     '        source.close()\n'
     '        os.environ["DATABASE_URL"] = f"sqlite:///{scratch.as_posix()}"\n'
     '        print(f"SIMULACION sobre una copia desechable: {scratch}")\n'
     '        print(f"La base real ({db_path}) solo se lee para copiarla; no se migra.")\n'
     '    elif True:\n'),
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
    # --- r9: one detector of credentials, a port that is not a 500, messages that are true -----
    ("F09 has_userinfo cuenta un userinfo vacio como credencial", POLICY,
     "        return bool(parsed.username or parsed.password)",
     '        return "@" in parsed.netloc',
     POLICY_TESTS),
    ("F10 has_userinfo exige usuario Y clave", POLICY,
     "        return bool(parsed.username or parsed.password)",
     "        return bool(parsed.username and parsed.password)",
     POLICY_TESTS),
    ("F11 una URL ilegible cuenta como URL con credenciales", POLICY,
     "        return bool(parsed.username or parsed.password)\n    except ValueError:\n        return False",
     "        return bool(parsed.username or parsed.password)\n    except ValueError:\n        return True",
     POLICY_TESTS),
    ("P12 split_url_credentials vuelve a dejar escapar el puerto fuera de rango", ENDPOINT_RESOLVER,
     "    except ValueError:\n        # An out-of-range port leaves nothing",
     "    except KeyError:\n        # An out-of-range port leaves nothing",
     PATCH_TESTS),
    ("P13 el POST guarda una credencial que no pudo separar", MODEL_ROUTES,
     "        if has_userinfo(base_url) or carries_unliftable_credential(base_url):\n            # A credential that could not be lifted",
     "        if False:\n            # A credential that could not be lifted",
     PATCH_TESTS),
    ("P14 el PATCH guarda una credencial que no pudo separar", MODEL_ROUTES,
     '    if has_userinfo(base) or carries_unliftable_credential(base):\n        raise HTTPException(400, "La URL lleva',
     '    if False:\n        raise HTTPException(400, "La URL lleva',
     PATCH_TESTS),
    ("P15 la respuesta del PATCH dice siempre is_enabled verdadero", MODEL_ROUTES,
     '                "is_enabled": ep.is_enabled,',
     '                "is_enabled": True,',
     PATCH_TESTS),
    ("P16 la respuesta del PATCH omite supports_tools", MODEL_ROUTES,
     '                "supports_tools": ep.supports_tools,\n',
     "",
     PATCH_TESTS),
    ("P17 build_headers deja pasar como Basic cualquier valor que empiece por Basic", ENDPOINT_RESOLVER,
     'api_key if api_key.startswith("Basic ")',
     'api_key if api_key.startswith("Basic")',
     PATCH_TESTS),
    ("P18 build_headers deja pasar como Basic tambien el esquema en minusculas", ENDPOINT_RESOLVER,
     'api_key if api_key.startswith("Basic ")',
     'api_key if api_key.lower().startswith("basic ")',
     PATCH_TESTS),
    ("W1 create_run deja pasar una URL de tarea con credenciales", WF_ROUTES,
     '    if has_userinfo(task.endpoint_url or ""):',
     "    if False:",
     FREEZE_TESTS),
    ("W2 el rechazo de una fila con credenciales ya no nombra el PATCH", WF_ROUTES,
     'f"lleva credenciales embebidas en su URL. Editalo (un PATCH "',
     'f"lleva credenciales embebidas en su URL. Editalo (un GET "',
     FREEZE_TESTS),
    ("W3 el rechazo vuelve a decir que registrar otro endpoint basta", WF_ROUTES,
     'f"eliminalo o deshabilitalo: registrar otro nuevo no basta, "',
     'f"eliminalo o deshabilitalo: registrar otro nuevo basta, "',
     FREEZE_TESTS),
    ("W4 las notas de descarte se repiten una vez por paso", WF_ROUTES,
     "        notes.extend(n for n in dropped if n not in notes)",
     "        notes.extend(dropped)",
     FREEZE_TESTS),
    ("W5 solo se dice el descarte por http, no el de un modelo que no es :free", ROUTER,
     '                    _note_dropped(dropped, row, host, "cost_gate")\n'
     '                    continue\n'
     '                candidates.append(',
     '                    if str(row.base_url).startswith("http:"):\n'
     '                        _note_dropped(dropped, row, host, "cost_gate")\n'
     '                    continue\n'
     '                candidates.append(',
     FREEZE_TESTS),
    ("W6 el rechazo de la URL de la tarea vuelve a hablar de 'la URL del endpoint'", WF_ROUTES,
     'la URL de la tarea del agente lleva "',
     'la URL del endpoint lleva "',
     FREEZE_TESTS),
    # --- r10: a credential urlparse cannot see, and the detector's boundaries -----------------
    ("P19 el POST solo rechaza lo que urlparse ve como credencial", MODEL_ROUTES,
     "        if has_userinfo(base_url) or carries_unliftable_credential(base_url):\n            # A credential that could not be lifted",
     "        if has_userinfo(base_url):\n            # A credential that could not be lifted",
     PATCH_TESTS),
    ("P20 el PATCH solo rechaza lo que urlparse ve como credencial", MODEL_ROUTES,
     '    if has_userinfo(base) or carries_unliftable_credential(base):\n        raise HTTPException(400, "La URL lleva',
     '    if has_userinfo(base):\n        raise HTTPException(400, "La URL lleva',
     PATCH_TESTS),
    ("F12 el detector mira todo el texto y no solo la autoridad", POLICY,
     '    return "@" in _split_authority(base_url or "")[1]',
     '    return "@" in (base_url or "")',
     POLICY_TESTS),
    ("F13 el detector no ve nunca una credencial que quedo", POLICY,
     '    return "@" in _split_authority(base_url or "")[1]',
     "    return False",
     POLICY_TESTS),
    ("F14 la autoridad ya no termina en un '?'", POLICY,
     '    stops = [i for i in (rest.find("/"), rest.find("?"), rest.find("#")) if i >= 0]',
     '    stops = [i for i in (rest.find("/"), rest.find("#")) if i >= 0]',
     POLICY_TESTS),
    ("F15 la autoridad ya no termina en un '#'", POLICY,
     '    stops = [i for i in (rest.find("/"), rest.find("?"), rest.find("#")) if i >= 0]',
     '    stops = [i for i in (rest.find("/"), rest.find("?")) if i >= 0]',
     POLICY_TESTS),
    ("F16 la autoridad ya no termina en una '/'", POLICY,
     '    stops = [i for i in (rest.find("/"), rest.find("?"), rest.find("#")) if i >= 0]',
     '    stops = [i for i in (rest.find("?"), rest.find("#")) if i >= 0]',
     POLICY_TESTS),
    ("F17 redact_url deja entera una URL sin esquema", POLICY,
     '    head, authority, tail = _split_authority(base_url)\n    cleaned = head + authority.rsplit("@", 1)[-1] + tail',
     '    head, authority, tail = _split_authority(base_url)\n    cleaned = (head + authority.rsplit("@", 1)[-1] + tail) if head else base_url',
     POLICY_TESTS),
    ("W7 el rechazo de una fila con credenciales ya no nombra eliminar ni deshabilitar", WF_ROUTES,
     'f"eliminalo o deshabilitalo: registrar otro nuevo no basta, "',
     'f"registrar otro nuevo no basta, "',
     FREEZE_TESTS),
    ("W8 el rechazo ya no avisa de que con un puerto fuera de rango el PATCH la rechaza", WF_ROUTES,
     'f"porque este sigue habilitado. Si la URL tiene un puerto "\n'
     '                                     f"fuera de rango o no se puede leer, el PATCH la rechaza: "\n'
     '                                     f"corrigela a mano. Aqui no se recorta en silencio.")',
     'f"porque este sigue habilitado. Aqui no se recorta en silencio.")',
     FREEZE_TESTS),
    # --- the seed script, r9 --------------------------------------------------------
    ("Z15 --apply sobre una base que no existe la abre (y la crea vacia) antes de negarse", SEED,
     "        elif not args.allow_pending:",
     "        elif False:",
     SEED_TESTS),
    ("Z16 una clave de solo espacios cuenta como clave registrada", SEED,
     '                 if str(getattr(ep, "api_key", None) or "").strip()}',
     '                 if str(getattr(ep, "api_key", None) or "")}',
     SEED_TESTS),
    ("Z17 el aviso de una fila con credenciales vuelve a decir que registrar otra basta", SEED,
     '"no basta, la fila vieja sigue habilitada"),',
     '"basta"),',
     SEED_TESTS),
    ("Z18 el aviso de una fila con credenciales ya no nombra el PATCH", SEED,
     "editalo (un PATCH con esa misma URL pasa las ",
     "editalo (con esa misma URL pasa las ",
     SEED_TESTS),
    ("Z19 el plan vuelve a decir que no hay endpoint gratuito cuando solo hay OpenRouter", SEED,
     "        elif registered_hosts & _free_hosts():",
     "        elif False:",
     SEED_TESTS),
    ("Z20 el plan dice que OpenRouter no cuenta aunque no haya nada registrado", SEED,
     "        elif registered_hosts & _free_hosts():",
     "        elif True:",
     SEED_TESTS),
    # --- the header a workflow step REALLY sends (r9) -------------------------------
    # task_scheduler.py builds it twice with the same line: in _run_agent_loop (what every
    # workflow step runs) and in _execute_research_task (Odysseus's own research task, which
    # no CMH flow calls). Only the first is reachable from call_model; the pattern carries
    # the line that follows it so that it names one site and not both.
    ("P10 el ejecutor del paso no pone la cabecera Authorization de la fila", SCHEDULER,
     "                    headers = build_headers(ep.api_key, normalize_base(ep.base_url))\n"
     "            finally:",
     "                    headers = {}\n"
     "            finally:",
     STEP_TESTS),
    ("P11 el ejecutor del paso envia siempre Bearer, tambien un Basic ya armado", SCHEDULER,
     "                    headers = build_headers(ep.api_key, normalize_base(ep.base_url))\n"
     "            finally:",
     '                    headers = {"Authorization": "Bearer " + str(ep.api_key)}\n'
     "            finally:",
     STEP_TESTS),
]


if __name__ == "__main__":
    sys.exit(campaign(MUTANTS, REPO, PY))
