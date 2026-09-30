"""Mutants for the fixes of the 2026-09-29 audit (step 3.3b and what surrounds it).

Each capacity adds its mutants here, in the same commit as its fix, and names the
test module that must fall. A mutant that does not fall is a test that cannot
fail: that is the only reason this file exists.

Run it against an EXPORT of a commit, never the live tree. The runner refuses a
directory that contains .git (see _target.py).

    git archive <commit> | tar -x -C /tmp/export
    CMH_MUTANT_REPO=/tmp/export python scripts/cmh_mutants/round4.py

A mutant whose pattern stops matching is reported as NO APLICABLE and counted
separately, so an obsolete pattern cannot quietly leave the denominator.
"""

import pathlib
import sys

from _target import resolve_repo
from _target import campaign

REPO = resolve_repo(pathlib.Path(__file__).resolve().parents[2])
PY = pathlib.Path(sys.executable)
if not PY.exists() or "python" not in PY.name.lower():
    PY = REPO.parent.parent / ".venv" / "Scripts" / "python.exe"

TARGET_TESTS = ["tests/test_cmh_mutant_target.py"]
CAMPAIGN_TESTS = ["tests/test_cmh_mutant_campaign.py"]
STEP_FAILURE_TESTS = ["tests/test_cmh_step_provider_failures.py"]
LOOP_TESTS = ["tests/test_cmh_restricted_loop.py"]
DISCOVERY_TESTS = ["tests/test_cmh_provider_discovery.py"]

TARGET = "scripts/cmh_mutants/_target.py"
ROUND2 = "scripts/cmh_mutants/round2.py"
SCHED = "src/task_scheduler.py"
ROUTER = "src/cmh_provider_router.py"
ROUTES = "routes/cmh_workflow_routes.py"
FLOW = "src/cmh_workflows.py"

