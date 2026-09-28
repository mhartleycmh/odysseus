"""_LOCAL_MODEL_WAITING_FOREGROUND must be decremented exactly once per caller.

The counter is read by the background branch's wait loop to decide whether to
start queueing for the local model at all. A foreground caller that acquired
the slot used to decrement it twice -- once right after acquiring and once
again in the ``finally`` -- so a sibling still queued became invisible and a
background caller arriving in that window queued immediately instead of
deferring. It never reordered callers already in the lock queue: asyncio.Lock
is FIFO. These tests pin the accounting, the gating the counter exists for,
and the priority contract a foreground workflow step now has against the chat.

Drives the real context manager against a local URL; no provider is called.
"""

import asyncio

import pytest

import src.llm_core as llm_core

LOCAL_URL = "http://127.0.0.1:1234/v1"
CLOUD_URL = "https://api.anthropic.com"
# Every wait in this module is bounded. An unbounded poll turns a future
# regression in the counter from a red test into a hung run, and this venv has
# no pytest-timeout to catch it.
DEADLINE = 2.0


@pytest.fixture
def gate(monkeypatch):
    """Fresh lock and counter so tests cannot leak state into each other."""
    monkeypatch.setenv("ODYSSEUS_LOCAL_MODEL_GATE", "true")
    monkeypatch.setenv("BACKGROUND_TASK_FOREGROUND_GATE", "false")
    lock = asyncio.Lock()
    monkeypatch.setattr(llm_core, "_LOCAL_MODEL_LOCK", lock)
    monkeypatch.setattr(llm_core, "_LOCAL_MODEL_CURRENT", {})
    monkeypatch.setattr(llm_core, "_LOCAL_MODEL_WAITING_FOREGROUND", 0)

    def waiting():
        return llm_core._LOCAL_MODEL_WAITING_FOREGROUND

    def seed(value):
        monkeypatch.setattr(llm_core, "_LOCAL_MODEL_WAITING_FOREGROUND", value)

    def queued_on_lock():
        """How many callers sit in the lock's FIFO queue.

        Reads an asyncio internal on purpose: it is the only direct observable
        for "did the background caller queue while a foreground one waited",
        which is the single thing the counter exists to prevent.
        """
        assert hasattr(lock, "_waiters"), "asyncio.Lock lost _waiters; rewrite this probe"
        return len(lock._waiters or ())

    async def until(predicate, what):
        loop = asyncio.get_running_loop()
        limit = loop.time() + DEADLINE
        while not predicate():
            if loop.time() >= limit:
                pytest.fail(f"timed out after {DEADLINE}s waiting for {what}")
            await asyncio.sleep(0.01)

    return type("Gate", (), {
        "waiting": staticmethod(waiting),
        "seed": staticmethod(seed),
        "queued_on_lock": staticmethod(queued_on_lock),
        "until": staticmethod(until),
    })


def foreground(url=LOCAL_URL):
    return llm_core._local_model_slot(url, "m", workload="foreground")


def background(url=LOCAL_URL):
    return llm_core._local_model_slot(url, "m", workload="background")


# ── exact accounting ──────────────────────────────────────────────────────────

async def test_foreground_caller_that_acquires_does_not_decrement_a_sibling_away(gate):
    # One sibling is already queued. Our caller must leave that 1 untouched.
    gate.seed(1)
    async with foreground():
        # While we hold the slot our own increment is already spent.
        assert gate.waiting() == 1
    assert gate.waiting() == 1, "a completed foreground caller erased a waiting sibling"


async def test_foreground_caller_cancelled_while_waiting_still_releases_its_count(gate):
    # The `finally` decrement exists for this path and must keep working.
    release = asyncio.Event()

    async def holder():
        async with foreground():
            await release.wait()

    holder_task = asyncio.create_task(holder())
    await gate.until(lambda: llm_core._LOCAL_MODEL_LOCK.locked(), "the holder to take the slot")

    async def waiter():
        async with foreground():
            pass

    waiter_task = asyncio.create_task(waiter())
    await gate.until(lambda: gate.waiting() == 1, "the waiter to register as queued")

    waiter_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter_task
    assert gate.waiting() == 0, "a cancelled foreground caller left its count behind"

    release.set()
    await holder_task
    assert gate.waiting() == 0


