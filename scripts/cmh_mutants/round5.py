"""Mutants for step 3.2: the zero-cost gate (D1) and every place it is applied.

Until now no versioned mutant touched src/cmh_cost_policy.py or the sites that
call it: rounds 2-4 mutate the router, the seed script and the workflow routes,
and the two mentions of "cmh_cost_policy" in them are test file names. The gate
was declared done on tests nobody had shown able to fail. Each mutant below
removes or weakens one rule; the tests that must fall are the ones that claim to
pin it.

Run it against an EXPORT of a commit, never the live tree. The runner refuses a
directory that contains .git (see _target.py).

    git archive <commit> | tar -x -C /tmp/export
    CMH_MUTANT_REPO=/tmp/export python scripts/cmh_mutants/round5.py
"""

import pathlib
import sys

from _target import resolve_repo
from _target import campaign

REPO = resolve_repo(pathlib.Path(__file__).resolve().parents[2])
PY = pathlib.Path(sys.executable)
if not PY.exists() or "python" not in PY.name.lower():
    PY = REPO.parent.parent / ".venv" / "Scripts" / "python.exe"

GATE_TESTS = ["tests/test_cmh_cost_policy.py", "tests/test_cmh_review_findings.py"]
SITE_TESTS = ["tests/test_cmh_cost_policy.py", "tests/test_cmh_review_findings.py",
              "tests/test_cmh_provider_router.py", "tests/test_cmh_control_routes.py",
              "tests/test_cmh_workflow_routes.py"]

POLICY = "src/cmh_cost_policy.py"
CONTROL = "routes/cmh_control_routes.py"
ROUTES = "routes/cmh_workflow_routes.py"
FLOW = "src/cmh_workflows.py"
ROUTER = "src/cmh_provider_router.py"

