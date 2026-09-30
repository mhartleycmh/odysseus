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

    async def execute(chunks, allowed_tools=("glob", "grep", "ls", "read_file"),
                      foreground_controlled=True, **loop_kwargs):
        async def fake_stream(**kwargs):
            seen.update(kwargs)
            for item in chunks:
                yield item
        monkeypatch.setattr(agent_loop, "stream_agent_loop", fake_stream)
        events = []
        execute.events = events      # still readable when the attempt raises
        task = SimpleNamespace(owner="admin", name="constructor", prompt="p", workspace=str(workspace),
                               allowed_tools=None if allowed_tools is None else json.dumps(list(allowed_tools)),
                               max_steps=12)
        output = await TaskScheduler(None)._run_agent_loop(
            "http://model.invalid", "m", task, "session", system_prompt="x", override_user_message="p",
            foreground_controlled=foreground_controlled,
            event_sink=lambda kind, **payload: events.append((kind, payload)),
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


@pytest.mark.parametrize("foreground_controlled, workload", [(True, "foreground"), (False, "background")])
async def test_foreground_controlled_step_is_not_gated_as_background_work(run, foreground_controlled, workload):
    # _local_model_slot makes a background caller wait while has_foreground_activity()
    # is true and cancels it mid-generation for any foreground request. The browser
    # heartbeat fires every 15 s and keeps that true for 45 s, so a workflow step the
    # user launched and is watching could never acquire the local model.
    await run([chunk({"delta": "Listo."}), "data: [DONE]\n\n"], foreground_controlled=foreground_controlled)
    assert run.seen["workload"] == workload


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
    seen = {}

    async def execute(chunks):
        async def fake_stream(**kwargs):
            seen.update(kwargs)
            for item in chunks:
                yield item
        monkeypatch.setattr(agent_loop, "stream_agent_loop", fake_stream)
        return await TaskScheduler(session_manager=None)._execute_llm_task(
            scheduled_pilot(tmp_path.resolve()), None)

    execute.fallback = fallback
    execute.seen = seen
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


async def test_scheduled_path_keeps_yielding_to_the_foreground(scheduled):
    # The scheduled route must not inherit the workflow step's exemption:
    # an automatic job still waits for the browser to go quiet.
    await scheduled([
        chunk({"type": "tool_start", "tool": "ls"}),
        chunk({"type": "tool_output", "tool": "ls", "exit_code": 0, "output": "input/"}),
        chunk({"delta": "Listo."}), "data: [DONE]\n\n",
    ])
    assert scheduled.seen["workload"] == "background"


async def test_workflow_step_declares_itself_foreground_controlled(monkeypatch, tmp_path):
    # Connects the wire: without this, the fix above is unreachable from a flow.
    #
    # It brings its own database. It used to read whatever core.database.SessionLocal
    # was bound to, an in-memory database that the seed script's engine.dispose()
    # empties: run after tests/test_cmh_seed_scripts.py it failed with "no such table:
    # model_endpoints", and only the alphabetical order hid it.
    import core.database as cdb
    import src.cmh_workflows as cmh_workflows
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    cdb.Base.metadata.create_all(engine)
    monkeypatch.setattr(cmh_workflows, "SessionLocal", sessionmaker(bind=engine))
    seen = {}

    async def fake_loop(self, endpoint_url, model, task, session_id, **kwargs):
        seen.update(kwargs)
        return "artefacto"

    monkeypatch.setattr(TaskScheduler, "_run_agent_loop", fake_loop)
    config = {"run_id": "r", "step_key": "constructor", "agent_id": "a", "model": "m", "owner": "admin",
              "name": "constructor", "workspace": str(tmp_path), "allowed_tools": ["ls"],
              "endpoint_url": "http://127.0.0.1:59999/v1", "instructions": "x"}
    assert await cmh_workflows.call_model(config, "objetivo") == "artefacto"
    assert seen["foreground_controlled"] is True


async def test_metrics_with_no_usage_buckets_do_not_claim_rounds(run):
    """Unknown is not zero: a loop that reported no buckets must not turn into 'rounds=0'."""
    _, events = await run([
        chunk({"type": "metrics", "data": {"input_tokens": 4, "output_tokens": 2,
                                           "usage_buckets": []}}),
        chunk({"delta": "Listo."}),
        "data: [DONE]\n\n",
    ])
    forwarded = [payload["metrics"] for kind, payload in events if kind == "model_metrics"]
    assert len(forwarded) == 1 and "rounds" not in forwarded[0]
    assert forwarded[0]["input_tokens"] == 4


async def test_a_failed_attempt_reports_what_it_had_spent_before_the_error(run):
    """The loop yields an agent_terminal chunk, with its totals so far, and then the error
    chunk. Two rounds had completed (two buckets) and the third took the 429: three
    requests, and the tokens of the two that answered."""
    terminal = {"failed": True, "failure": {"status": 429, "message": "rate limited"},
                "round_texts": ["uno", "dos", "[Agent stopped: rate limited]"],
                "input_tokens": 20, "output_tokens": 10, "total_tokens": 30,
                "usage_source": "real",
                "usage_buckets": [{"input_tokens": 10, "output_tokens": 5},
                                  {"input_tokens": 10, "output_tokens": 5}]}
    with pytest.raises(RuntimeError):
        await run([chunk({"type": "agent_terminal", "data": terminal}),
                   'event: error\ndata: {"error": "rate limited", "status": 429}\n\n'])
    forwarded = [payload["metrics"] for kind, payload in run.events if kind == "model_metrics"]
    assert forwarded == [{"input_tokens": 20, "output_tokens": 10, "total_tokens": 30,
                          "usage_source": "real", "rounds": 3, "failed": True}]


async def test_a_failure_of_the_direct_path_counts_its_one_request_once(run):
    """The direct path puts its single request in one bucket AND one round text: adding
    one for 'the request that failed' would count it twice."""
    terminal = {"failed": True, "failure": {"status": 503, "message": "down"},
                "round_texts": ["[Agent stopped: down]"],
                "input_tokens": 3, "output_tokens": 0, "total_tokens": 3, "usage_source": "estimated",
                "usage_buckets": [{"input_tokens": 3, "output_tokens": 0}]}
    with pytest.raises(RuntimeError):
        await run([chunk({"type": "agent_terminal", "data": terminal}),
                   'event: error\ndata: {"error": "down", "status": 503}\n\n'])
    forwarded = [payload["metrics"] for kind, payload in run.events if kind == "model_metrics"]
    assert [m["rounds"] for m in forwarded] == [1]


async def test_a_failure_before_any_round_still_counts_the_request_that_was_refused(run):
    terminal = {"failed": True, "failure": {"status": 429, "message": "limited"}}
    with pytest.raises(RuntimeError):
        await run([chunk({"type": "agent_terminal", "data": terminal}),
                   'event: error\ndata: {"error": "limited", "status": 429}\n\n'])
    forwarded = [payload["metrics"] for kind, payload in run.events if kind == "model_metrics"]
    assert [m["rounds"] for m in forwarded] == [1]


async def test_tool_finished_carries_the_numeric_exit_code(run):
    """ESTADO and blueprint 7.3 both said the events carry exit_code; only a boolean
    `error` was emitted. Step 3.6 records the exit of every tool call."""
    _, events = await run([
        chunk({"type": "tool_start", "tool": "read_file"}),
        chunk({"type": "tool_start", "tool": "ls"}),
        chunk({"type": "tool_start", "tool": "grep"}),
        chunk({"type": "tool_output", "tool": "read_file", "output": "Error: not found", "exit_code": 1}),
        chunk({"type": "tool_output", "tool": "ls", "output": "ok", "exit_code": 0}),
        chunk({"type": "tool_output", "tool": "grep", "output": "ok"}),
        chunk({"delta": "Listo."}),
        "data: [DONE]\n\n",
    ])
    finished = [payload for kind, payload in events if kind == "tool_finished"]
    assert [(p["tool"], p["exit_code"]) for p in finished] == [
        ("read_file", 1), ("ls", 0), ("grep", None)]