async def test_cancelled_waiter_gives_back_only_its_own_count(gate):
    # Guards the "exactly one" claim on the cancelled path too: max(0, ...)
    # would otherwise hide an over-decrement that eats a queued sibling.
    gate.seed(1)
    release = asyncio.Event()

    async def holder():
        async with foreground():
            await release.wait()

    holder_task = asyncio.create_task(holder())
    await gate.until(lambda: llm_core._LOCAL_MODEL_LOCK.locked(), "the holder to take the slot")

    async def waiter():
        async with foreground():
            pass

    waiter_task = asyncio.create_task(waiter())
    # The holder already spent its own count on acquiring, so the seeded
    # sibling plus the queued waiter make 2.
    await gate.until(lambda: gate.waiting() == 2, "the sibling and the waiter to be counted")

    waiter_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter_task
    assert gate.waiting() == 1, "the cancelled waiter took more than its own count"

    release.set()
    await holder_task
    assert gate.waiting() == 1, "the seeded sibling was erased"


async def test_serial_foreground_callers_return_the_counter_to_zero(gate):
    for _ in range(3):
        async with foreground():
            pass
    assert gate.waiting() == 0


async def test_a_cloud_endpoint_is_not_gated_at_all(gate):
    gate.seed(1)
    async with foreground(CLOUD_URL):
        pass
    assert gate.waiting() == 1


# ── what the counter is for ───────────────────────────────────────────────────

async def test_a_queued_foreground_caller_keeps_background_out_of_the_lock_queue(gate):
    """The counter's only consumer: the background wait loop.

    While a foreground caller is queued, a background caller must stay in its
    poll and not join the lock queue. Without the counter check in that loop
    the gate is decorative -- the mechanism can be deleted silently.
    """
    release = asyncio.Event()

    async def holder():
        async with foreground():
            await release.wait()

    holder_task = asyncio.create_task(holder())
    await gate.until(lambda: llm_core._LOCAL_MODEL_LOCK.locked(), "the holder to take the slot")

    async def fg_waiter():
        async with foreground():
            pass

    fg_task = asyncio.create_task(fg_waiter())
    await gate.until(lambda: gate.queued_on_lock() == 1, "the foreground waiter to queue")
    assert gate.waiting() == 1

    entered_background = False

    async def bg_waiter():
        nonlocal entered_background
        async with background():
            entered_background = True

    bg_task = asyncio.create_task(bg_waiter())
    # Give the background caller several poll cycles (the loop sleeps 0.25 s).
    await asyncio.sleep(0.6)
    assert gate.queued_on_lock() == 1, "a background caller queued past a waiting foreground one"
    assert not entered_background

    release.set()
    await asyncio.gather(holder_task, fg_task, bg_task)
    assert entered_background
    assert gate.waiting() == 0


# ── the priority contract this gate now encodes ───────────────────────────────

async def test_foreground_callers_serialize_without_pre_emption(gate):
    """A foreground caller waits for another; it does not cancel it.

    This is the cost of routing a hand-launched CMH workflow step as
    foreground: the chat used to pre-empt a background step mid-generation and
    now queues behind it, for as long as one generation takes. Pinned so a
    future change has to argue with it rather than discover it.
    """
    order = []
    release = asyncio.Event()

    async def step():
        async with foreground():
            order.append("step-in")
            await release.wait()
            order.append("step-out")

    step_task = asyncio.create_task(step())
    await gate.until(lambda: "step-in" in order, "the step to take the slot")

    async def chat():
        async with foreground():
            order.append("chat-in")

    chat_task = asyncio.create_task(chat())
    await gate.until(lambda: gate.queued_on_lock() == 1, "the chat to queue")

    # The step is mid-generation and must still be running: no pre-emption.
    await asyncio.sleep(0.1)
    assert not step_task.done() and not step_task.cancelled()
    assert order == ["step-in"]

    release.set()
    await asyncio.gather(step_task, chat_task)
    assert order == ["step-in", "step-out", "chat-in"]


