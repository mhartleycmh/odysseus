"""Mutants for the corrections of the independent review of r10 (2026-10-04, ADR-040).

Each mutant names the test module, or the test, that must fall. A mutant that does not
fall is a test that cannot fail: that is the only reason this file exists.

Run it against an EXPORT of a commit, never the live tree. The runner refuses a
directory that contains .git (see _target.py).

    git archive <commit> | tar -x -C /tmp/export
    CMH_MUTANT_REPO=/tmp/export python scripts/cmh_mutants/round10.py
"""

import pathlib
import sys

from _target import resolve_repo
from _target import campaign

REPO = resolve_repo(pathlib.Path(__file__).resolve().parents[2])
PY = pathlib.Path(sys.executable)
if not PY.exists() or "python" not in PY.name.lower():
    PY = REPO.parent.parent / ".venv" / "Scripts" / "python.exe"

LOOP_TESTS = ["tests/test_cmh_restricted_loop.py"]
REPORT = "tests/test_cmh_run_report.py"
VERDICT_INTERRUPTED = ("tests/test_cmh_mutant_validity.py::"
                       "test_a_pytest_that_did_not_end_by_itself_is_interrupted_not_invalid")
CAMPAIGN_INTERRUPTED = ("tests/test_cmh_mutant_campaign.py::"
                        "test_a_pytest_that_did_not_finish_stops_the_campaign_and_judges_nothing_after_it")
CAMPAIGN_INVALID_TAIL = "tests/test_cmh_mutant_campaign.py::test_an_invalid_mutant_shows_what_pytest_said"
VALIDITY_ROUND4 = "tests/test_cmh_mutant_validity.py::test_every_mutant_is_applicable_and_compiles[round4.py]"

SCHEDULER = "src/task_scheduler.py"
REPORT_SCRIPT = "scripts/cmh_ops/run_report.py"
TARGET = "scripts/cmh_mutants/_target.py"

#: The restricted block as ADR-040 leaves it: no text of its own, the step fails.
RESTRICTED_FAILS = (
    "            if not full_text:\n"
    "                # No second call, with or without tool evidence: a text Odysseus asked\n"
    "                # for after the loop is a forced synthesis, and canon 05 (2026-09-24)\n"
    "                # makes that a failure of the step (ADR-040; 2596a2b6 had added one).\n"
    "                raise RuntimeError(\"Restricted task produced no final model output\")\n"
)

#: The same block as 2596a2b6 wrote it, line for line: the forced synthesis comes back.
SYNTHESIS_OF_2596A2B6 = (
    "            if not full_text:\n"
    "                if require_tool_evidence and not successful_tool_calls:\n"
    "                    raise RuntimeError(\"Restricted task produced no final model output\")\n"
    "                try:\n"
    "                    from src.llm_core import llm_call_async\n"
    "                    grace_context = \"You ran out of tool-call rounds. \"\n"
    "                    if tool_results:\n"
    "                        grace_context += \"Here are the successful tool results:\\n\" + \"\\n\".join(tool_results[-5:])\n"
    "                    else:\n"
    "                        grace_context += \"No successful tool output was captured.\"\n"
    "                    grace_context += (\n"
    "                        \"\\n\\nProduce the final artifact now. Be concise. Do not request \"\n"
    "                        \"more tools, do not mention hidden reasoning, and label unresolved \"\n"
    "                        \"items as PENDIENTE.\"\n"
    "                    )\n"
    "                    full_text = await llm_call_async(\n"
    "                        endpoint_url,\n"
    "                        model,\n"
    "                        messages=[\n"
    "                            {\"role\": \"system\", \"content\": system_content},\n"
    "                            {\"role\": \"user\", \"content\": grace_context},\n"
    "                        ],\n"
    "                        headers=headers,\n"
    "                        timeout=30,\n"
    "                        workload=\"foreground\" if foreground_controlled else \"background\",\n"
    "                    )\n"
    "                    full_text = strip_think(full_text or \"\", prompt_echo=False).strip()\n"
    "                except Exception as e:\n"
    "                    logger.warning(f\"Restricted grace summarization failed: {e}\")\n"
    "                if not full_text:\n"
    "                    raise RuntimeError(\"Restricted task produced no final model output\")\n"
)