#: (name, file, text to replace, replacement, test modules that must fall)
MUTANTS = [
    # --- the rules of the gate itself ------------------------------------------
    ("CG01 Cerebras vuelve a FREE_HOSTS", POLICY,
     'FREE_HOSTS = frozenset({"api.groq.com", "openrouter.ai"})',
     'FREE_HOSTS = frozenset({"api.groq.com", "openrouter.ai", "api.cerebras.ai"})',
     GATE_TESTS),
    ("CG02 el host gratuito se reconoce por sufijo, no por igualdad", POLICY,
     "    if host not in FREE_HOSTS:\n        return False",
     "    if not any(host.endswith(free) for free in FREE_HOSTS):\n        return False",
     GATE_TESTS),
    ("CG03 OpenRouter deja de exigir el sufijo :free", POLICY,
     "        return name.endswith(_FREE_SUFFIX)",
     "        return True",
     GATE_TESTS),
    ("CG04 un modelo desconocido pasa en OpenRouter", POLICY,
     "        return name.endswith(_FREE_SUFFIX)",
     "        return not name or name.endswith(_FREE_SUFFIX)",
     GATE_TESTS),
    ("CG05 las etiquetas api y proxy dejan de descalificar", POLICY,
     "    if kind in _EXTERNAL_KINDS:\n        return False",
     "    if False:\n        return False",
     GATE_TESTS),
    ("CG06 la etiqueta local decide, no el host", POLICY,
     "    return is_reachable_without_leaving_the_network(\n"
     '        endpoint_host(_field(endpoint, "base_url")))',
     "    return kind == \"local\" or is_reachable_without_leaving_the_network(\n"
     '        endpoint_host(_field(endpoint, "base_url")))',
     GATE_TESTS),
    # CG07 and CG09 SURVIVED the first campaign (2026-09-29): nothing pinned the
    # 172.16/12 boundary, and dropping link-local changed nothing at all because
    # the code leaned on ipaddress.is_private, which already contains it. The gate
    # now names its networks and both are valid mutants.
    ("CG07 todo 172.x cuenta como red privada (172.16/12 se ensancha a 172/8)", POLICY,
     '    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",',
     '    "10.0.0.0/8", "172.0.0.0/8", "192.168.0.0/16",',
     GATE_TESTS),
    ("CG08 los nombres .local dejan de contar", POLICY,
     '    if name in _LOOPBACK_HOSTS or name.endswith(".local"):',
     "    if name in _LOOPBACK_HOSTS:",
     GATE_TESTS),
    ("CG09 link-local deja de contar", POLICY,
     '    "169.254.0.0/16", "fe80::/10",\n    "fc00::/7",',
     '    "fc00::/7",',
     GATE_TESTS),
    ("CG10 CMH_ZERO_COST vale falso por defecto", POLICY,
     'os.environ.get("CMH_ZERO_COST", "true")',
     'os.environ.get("CMH_ZERO_COST", "false")',
     GATE_TESTS),
    # Repointed on 2026-09-29: the disabled branch now logs before it returns.
    ("CG11 assert_zero_cost nunca lanza", POLICY,
     '    raise ZeroCostViolation(\n        f"Costo cero (D1): {describe(endpoint, model)} no es gratuito. "',
     '    return\n    raise ZeroCostViolation(\n        f"Costo cero (D1): {describe(endpoint, model)} no es gratuito. "',
     GATE_TESTS),
    ("CG11b la bandera se ignora y la compuerta lanza siempre", POLICY,
     "    if not enforced():\n        logger.warning(",
     "    if False:\n        logger.warning(",
     GATE_TESTS),
    ("CG12 endpoint_for_url acepta una fila de otro host", POLICY,
     '    if row is not None and endpoint_host(getattr(row, "base_url", "")) != endpoint_host(endpoint_url):\n'
     "        return None",
     "    if False:\n        return None",
     GATE_TESTS),
    ("CG13 10.0.0.0/8 deja de ser red privada", POLICY,
     '    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",',
     '    "172.16.0.0/12", "192.168.0.0/16",',
     GATE_TESTS),
    ("CG14 192.168.0.0/16 deja de ser red privada", POLICY,
     '    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",',
     '    "10.0.0.0/8", "172.16.0.0/12",',
     GATE_TESTS),
    ("CG15 el rango unique-local de IPv6 deja de contar", POLICY,
     '    "169.254.0.0/16", "fe80::/10",\n    "fc00::/7",\n))',
     '    "169.254.0.0/16", "fe80::/10",\n))',
     GATE_TESTS),
    ("CG16 loopback deja de ser local", POLICY,
     "    return bool(address.is_loopback or any(",
     "    return bool(any(",
     GATE_TESTS),

    # --- added on 2026-09-29 after the independent review of revision-fase1-r6 ------
    # CG17-CG20 are mutants the review reported as SURVIVING r6 (SEG-06, SEG-07,
    # PRU-F25, PRU-F26): the boundary cases they needed were not in the tests.
    # CG21-CG30 guard the corrections of that same review (https, the flag, the
    # redaction). Their counts are in the campaign output, not in this comment.
    ("CG17 el sufijo ':free' pierde los dos puntos", POLICY,
     '_FREE_SUFFIX = ":free"',
     '_FREE_SUFFIX = "free"',
     GATE_TESTS),
    ("CG18 un host vacio cuenta como local", POLICY,
     "    if not name:\n        return False\n    if name in _LOOPBACK_HOSTS",
     "    if not name:\n        return True\n    if name in _LOOPBACK_HOSTS",
     GATE_TESTS),
    ("CG19 fe80::/10 se estrecha a fe80::/16", POLICY,
     '    "169.254.0.0/16", "fe80::/10",\n    "fc00::/7",',
     '    "169.254.0.0/16", "fe80::/16",\n    "fc00::/7",',
     GATE_TESTS),
    ("CG20 fc00::/7 se estrecha a fd00::/8", POLICY,
     '    "fc00::/7",\n))',
     '    "fd00::/8",\n))',
     GATE_TESTS),
    ("CG21 un host gratuito por http sigue pasando", POLICY,
     '    if endpoint_scheme(base_url) != "https":\n        return False',
     "    if False:\n        return False",
     GATE_TESTS),
    ("CG22 CMH_ZERO_COST vuelve a fallar abierto", POLICY,
     '    return os.environ.get("CMH_ZERO_COST", "true").strip().lower() not in _OFF',
     '    return os.environ.get("CMH_ZERO_COST", "true").strip().lower() in {"1", "true", "yes", "on"}',
     GATE_TESTS),
    ("CG23 describe imprime la URL cruda", POLICY,
     '    base_url = redact_url(_field(endpoint, "base_url")) or "sin URL"',
     '    base_url = _field(endpoint, "base_url") or "sin URL"',
     GATE_TESTS),
    ("CG24 redact_url conserva usuario y clave", POLICY,
     '    cleaned = head + authority.rsplit("@", 1)[-1] + tail',
     "    cleaned = head + authority + tail",
     GATE_TESTS),
    ("CG25 redact_url conserva la query", POLICY,
     '        return urlunparse((parts.scheme, parts.netloc, parts.path, "", "", ""))',
     '        return urlunparse((parts.scheme, parts.netloc, parts.path, "", parts.query, ""))',
     GATE_TESTS),
    ("CG26 apagar la compuerta ya no deja rastro en el log", POLICY,
     '        logger.warning("Costo cero (D1) DESACTIVADO por CMH_ZERO_COST: se deja pasar %s",\n'
     "                       describe(endpoint, model))",
     "        pass",
     GATE_TESTS),
    ("CG27 el evento zero_cost_blocked lleva la URL cruda", FLOW,
     '                record("zero_cost_blocked", endpoint_url=redact_url(url), candidate_model=model)',
     '                record("zero_cost_blocked", endpoint_url=url, candidate_model=model)',
     GATE_TESTS),
    ("CG28 redact_url conserva el fragmento", POLICY,
     '        return urlunparse((parts.scheme, parts.netloc, parts.path, "", "", ""))',
     '        return urlunparse((parts.scheme, parts.netloc, parts.path, "", "", parts.fragment))',
     GATE_TESTS),
    ("CG29 una URL que no se interpreta se devuelve tal cual", POLICY,
     '        return "URL no interpretable"',
     "        return base_url",
     GATE_TESTS),
    ("CG30 el esquema se da siempre por https", POLICY,
     '        return urlparse(base_url or "").scheme',
     '        return "https"',
     GATE_TESTS),

    # --- every site where the gate is applied ----------------------------------
    ("SI01 enlazar agente y tarea deja de pasar por la compuerta", CONTROL,
     "        assert_zero_cost_url(db, task.endpoint_url, model, owner)",
     "        pass",
     SITE_TESTS),
    ("SI02 crear la tarea gemela deja de pasar por la compuerta", CONTROL,
     "            assert_zero_cost_url(db, endpoint_url, model, owner)",
     "            pass",
     SITE_TESTS),
    ("SI03 crear la definicion deja de pasar por la compuerta", ROUTES,
     "        try:\n            assert_zero_cost_url(db, task.endpoint_url, agent.model, owner)",
     "        try:\n            pass",
     SITE_TESTS),
    ("SI04 congelar el run deja de pasar por la compuerta", ROUTES,
     "    try:\n        assert_zero_cost_url(db, task.endpoint_url, agent.model, owner)\n    except",
     "    try:\n        pass\n    except",
     SITE_TESTS),
    ("SI05 un candidato de pago ya no se descarta al ejecutar", FLOW,
     "            if not is_zero_cost_endpoint(endpoint, model):",
     "            if False:",
     SITE_TESTS),
    ("SI06 sin candidato gratuito el paso cae a los de pago", FLOW,
     "        if enforced():\n            raise ZeroCostViolation(",
     "        if False:\n            raise ZeroCostViolation(",
     SITE_TESTS),
    ("SI07 el router lista un proveedor de nube sin pasar la compuerta", ROUTER,
     '                if not is_zero_cost_endpoint(row, model):\n'
     '                    _note_dropped(dropped, row, host, "cost_gate")\n'
     '                    continue',
     '                if False:\n'
     '                    _note_dropped(dropped, row, host, "cost_gate")\n'
     '                    continue',
     SITE_TESTS),
    ("SI08 el router lista como local cualquier endpoint habilitado", ROUTER,
     "        if not is_local_endpoint(row):\n            continue",
     "        if False:\n            continue",
     SITE_TESTS),
]


if __name__ == "__main__":
    sys.exit(campaign(MUTANTS, REPO, PY))