async def test_background_defers_to_a_queued_foreground_caller_on_a_free_lock(gate):
    """Pins the waiting-counter clause, which the holding clause does not cover.

    The window: the lock is free and a foreground caller has been counted but
    has not yet resumed from acquire(), so _LOCAL_MODEL_CURRENT is still empty
    and only the counter can hold background work back. Forced by taking the
    raw lock, which leaves CURRENT untouched, and releasing it by hand.

    Ordering cannot detect this: measured both ways, the order is ['fg', 'bg']
    either way, because asyncio.Lock is FIFO and the foreground caller queued
    first. What the clause changes is whether the background caller joins the
    queue at all -- 1 waiter with it, 2 without -- so that is what is asserted.
    """
    order = []
    await llm_core._LOCAL_MODEL_LOCK.acquire()  # raw, so CURRENT stays empty

    async def fg():
        async with foreground():
            order.append("fg")

    async def bg():
        async with background():
            order.append("bg")

    fg_task = asyncio.create_task(fg())
    await gate.until(lambda: gate.waiting() == 1, "the foreground caller to be counted")
    bg_task = asyncio.create_task(bg())
    await asyncio.sleep(0.6)  # several cycles of the loop's 0.25 s sleep

    assert llm_core._LOCAL_MODEL_CURRENT.get("workload") is None, "probe no longer isolates the clause"
    assert gate.queued_on_lock() == 1, "a background caller queued past a counted foreground one"

    llm_core._LOCAL_MODEL_LOCK.release()
    await asyncio.wait_for(asyncio.gather(fg_task, bg_task), timeout=DEADLINE * 4)
    assert order == ["fg", "bg"]
    assert gate.waiting() == 0


async def test_background_does_not_queue_while_a_foreground_caller_generates(gate):
    """The counter goes to zero the moment a foreground caller acquires.

    That left a window as wide as one generation in which a background caller
    polling the loop saw a clear field, joined the lock queue, and so sat ahead
    of any foreground caller that arrived later -- automatic work beating
    interactive work on the single local model. Measured on the commit before
    this one: ['C(bg task)', 'B(fg chat)'].

    The gate is disabled here on purpose: it models the case this whole series
    is about, where only /cmh/os is open and sends no browser heartbeat, so
    has_foreground_activity() is false and the counter is the only thing left
    holding background work back.
    """
    order = []
    generating = asyncio.Event()
    finish = asyncio.Event()

    async def step():
        async with foreground():
            generating.set()
            await finish.wait()

    step_task = asyncio.create_task(step())
    await asyncio.wait_for(generating.wait(), timeout=DEADLINE)

    async def task():
        async with background():
            order.append("background")

    bg_task = asyncio.create_task(task())
    await asyncio.sleep(0.6)  # several cycles of the loop's 0.25 s sleep
    assert gate.queued_on_lock() == 0, "a background caller queued while a foreground one generated"

    async def chat():
        async with foreground():
            order.append("foreground")

    chat_task = asyncio.create_task(chat())
    await gate.until(lambda: gate.queued_on_lock() == 1, "the chat to queue")

    finish.set()
    await asyncio.wait_for(asyncio.gather(step_task, chat_task, bg_task), timeout=DEADLINE * 4)
    assert order == ["foreground", "background"], f"automatic work went first: {order}"
    assert gate.waiting() == 0


async def test_a_foreground_caller_does_cancel_a_running_background_one(gate):
    # The other half of the contract, unchanged by the workload fix: automatic
    # work still loses the slot the moment interactive work wants it.
    started = asyncio.Event()

    async def bg():
        async with background():
            started.set()
            await asyncio.sleep(DEADLINE * 5)

    bg_task = asyncio.create_task(bg())
    await asyncio.wait_for(started.wait(), timeout=DEADLINE)

    async def fg():
        async with foreground():
            return "fg ran"

    assert await asyncio.wait_for(fg(), timeout=DEADLINE) == "fg ran"
    assert bg_task.cancelled() or bg_task.done()
    if not bg_task.cancelled():
        with pytest.raises(asyncio.CancelledError):
            await bg_task