#: (name, file, text to replace, replacement, test modules or node ids that must fall)
MUTANTS = [
    # --- P1-1/2/3, P2-4/5: no forced synthesis in a restricted task -----------------
    ("S01 vuelve la sintesis forzada de 2596a2b6 en las tareas restringidas", SCHEDULER,
     RESTRICTED_FAILS,
     SYNTHESIS_OF_2596A2B6,
     LOOP_TESTS),
    ("S02 una tarea restringida sin texto propio cae a la sintesis sin traza de las no restringidas",
     SCHEDULER,
     "                raise RuntimeError(\"Restricted task produced no final model output\")\n",
     "                pass\n",
     LOOP_TESTS),
    # --- P2-6: run_report closes only on APROBADO and does not call a decision human -------
    ("RV01 TODO CUMPLIDO deja de exigir el veredicto del revisor", REPORT_SCRIPT,
     '        and criteria["review_approved"]\n',
     '',
     [f"{REPORT}::test_only_a_reviewer_that_declares_aprobado_closes_the_phase"]),
    ("RV02 un DEVUELTO cuenta como aprobado", REPORT_SCRIPT,
     '"review_approved": verdict == "APROBADO",',
     '"review_approved": verdict is not None,',
     [f"{REPORT}::test_only_a_reviewer_that_declares_aprobado_closes_the_phase"]),
    ("RV03 un veredicto ausente cuenta como aprobado", REPORT_SCRIPT,
     '"review_approved": verdict == "APROBADO",',
     '"review_approved": verdict != "DEVUELTO",',
     [f"{REPORT}::test_only_a_reviewer_that_declares_aprobado_closes_the_phase"]),
    ("RV04 cualquier palabra tras VEREDICTO vale, tambien la plantilla sin llenar", REPORT_SCRIPT,
     "    if len(set(found)) != 1 or found[0] not in VERDICTS:",
     "    if len(set(found)) != 1:",
     [f"{REPORT}::test_a_verdict_nobody_can_read_is_not_an_approval"]),
    ("RV05 dos lineas de veredicto que se contradicen valen por la primera", REPORT_SCRIPT,
     "    if len(set(found)) != 1 or found[0] not in VERDICTS:",
     "    if found[0] not in VERDICTS:",
     [f"{REPORT}::test_a_verdict_nobody_can_read_is_not_an_approval"]),
    ("RV06 el veredicto con marcas markdown (el de 012ea502) deja de leerse", REPORT_SCRIPT,
     # r12: the verdict is the first line (r11 review, P1-1), read by its own expression.
     '        re.sub(r"^[\\s#]+", "", re.sub(r"[*_`]", "", lines[first])).strip())',
     "        lines[first].strip())",
     [f"{REPORT}::test_only_a_reviewer_that_declares_aprobado_closes_the_phase"]),
    ("RV07 un veredicto en minusculas deja de leerse", REPORT_SCRIPT,
     "    found = [opening.group(1).upper()]",
     "    found = [opening.group(1)]",
     [f"{REPORT}::test_a_verdict_nobody_can_read_is_not_an_approval"]),
    ("RV08 el informe deja de leer el texto del artefacto del revisor", REPORT_SCRIPT,
     "        if key == REVIEW_STEP:\n            review_text = text",
     "        if False:\n            review_text = text",
     [f"{REPORT}::test_only_a_reviewer_that_declares_aprobado_closes_the_phase"]),
    ("RV09 la decision vuelve a rotularse humana", REPORT_SCRIPT,
     "f\"    decision registrada por {d.get('by')} el {d.get('at')}: {d.get('outcome')}\"",
     "f\"    decision humana: {d.get('outcome')} por {d.get('by')} el {d.get('at')}\"",
     [f"{REPORT}::test_a_decision_says_who_it_was_registered_by_and_why_never_that_it_was_human"]),
    ("RV10 la justificacion de la decision deja de imprimirse", REPORT_SCRIPT,
     "            lines.append(f\"    justificacion: {d.get('justification') or 'sin justificacion'}\")\n",
     "",
     [f"{REPORT}::test_a_decision_says_who_it_was_registered_by_and_why_never_that_it_was_human"]),
    # --- round9 Z16/Z17: a pytest that did not end by itself is not a broken mutant ---------
    ("H01 un pytest interrumpido vuelve a contarse como mutante INVALIDO", TARGET,
     '    if (returncode not in PYTEST_EXIT_CODES or not stdout.strip()\n'
     '            or "KeyboardInterrupt" in stdout):\n        return "INTERRUMPIDO"',
     '    if False:\n        return "INTERRUMPIDO"',
     [VERDICT_INTERRUPTED, CAMPAIGN_INTERRUPTED]),
    ("H02 un Ctrl+C que pytest atrapo deja de verse como interrupcion", TARGET,
     '            or "KeyboardInterrupt" in stdout):',
     '            ):',
     [VERDICT_INTERRUPTED, CAMPAIGN_INTERRUPTED]),
    ("H03 un pytest matado sin salida deja de verse como interrupcion", TARGET,
     "    if (returncode not in PYTEST_EXIT_CODES or not stdout.strip()\n",
     "    if (returncode not in PYTEST_EXIT_CODES\n",
     [VERDICT_INTERRUPTED]),
    ("H04 un codigo que pytest nunca devuelve deja de verse como interrupcion", TARGET,
     "    if (returncode not in PYTEST_EXIT_CODES or not stdout.strip()\n",
     "    if (not stdout.strip()\n",
     [VERDICT_INTERRUPTED]),
    ("H05 la campana sigue juzgando mutantes despues de una interrupcion", TARGET,
     '                "veredicto. Repita la campana.")\n            return 3\n',
     '                "veredicto. Repita la campana.")\n',
     [CAMPAIGN_INTERRUPTED]),
    ("H06 un mutante INVALIDO deja de mostrar lo que dijo pytest", TARGET,
     '                _tail(result)\n            elif outcome == "INTERRUMPIDO":',
     '            elif outcome == "INTERRUMPIDO":',
     [CAMPAIGN_INVALID_TAIL]),
    ("H07 el aviso de interrupcion vuelve a repetir el texto del resumen que muta T15", TARGET,
     '{survived} SURVIVED, "\n                f"{invalid} INVALIDOS, {skipped} NO APLICABLE; los "',
     '{survived} SURVIVED, "\n                f"{invalid} INVALIDOS - {skipped} NO APLICABLE; los "',
     [VALIDITY_ROUND4]),
]


if __name__ == "__main__":
    sys.exit(campaign(MUTANTS, REPO, PY))
