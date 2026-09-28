"""_LOCAL_MODEL_WAITING_FOREGROUND must be decremented exactly once per caller.

The counter is what a background caller polls to decide whether a foreground
request is queued ahead of it. A foreground caller that acquires the slot used
to decrement it twice -- once right after acquiring and once again in the
``finally`` -- so a still-waiting sibling became invisible and background work
could slip in ahead of it.

Drives the real context manager against a local URL; no provider is called.
"""

import asyncio

import pytest

import src.llm_core as llm_core

LOCAL_URL = "http://127.0.0.1:1234/v1"


@pytest.fixture
def gate(monkeypatch):
    """Fresh lock and counter so tests cannot leak state into each other."""
    monkeypatch.setenv("ODYSSEUS_LOCAL_MODEL_GATE", "true")
    monkeypatch.setenv("BACKGROUND_TASK_FOREGROUND_GATE", "false")
    monkeypatch.setattr(llm_core, "_LOCAL_MODEL_LOCK", asyncio.Lock())
    monkeypatch.setattr(llm_core, "_LOCAL_MODEL_CURRENT", {})
    monkeypatch.setattr(llm_core, "_LOCAL_MODEL_WAITING_FOREGROUND", 0)

    def waiting():
        return llm_core._LOCAL_MODEL_WAITING_FOREGROUND

    def seed(value):
        monkeypatch.setattr(llm_core, "_LOCAL_MODEL_WAITING_FOREGROUND", value)

    return type("Gate", (), {"waiting": staticmethod(waiting), "seed": staticmethod(seed)})


async def test_foreground_caller_that_acquires_does_not_decrement_a_sibling_away(gate):
    # One sibling is already queued. Our caller must leave that 1 untouched.
    gate.seed(1)
    async with llm_core._local_model_slot(LOCAL_URL, "m", workload="foreground"):
        # While we hold the slot our own increment is already spent.
        assert gate.waiting() == 1
    assert gate.waiting() == 1, "a completed foreground caller erased a waiting sibling"


async def test_foreground_caller_cancelled_while_waiting_still_releases_its_count(gate):
    # The `finally` decrement exists for this path and must keep working.
    held = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with llm_core._local_model_slot(LOCAL_URL, "m", workload="foreground"):
            held.set()
            await release.wait()

    holder_task = asyncio.create_task(holder())
    await asyncio.wait_for(held.wait(), timeout=2)

    async def waiter():
        async with llm_core._local_model_slot(LOCAL_URL, "m", workload="foreground"):
            pass

    waiter_task = asyncio.create_task(waiter())
    while gate.waiting() == 0:  # let it register as queued before cancelling
        await asyncio.sleep(0.01)
    assert gate.waiting() == 1

    waiter_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter_task
    assert gate.waiting() == 0, "a cancelled foreground caller left its count behind"

    release.set()
    await holder_task
    assert gate.waiting() == 0


async def test_serial_foreground_callers_return_the_counter_to_zero(gate):
    for _ in range(3):
        async with llm_core._local_model_slot(LOCAL_URL, "m", workload="foreground"):
            pass
    assert gate.waiting() == 0


async def test_a_cloud_endpoint_is_not_gated_at_all(gate):
    gate.seed(1)
    async with llm_core._local_model_slot("https://api.anthropic.com", "m", workload="foreground"):
        pass
    assert gate.waiting() == 1