#: (name, file, text to replace, replacement, test modules that must fall)
MUTANTS = [
    # --- the campaign runners refuse the live tree -----------------------------
    # T01 was repointed on 2026-09-29 when the check moved into assert_not_live.
    ("T01 assert_not_live deja de mirar .git", TARGET,
     '    if (pathlib.Path(repo) / ".git").exists() and os.environ.get("CMH_MUTANT_ALLOW_LIVE") != "1":',
     '    if False and (pathlib.Path(repo) / ".git").exists():',
     TARGET_TESTS + CAMPAIGN_TESTS),
    ("T02 resolve_repo ignora CMH_MUTANT_REPO", TARGET,
     '    override = os.environ.get("CMH_MUTANT_REPO")',
     '    override = None',
     TARGET_TESTS),
    ("T03 round2 vuelve a fijar su propia ruta sin pasar por resolve_repo", ROUND2,
     "REPO = resolve_repo(pathlib.Path(__file__).resolve().parents[2])",
     "REPO = pathlib.Path(__file__).resolve().parents[2]",
     TARGET_TESTS),

    # --- the loop itself: what the review of 2026-09-29 found it could not tell ---
    ("T04 campaign deja de correr la linea base", TARGET,
     "    if baseline.returncode != 0:",
     "    if False:",
     CAMPAIGN_TESTS),
    ("T05 campaign deja de rechazar el arbol vivo por su cuenta", TARGET,
     "    assert_not_live(repo)\n    root = pathlib.Path(repo).resolve()",
     "    root = pathlib.Path(repo).resolve()",
     CAMPAIGN_TESTS),
    ("T06 el codigo de salida siempre es cero", TARGET,
     "    return 0 if not (survived or skipped or invalid) and final.returncode == 0 else 1",
     "    return 0",
     CAMPAIGN_TESTS),
    ("T07 el archivo mutado no se restaura", TARGET,
     "            path.write_bytes(raw)\n            if path.read_bytes() != raw:",
     "            pass\n            if False:",
     CAMPAIGN_TESTS),
    ("T08 la campana deja de normalizar CRLF antes de buscar el patron", TARGET,
     '        text = raw.decode("utf-8").replace("\\r\\n", "\\n")',
     '        text = raw.decode("utf-8")',
     CAMPAIGN_TESTS),
    ("T09 un mutante que no cambia nada deja de ser INVALIDO", TARGET,
     "        if mutated == text:",
     "        if False:",
     CAMPAIGN_TESTS),
    ("T10 failed_id corta en el ultimo :: y no en el primero", TARGET,
     '    return body.split("::", 1)[1] if "::" in body else body',
     '    return body.rsplit("::", 1)[1] if "::" in body else body',
     CAMPAIGN_TESTS),
    ("T11 el arbol final restaurado deja de exigirse verde", TARGET,
     "    return 0 if not (survived or skipped or invalid) and final.returncode == 0 else 1",
     "    return 0 if not (survived or skipped or invalid) else 1",
     CAMPAIGN_TESTS),

    # --- 3.3b.1 the provider's status survives the trip from stream to router ---
    ("S01 el paso vuelve a lanzar un RuntimeError sin status", SCHED,
     "                raise RestrictedStreamError(_stream_error_status(event_str))",
     '                raise RuntimeError("Restricted task model stream failed")',
     STEP_FAILURE_TESTS),
    ("S02 el status del evento de error se descarta", SCHED,
     "        return status if isinstance(status, int) and not isinstance(status, bool) else None",
     "        return None",
     STEP_FAILURE_TESTS),
    ("S03 cualquier status cambia de proveedor, tambien un 401", ROUTER,
     "    if status in FALLBACK_STATUS or (isinstance(status, int) and 500 <= status <= 599):",
     "    if isinstance(status, int):",
     STEP_FAILURE_TESTS),

    # --- 3.3b.2 OpenRouter's model is discovered and frozen with the list ------
    ("D01 create_run deja de descubrir el modelo", ROUTES,
     "                await discover_free_models(db, owner) if wants_cloud else ({}, []))",
     "                ({}, []))",
     DISCOVERY_TESTS),
    ("D02 _snapshot no pasa lo descubierto al router", ROUTES,
     "    candidates = resolve_candidates(db, policy, owner, discovered=discovered, dropped=dropped)",
     "    candidates = resolve_candidates(db, policy, owner, dropped=dropped)",
     DISCOVERY_TESTS),
    ("D03 el router ignora el modelo descubierto", ROUTER,
     '            model = provider.get("model") or (discovered or {}).get(host)',
     '            model = provider.get("model")',
     DISCOVERY_TESTS),
    ("D04 el modelo descubierto pisa al escrito en el config", ROUTER,
     '            model = provider.get("model") or (discovered or {}).get(host)',
     '            model = (discovered or {}).get(host) or provider.get("model")',
     DISCOVERY_TESTS),
    ("D05 se descubre aunque el config ya fije el modelo", ROUTER,
     '        if provider.get("model") or rule is None:',
     '        if rule is None:',
     DISCOVERY_TESTS),
    ("D06 una lista vacia de la cuenta se amplia al catalogo general", ROUTER,
     "    if status == 404:",
     "    if status == 404 or (status == 200 and rule(payload) is None):",
     DISCOVERY_TESTS),
    ("D07 se pregunta primero al catalogo general", ROUTER,
     '    payload, reason, status = await _get_json(client, models_url + "/user", headers,\n'
     '                                              knobs["timeout_s"])\n'
     '    source, note = "models/user", None',
     '    payload, reason, status = await _get_json(client, models_url, headers,\n'
     '                                              knobs["timeout_s"])\n'
     '    source, note = "models", None',
     DISCOVERY_TESTS),
    ("D08 la consulta va sin la clave de la cuenta", ROUTER,
     "    headers = build_headers(api_key, base)",
     "    headers = {}",
     DISCOVERY_TESTS),
    ("D09 la cache por TTL se ignora", ROUTER,
     '        if cached and cached["expires"] > moment:',
     '        if False:',
     DISCOVERY_TESTS),
    ("D10 el run no registra los eventos de descubrimiento", ROUTES,
     "            for note in discovery_notes:",
     "            for note in []:",
     DISCOVERY_TESTS),
    ("D11 se consulta el catalogo aunque todos los pasos sean local-only", ROUTES,
     "            discovered, discovery_notes = (\n"
     "                await discover_free_models(db, owner) if wants_cloud else ({}, []))",
     "            discovered, discovery_notes = await discover_free_models(db, owner)",
     DISCOVERY_TESTS),
    ("D12 la condicion de 'algun paso admite la nube' se invierte", ROUTES,
     '            wants_cloud = any(resolve_policy(spec, agents.get(spec["agent_id"])) != LOCAL_ONLY',
     '            wants_cloud = any(resolve_policy(spec, agents.get(spec["agent_id"])) == LOCAL_ONLY',
     DISCOVERY_TESTS),

    # --- discovery hardening (review of 2026-09-29: COR-C3, C4, HON-F2, PRU-F17..F21) ---
    # D06, D07 and D08 were repointed the same day: the rewrite of _discover_one
    # removed the loop they mutated. What they claim is unchanged.
    ("D13 el descubrimiento deja de exigir la clave registrada", ROUTER,
     '    if not api_key:\n        return {"model": None, "source": None, "reason": "no api key"}',
     "    if False:\n        return {\"model\": None, \"source\": None, \"reason\": \"no api key\"}",
     DISCOVERY_TESTS),
    ("D14 el descubrimiento manda la clave por http", ROUTER,
     '    if endpoint_scheme(getattr(row, "base_url", "")) != "https":',
     "    if False:",
     DISCOVERY_TESTS),
    ("D15 cualquier fallo de la lista de la cuenta amplia al listado general", ROUTER,
     "    if status == 404:",
     "    if status != 200:",
     DISCOVERY_TESTS),
    ("D16 un 4xx o 5xx de la lista de la cuenta amplia al listado general", ROUTER,
     "    if status == 404:",
     "    if status is not None and status >= 400:",
     DISCOVERY_TESTS),
    ("D17 httpx.InvalidURL se escapa del descubrimiento", ROUTER,
     '    except httpx.InvalidURL:\n        return None, "invalid url", None',
     '    except KeyError:\n        return None, "invalid url", None',
     DISCOVERY_TESTS),
    ("D18 una base_url mal formada hace fallar la creacion del run", ROUTER,
     '    except ValueError:\n        return {"model": None, "source": None, "reason": "invalid url"}',
     '    except KeyError:\n        return {"model": None, "source": None, "reason": "invalid url"}',
     DISCOVERY_TESTS),
    ("D19 un context_length infinito rompe la eleccion", ROUTER,
     "        except (TypeError, ValueError, OverflowError):",
     "        except (TypeError, ValueError):",
     DISCOVERY_TESTS),
    ("D20 una carga que no es una lista se recorre igual", ROUTER,
     "    if not isinstance(entries, list):\n        return None",
     "    if False:\n        return None",
     DISCOVERY_TESTS),
    ("D21 una regla que lanza excepcion mata la creacion del run", ROUTER,
     "    except Exception as exc:  # a rule is code we wrote, a payload is not",
     "    except KeyError as exc:  # a rule is code we wrote, a payload is not",
     DISCOVERY_TESTS),
    ("D22 un booleano vale como valor de TTL o de timeout", ROUTER,
     "        valid = (isinstance(value, (int, float)) and not isinstance(value, bool)",
     "        valid = (isinstance(value, (int, float))",
     DISCOVERY_TESTS),
    ("D23 cero o un negativo valen como TTL o timeout", ROUTER,
     "                 and math.isfinite(value) and value > 0)",
     "                 and math.isfinite(value))",
     DISCOVERY_TESTS),
    ("D24 un valor infinito vale como TTL o timeout", ROUTER,
     "                 and math.isfinite(value) and value > 0)",
     "                 and value > 0)",
     DISCOVERY_TESTS),
    ("D25 la cache ignora la clave de la cuenta", ROUTER,
     '            hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16])',
     '            "")',
     DISCOVERY_TESTS),
    ("D26 la cache ignora la URL de la fila", ROUTER,
     '    return (getattr(row, "id", None), getattr(row, "base_url", None),\n            hashlib',
     '    return (getattr(row, "id", None),\n            hashlib',
     DISCOVERY_TESTS),
    ("D27 un fallo deja de recordarse", ROUTER,
     '            ttl = knobs["failure_ttl_s"]',
     "            ttl = 0",
     DISCOVERY_TESTS),
    ("D28 una eleccion del listado sin filtrar dura lo que una filtrada", ROUTER,
     '            ttl = knobs["ttl_s"] if result["source"] == "models/user" else knobs["unfiltered_ttl_s"]',
     '            ttl = knobs["ttl_s"]',
     DISCOVERY_TESTS),
    ("D29 el tiempo total del descubrimiento deja de acotarse", ROUTER,
     "            result = await asyncio.wait_for(_discover_one(row, rule, knobs),\n"
     '                                            timeout=knobs["timeout_s"])',
     "            result = await _discover_one(row, rule, knobs)",
     DISCOVERY_TESTS),
    ("D30 la primera consulta va sin timeout", ROUTER,
     '    payload, reason, status = await _get_json(client, models_url + "/user", headers,\n'
     '                                              knobs["timeout_s"])',
     '    payload, reason, status = await _get_json(client, models_url + "/user", headers, None)',
     DISCOVERY_TESTS),
    ("D31 la segunda consulta va sin timeout", ROUTER,
     '        payload, reason, status = await _get_json(client, models_url, headers, knobs["timeout_s"])',
     "        payload, reason, status = await _get_json(client, models_url, headers, None)",
     DISCOVERY_TESTS),
    ("D32 el config deja de fijar los valores de TTL y timeout", ROUTER,
     "        knobs[name] = float(value)",
     "        pass",
     DISCOVERY_TESTS),
    ("D33 la nota no dice por que se uso el listado general", ROUTER,
     '        note = "models/user no existe (404): se uso el listado general, sin el filtro de la cuenta"',
     "        note = None",
     DISCOVERY_TESTS),

    # --- 3.3b.3 the local candidate has its own identifier ----------------------
    # (R12 of round3, repointed, covers _snapshot handing the agent's model back.)
    ("L01 el identificador local del config se ignora", ROUTER,
     "        model = local_model or configured_local or _first_cached_model(row)",
     "        model = local_model or _first_cached_model(row)",
     DISCOVERY_TESTS),
    ("L02 el config pisa al local_model explicito", ROUTER,
     "        model = local_model or configured_local or _first_cached_model(row)",
     "        model = configured_local or local_model or _first_cached_model(row)",
     DISCOVERY_TESTS),

    # --- 3.3b.4 quota counts what the step spent: requests, tokens, refusals ----
    ("Q01 el evento de metricas ya no carga la cuota", FLOW,
     '            if kind == "model_metrics":',
     '            if False:',
     STEP_FAILURE_TESTS),
    ("Q02 se cargan las peticiones pero no los tokens", FLOW,
     "                       tokens_in=tokens_in, tokens_out=tokens_out)",
     "                       tokens_in=0, tokens_out=0)",
     STEP_FAILURE_TESTS),
    ("Q03 un paso de varias rondas cuenta una sola peticion", FLOW,
     '                charge(_candidate, requests=max(1, int(metrics.get("rounds") or 1)),',
     '                charge(_candidate, requests=1,',
     STEP_FAILURE_TESTS),
    ("Q04 el intento rechazado deja de cobrarse", FLOW,
     '            if not charged["any"]:',
     '            if False:',
     STEP_FAILURE_TESTS),
    ("Q05 el intento que fallo despues de informar se cobra dos veces", FLOW,
     '            if not charged["any"]:',
     '            if True:',
     STEP_FAILURE_TESTS),
    ("Q06 un fallo al escribir la cuota vuelve a matar el paso", FLOW,
     '        except Exception as exc:\n            logger.exception("Could not charge quota',
     '        except KeyError as exc:\n            logger.exception("Could not charge quota',
     STEP_FAILURE_TESTS),
    ("Q07 el intento se ejecuta sin el canal que carga la cuota", FLOW,
     "            output = await _run_one_candidate(config, candidate, prompt, charging)",
     "            output = await _run_one_candidate(config, candidate, prompt, record)",
     STEP_FAILURE_TESTS),
    ("Q08 el planificador deja de reenviar cuantas rondas cubren los totales", SCHED,
     '                            safe_metrics["rounds"] = len(buckets)',
     '                            safe_metrics["rounds"] = 0',
     STEP_FAILURE_TESTS),

    # --- 3.3b.4b an attempt that dies mid-run is charged what it spent ----------
    # (review of 2026-09-29: COR-C1, PRU-F23, PRU-F24)
    ("Q09 el planificador ignora lo que un intento fallido gasto antes de morir", SCHED,
     '                    elif kind in ("metrics", "agent_terminal"):',
     '                    elif kind == "metrics":',
     STEP_FAILURE_TESTS + LOOP_TESTS),
    ("Q10 un intento fallido cuenta solo las rondas que completo", SCHED,
     '                            safe_metrics["rounds"] = (len(texts) if isinstance(texts, list) and texts\n'
     '                                                      else safe_metrics.get("rounds", 0) + 1)',
     '                            safe_metrics["rounds"] = safe_metrics.get("rounds", 0)',
     STEP_FAILURE_TESTS + LOOP_TESTS),
    ("Q11 un intento fallido suma una peticion aunque la ruta directa ya la contaba", SCHED,
     '                            safe_metrics["rounds"] = (len(texts) if isinstance(texts, list) and texts\n'
     '                                                      else safe_metrics.get("rounds", 0) + 1)',
     '                            safe_metrics["rounds"] = safe_metrics.get("rounds", 0) + 1',
     STEP_FAILURE_TESTS + LOOP_TESTS),
    ("Q12 el evento de un intento fallido no dice que fallo", SCHED,
     '                            safe_metrics["failed"] = True',
     "                            pass",
     LOOP_TESTS),
    ("Q13 rounds se emite aunque el bucle no informara ninguna ronda", SCHED,
     "                        if isinstance(buckets, list) and buckets:",
     "                        if isinstance(buckets, list):",
     LOOP_TESTS),
    ("Q14 el error de un proveedor vuelve a llevar el texto del chunk", SCHED,
     "                raise RestrictedStreamError(_stream_error_status(event_str))",
     "                error = RestrictedStreamError(_stream_error_status(event_str))\n"
     "                error.args = (event_str,)\n"
     "                raise error",
     STEP_FAILURE_TESTS),
    ("Q15 el planificador trata igual un fin normal y uno fallido", SCHED,
     '                        if kind == "agent_terminal":',
     "                        if False:",
     STEP_FAILURE_TESTS + LOOP_TESTS),

    # --- r8: what the loop's own tests still let through (review of r7: PM-03..PM-07, PM-13, PM-21) ---
    ("T12 la linea base corre solo las pruebas del primer mutante", TARGET,
     "    every = sorted({t for *_, tests in mutants for t in tests})",
     "    every = sorted(set(mutants[0][-1]))",
     CAMPAIGN_TESTS),
    ("T13 la guarda del arbol vivo no ve un .git que es un archivo", TARGET,
     '    if (pathlib.Path(repo) / ".git").exists() and os.environ.get("CMH_MUTANT_ALLOW_LIVE") != "1":',
     '    if (pathlib.Path(repo) / ".git").is_dir() and os.environ.get("CMH_MUTANT_ALLOW_LIVE") != "1":',
     CAMPAIGN_TESTS),
    ("T14 cualquier valor de CMH_MUTANT_ALLOW_LIVE salvo vacio levanta la guarda", TARGET,
     '    if (pathlib.Path(repo) / ".git").exists() and os.environ.get("CMH_MUTANT_ALLOW_LIVE") != "1":',
     '    if (pathlib.Path(repo) / ".git").exists() and os.environ.get("CMH_MUTANT_ALLOW_LIVE") is None:',
     CAMPAIGN_TESTS),
    ("T15 el resumen intercambia invalidos y obsoletos", TARGET,
     "{invalid} INVALIDOS - {skipped} NO APLICABLE",
     "{skipped} INVALIDOS - {invalid} NO APLICABLE",
     CAMPAIGN_TESTS),
    ("T16 el total del resumen deja fuera invalidos y obsoletos", TARGET,
     "    total = caught + survived + skipped + invalid",
     "    total = caught + survived",
     CAMPAIGN_TESTS),
    ("T17 un mutante puede nombrar un archivo fuera del export", TARGET,
     "        if not (root / relative).resolve().is_relative_to(root):",
     "        if False:",
     CAMPAIGN_TESTS),
    ("T18 un corredor sale en verde sin llamar a campaign()", "scripts/cmh_mutants/round8.py",
     "    sys.exit(campaign(MUTANTS, REPO, PY))",
     "    sys.exit(0)",
     TARGET_TESTS),
    ("T22 un corredor trunca su lista de mutantes", "scripts/cmh_mutants/round8.py",
     "    sys.exit(campaign(MUTANTS, REPO, PY))",
     "    sys.exit(campaign(MUTANTS[:1], REPO, PY))",
     TARGET_TESTS),
    ("T23 un corredor llama a campaign() con una lista vacia", "scripts/cmh_mutants/round8.py",
     "    sys.exit(campaign(MUTANTS, REPO, PY))",
     "    sys.exit(campaign([], REPO, PY))",
     TARGET_TESTS),
    ("T24 un corredor tiene apagada su guarda __main__", "scripts/cmh_mutants/round8.py",
     'if __name__ == "__main__":',
     "if False:",
     TARGET_TESTS),
    ("T25 la guarda de ruta de campaign() mira solo al primer mutante", TARGET,
     "    for _, relative, *_ in mutants:",
     "    for _, relative, *_ in mutants[:1]:",
     CAMPAIGN_TESTS),
    ("T26 el archivo se anuncia DESPUES de mutarlo", TARGET,
     '        say(f"   (mutando {relative} para {name})")\n'
     '        path.write_bytes((mutated.replace("\\n", "\\r\\n") if crlf else mutated).encode("utf-8"))',
     '        path.write_bytes((mutated.replace("\\n", "\\r\\n") if crlf else mutated).encode("utf-8"))\n'
     '        say(f"   (mutando {relative} para {name})")',
     CAMPAIGN_TESTS),
    ("T19 failed_id vuelve a cortar el id en un guion dentro de los corchetes", TARGET,
     '        closed = re.match(r"(.*?\\])(?: - |$)", rest)',
     "        closed = None",
     CAMPAIGN_TESTS),
    ("T20 el avance de la campana deja de vaciarse", TARGET,
     "say = functools.partial(print, flush=True)",
     "say = print",
     CAMPAIGN_TESTS),
    ("T21 la campana deja de anunciar que archivo esta mutado", TARGET,
     '        say(f"   (mutando {relative} para {name})")',
     "        pass",
     CAMPAIGN_TESTS),

    # --- r8: a failing quota write is said in the run; failure_ttl_s is read from the config ---
    ("Q16 un fallo al escribir la cuota deja de decirse en el run", FLOW,
     '                record("quota_write_failed", endpoint_id=_event_id(candidate.get("endpoint_id")),\n'
     '                       error_type=type(exc).__name__)',
     "                pass",
     STEP_FAILURE_TESTS),
    ("D34 failure_ttl_s se lee del codigo y no del config", ROUTER,
     '            ttl = knobs["failure_ttl_s"]',
     '            ttl = _DEFAULT_DISCOVERY["failure_ttl_s"]',
     DISCOVERY_TESTS),
    # --- r9: an event never carries a URL as an endpoint id; the inner guard of the charge -----
    ("Q17 el evento de cuota vuelve a publicar el id del endpoint sin recortar", FLOW,
     '                record("quota_write_failed", endpoint_id=_event_id(candidate.get("endpoint_id")),',
     '                record("quota_write_failed", endpoint_id=candidate.get("endpoint_id"),',
     STEP_FAILURE_TESTS),
    ("Q18 _event_id deja pasar una URL con credenciales", FLOW,
     '    return redact_url(text) if "://" in text else endpoint_id',
     "    return endpoint_id",
     STEP_FAILURE_TESTS),
    ("Q19 si falla el evento de cuota tambien, el paso muere", FLOW,
     '            except Exception:\n                logger.exception("Could not record quota_write_failed',
     '            except KeyError:\n                logger.exception("Could not record quota_write_failed',
     STEP_FAILURE_TESTS),
]


if __name__ == "__main__":
    sys.exit(campaign(MUTANTS, REPO, PY))
