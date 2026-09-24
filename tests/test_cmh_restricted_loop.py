"""A restricted run returns only its own model's answer, or fails.

Drives the real TaskScheduler._run_agent_loop with a stubbed stream carrying
the chunks agent_loop.py emits; no provider is called.
"""

import json
from types import SimpleNamespace

import pytest

import src.agent_loop as agent_loop
from src.task_scheduler import TaskScheduler


def chunk(obj):
    return "data: " + json.dumps(obj) + "\n\n"


@pytest.fixture
def run(monkeypatch, tmp_path):
    monkeypatch.setattr("src.tool_security.owner_is_admin_or_single_user", lambda owner: owner == "admin")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    seen = {}

    async def execute(chunks, allowed_tools=("glob", "grep", "ls", "read_file")):
        async def fake_stream(**kwargs):
            seen.update(kwargs)
            for item in chunks:
                yield item
        monkeypatch.setattr(agent_loop, "stream_agent_loop", fake_stream)
        events = []
        task = SimpleNamespace(owner="admin", name="constructor", prompt="p", workspace=str(workspace),
                               allowed_tools=None if allowed_tools is None else json.dumps(list(allowed_tools)),
                               max_steps=12)
        output = await TaskScheduler(None)._run_agent_loop(
            "http://model.invalid", "m", task, "session", system_prompt="x", override_user_message="p",
            foreground_controlled=True, event_sink=lambda kind, **payload: events.append((kind, payload)))
        return output, events

    execute.seen = seen
    return execute


async def test_empty_response_placeholder_fails_instead_of_becoming_the_artifact(run):
    _, placeholder = agent_loop._empty_response_fallback("", "", [])
    assert '"synthetic": "failure"' in placeholder
    with pytest.raises(RuntimeError, match="without its own answer"):
        await run([placeholder, "data: [DONE]\n\n"])


@pytest.mark.parametrize("final", [
    {"type": "rounds_exhausted", "rounds": 12},
    {"type": "teacher_takeover", "model": "other"},
    {"delta": "\n\n*[Stream error: 529 overloaded]*", "synthetic": "failure"},
])
async def test_round_cap_takeover_and_stream_error_fail_the_step(run, final):
    with pytest.raises(RuntimeError, match="without its own answer"):
        await run([chunk({"delta": "Voy a leer el archivo primero."}), chunk(final), "data: [DONE]\n\n"])


async def test_notes_and_inline_reasoning_are_not_part_of_the_artifact(run):
    output, _ = await run([
        chunk({"delta": "<think>razonamiento privado del constructor</think>Entregable final."}),
        chunk({"delta": "\n\n_Double-checked the work and found something to fix._\n\n", "synthetic": "note"}),
        "data: [DONE]\n\n",
    ])
    assert output == "Entregable final."
    assert run.seen["allow_escalation"] is False


async def test_sink_reports_tool_failures_and_token_counts(run):
    output, events = await run([
        chunk({"type": "tool_start", "tool": "read_file"}),
        chunk({"type": "tool_start", "tool": "read_file"}),
        chunk({"type": "tool_output", "tool": "read_file", "output": "Error: not found", "exit_code": 1}),
        chunk({"type": "tool_output", "tool": "read_file", "output": "ok", "exit_code": 0}),
        chunk({"delta": "Listo."}),
        chunk({"type": "metrics", "data": {"input_tokens": 1200, "output_tokens": 300, "total_tokens": 1500,
                                           "model": "m", "prompt": "never recorded"}}),
        "data: [DONE]\n\n",
    ])
    assert output == "Listo."
    finished = [payload for kind, payload in events if kind == "tool_finished"]
    assert [p["error"] for p in finished] == [True, False]
    assert all(p["duration_seconds"] is not None for p in finished)
    metrics = next(payload["metrics"] for kind, payload in events if kind == "model_metrics")
    assert metrics == {"input_tokens": 1200, "output_tokens": 300, "total_tokens": 1500, "model": "m"}


async def test_unrestricted_tasks_keep_escalation_and_legacy_text(run):
    output, _ = await run([chunk({"delta": "texto"}), chunk({"delta": " nota", "synthetic": "note"}),
                           "data: [DONE]\n\n"], allowed_tools=None)
    assert output == "texto nota"
    assert run.seen["allow_escalation"] is True
