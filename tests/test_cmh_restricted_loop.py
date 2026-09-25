"""A restricted run returns only its own model's answer, or fails.

Drives the real TaskScheduler._run_agent_loop with a stubbed stream carrying
the chunks agent_loop.py emits; no provider is called.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

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

    async def execute(chunks, allowed_tools=("glob", "grep", "ls", "read_file"), **loop_kwargs):
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
            foreground_controlled=True, event_sink=lambda kind, **payload: events.append((kind, payload)),
            **loop_kwargs)
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


@pytest.mark.parametrize("tool_events", [
    [],
    [chunk({"type": "tool_start", "tool": "read_file"}),
     chunk({"type": "tool_output", "tool": "read_file", "exit_code": 1,
            "output": "read_file: path '..' is outside the workspace"})],
], ids=["no_tool_call", "only_blocked_call"])
async def test_evidence_required_run_without_a_successful_tool_call_fails(run, tool_events):
    # Run 0850ebfe (2026-09-24): 0 tool calls, yet it reported "no files found".
    with pytest.raises(RuntimeError, match="without any successful tool call"):
        await run([*tool_events, chunk({"delta": "Workspace accesible, sin archivos."}), "data: [DONE]\n\n"],
                  require_tool_evidence=True)


async def test_evidence_required_run_with_a_successful_tool_call_returns_its_answer(run):
    output, _ = await run([
        chunk({"type": "tool_start", "tool": "ls"}),
        chunk({"type": "tool_output", "tool": "ls", "exit_code": 0, "output": "input/\noutput/"}),
        chunk({"delta": "Hay dos carpetas."}),
        "data: [DONE]\n\n",
    ], require_tool_evidence=True)
    assert output == "Hay dos carpetas."


def test_scheduled_restricted_task_with_workspace_requires_tool_evidence():
    from src import task_scheduler
    for allowed, workspace, expected in [
        ('["ls"]', "C:/ws", True),
        (None, "C:/ws", False),
        ('["ls"]', None, False),
        ('["ls"]', "", False),  # validate_task_workspace("") is None: no workspace bound
    ]:
        task = SimpleNamespace(allowed_tools=allowed, workspace=workspace)
        assert task_scheduler._requires_tool_evidence(task) is expected


def scheduled_pilot(workspace):
    return SimpleNamespace(
        workspace=str(workspace), owner="admin", prompt="Inspecciona el workspace", name="Pilot",
        crew_member_id=None, endpoint_url="http://model.invalid", model="m", session_id="session",
        max_steps=4, character_id=None, allowed_tools='["glob", "grep", "ls", "read_file"]',
    )


@pytest.fixture
def scheduled(monkeypatch, tmp_path):
    monkeypatch.setattr("src.tool_security.owner_is_admin_or_single_user", lambda owner: owner == "admin")
    monkeypatch.setattr("src.tool_index.get_tool_index", lambda: None)
    fallback = AsyncMock(return_value="UNTRACED")
    monkeypatch.setattr("src.task_endpoint.task_llm_call_async", fallback)

    async def execute(chunks):
        async def fake_stream(**kwargs):
            for item in chunks:
                yield item
        monkeypatch.setattr(agent_loop, "stream_agent_loop", fake_stream)
        return await TaskScheduler(session_manager=None)._execute_llm_task(
            scheduled_pilot(tmp_path.resolve()), None)

    execute.fallback = fallback
    return execute


async def test_scheduled_pilot_without_tool_calls_ends_in_error_without_fallback(scheduled):
    # The scheduled path, not a hand-set flag, must turn run 0850ebfe into an error.
    with pytest.raises(RuntimeError, match="no untraced fallback") as exc:
        await scheduled([chunk({"delta": "Workspace accesible, sin archivos."}), "data: [DONE]\n\n"])
    assert "without any successful tool call" in str(exc.value.__cause__)
    scheduled.fallback.assert_not_awaited()


async def test_scheduled_pilot_with_a_successful_tool_call_returns_its_answer(scheduled):
    output = await scheduled([
        chunk({"type": "tool_start", "tool": "ls"}),
        chunk({"type": "tool_output", "tool": "ls", "exit_code": 0, "output": "input/"}),
        chunk({"delta": "Hay una carpeta input/."}),
        "data: [DONE]\n\n",
    ])
    assert output == "Hay una carpeta input/."
