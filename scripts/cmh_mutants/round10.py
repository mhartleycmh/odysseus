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

SCHEDULER = "src/task_scheduler.py"

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
]


if __name__ == "__main__":
    sys.exit(campaign(MUTANTS, REPO, PY))
