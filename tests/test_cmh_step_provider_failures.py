"""A provider that refuses to answer moves the step to the next candidate, over the REAL chain.

Every earlier fallback test replaced ``flow._run_one_candidate`` with a double
that raised an exception carrying ``.status_code``. That is the one shape the
real chain never produces: the provider's status travels as text inside an
``event: error`` chunk and used to be flattened into a ``RuntimeError`` with no
status, so ``is_fallback_error`` answered ``None`` and the step died on its
first candidate. 16 tests exercised the fallback and none could see it.

Here only the network is fake. The path under test is
``call_model`` -> ``_run_one_candidate`` -> ``TaskScheduler._run_agent_loop``
-> ``stream_agent_loop`` -> ``stream_llm``; the transport is an ``httpx``
``MockTransport``, so every layer between the step and the socket is real.
"""

import json

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as cdb
import src.cmh_provider_router as router
import src.llm_core as llm_core
from src import cmh_workflows as flow

GROQ = "https://api.groq.com/openai/v1"
OPENROUTER = "https://openrouter.ai/api/v1"

CONFIG = {"threshold": 0.9, "providers": [
    {"endpoint_host": "api.groq.com", "order": 1, "model": "m-groq", "limits": {}},
    {"endpoint_host": "openrouter.ai", "order": 2, "model": "m-or:free", "limits": {}},
]}


def _sse(text, model):
    chunk = {"id": "x", "object": "chat.completion.chunk", "model": model,
             "choices": [{"index": 0, "delta": {"role": "assistant", "content": text},
                          "finish_reason": None}]}
    done = {"id": "x", "object": "chat.completion.chunk", "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}
    return (f"data: {json.dumps(chunk)}\n\ndata: {json.dumps(done)}\n\ndata: [DONE]\n\n").encode()


def _tool_round(model):
    """One round of a step that asks for a tool (``ls``) and reports 10 in / 5 out."""
    call = {"index": 0, "id": "call_1", "type": "function",
            "function": {"name": "ls", "arguments": json.dumps({"path": "."})}}
    first = {"id": "x", "object": "chat.completion.chunk", "model": model,
             "choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [call]},
                          "finish_reason": None}]}
    last = {"id": "x", "object": "chat.completion.chunk", "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
    return (f"data: {json.dumps(first)}\n\ndata: {json.dumps(last)}\n\ndata: [DONE]\n\n").encode()


class Network:
    """What each host does when the step calls it. Records who was actually hit."""

    def __init__(self):
        self.groq = "ok"
        self.hits = []
        self.error_body = "simulated"
        self.groq_calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.hits.append(request.url.host)
        if request.url.host == "api.groq.com":
            self.groq_calls += 1
            mode = self.groq
            if mode == "two_tool_rounds_then_429":
                # Two rounds that ask for a tool and spend 10/5 each, then a refusal.
                if self.groq_calls <= 2:
                    return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                          content=_tool_round("m-groq"))
                return httpx.Response(429, json={"error": {"message": self.error_body}})
            if mode == "ReadTimeout":
                raise httpx.ReadTimeout("simulated", request=request)
            if mode == "ConnectError":
                raise httpx.ConnectError("simulated", request=request)
            if mode != "ok":
                return httpx.Response(int(mode), json={"error": {"message": self.error_body}})
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=_sse("RESPUESTA_DE_GROQ", "m-groq"))
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=_sse("RESPUESTA_DE_OPENROUTER", "m-or:free"))


@pytest.fixture
def chain(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        for eid, url in (("groq", GROQ), ("openrouter", OPENROUTER)):
            session.add(cdb.ModelEndpoint(id=eid, name=eid, base_url=url, endpoint_kind="api",
                                          is_enabled=True))
        session.commit()
    monkeypatch.setattr(flow, "SessionLocal", factory)
    monkeypatch.setattr(router, "load_quota_config", lambda path=None: CONFIG)
    monkeypatch.setattr("src.tool_security.owner_is_admin_or_single_user", lambda owner: True)

    net = Network()
    client = httpx.AsyncClient(transport=httpx.MockTransport(net.handler))
    monkeypatch.setattr(llm_core, "_get_http_client", lambda *a, **k: client)
    # A connect failure cools the host process-wide; never let one case poison the next.
    for url in (GROQ, OPENROUTER):
        llm_core._clear_host_dead(url)
    yield net, factory, tmp_path
    for url in (GROQ, OPENROUTER):
        llm_core._clear_host_dead(url)
    engine.dispose()


def _config(workspace):
    return {"run_id": "run-1", "step_key": "constructor", "agent_id": "agent-1",
            "model": "m-groq", "owner": "admin", "name": "constructor",
            "workspace": str(workspace), "allowed_tools": ["glob", "grep", "ls", "read_file"],
            "instructions": "Answer briefly.", "instructions_version": 1,
            "require_tool_evidence": False, "max_rounds": 3,
            "candidates": [
                {"endpoint_id": "groq", "endpoint_url": GROQ, "model": "m-groq",
                 "host": "api.groq.com"},
                {"endpoint_id": "openrouter", "endpoint_url": OPENROUTER, "model": "m-or:free",
                 "host": "openrouter.ai"}]}


def _fallbacks(factory):
    with factory() as session:
        return [json.loads(e.payload) for e in session.query(cdb.CMHWorkflowEvent).filter(
            cdb.CMHWorkflowEvent.kind == "provider_fallback").all()]


async def test_a_healthy_first_candidate_answers_and_the_second_is_never_called(chain):
    """Positive control: without it, every failure case below could pass for the
    wrong reason (a harness that fails everything)."""
    net, factory, workspace = chain
    net.groq = "ok"
    config = _config(workspace)
    assert await flow.call_model(config, "p") == "RESPUESTA_DE_GROQ"
    assert config["resolved_endpoint_id"] == "groq"
    assert set(net.hits) == {"api.groq.com"}
    assert _fallbacks(factory) == []


@pytest.mark.parametrize("failure, reason", [
    ("429", "http:429"), ("402", "http:402"), ("408", "http:408"),
    ("500", "http:500"), ("503", "http:503"), ("529", "http:529"),
    ("ReadTimeout", "http:504"), ("ConnectError", "http:503"),
])
async def test_a_refusal_to_answer_moves_the_step_to_openrouter(chain, failure, reason):
    net, factory, workspace = chain
    net.groq = failure
    config = _config(workspace)
    assert await flow.call_model(config, "p") == "RESPUESTA_DE_OPENROUTER"
    assert config["resolved_endpoint_id"] == "openrouter"
    events = _fallbacks(factory)
    assert len(events) == 1
    assert events[0]["from"] == "groq" and events[0]["to"] == "openrouter"
    assert events[0]["reason"] == reason
    assert "openrouter.ai" in net.hits


@pytest.mark.parametrize("failure", ["400", "401", "403", "404"])
async def test_a_configuration_fault_stops_the_step_where_it_happened(chain, failure):
    """ADR-020: a 401 or a 400 is a defect the next provider would meet too."""
    net, factory, workspace = chain
    net.groq = failure
    with pytest.raises(RuntimeError):
        await flow.call_model(_config(workspace), "p")
    assert set(net.hits) == {"api.groq.com"}
    assert _fallbacks(factory) == []


# --- quota: what the step actually spent -------------------------------------
#
# Quota used to be charged once per SUCCESSFUL step, with requests=1 and no
# tokens. tpm and tpd could never fire, rpm and rpd counted steps instead of
# requests (a step makes up to max_rounds of them), and a refused call was never
# counted at all. The loop reports its totals in ONE model_metrics event at the
# end of an attempt: tokens summed over every round, and the number of rounds.

from src.cmh_provider_router import usage_snapshot  # noqa: E402


def _day(factory, endpoint_id):
    with factory() as session:
        return usage_snapshot(session, endpoint_id)["day"]


async def test_a_successful_step_charges_the_tokens_and_requests_the_loop_reported(chain):
    net, factory, workspace = chain
    assert await flow.call_model(_config(workspace), "p") == "RESPUESTA_DE_GROQ"
    day = _day(factory, "groq")
    assert (day["requests"], day["tokens_in"], day["tokens_out"]) == (1, 3, 2)


async def test_a_refused_attempt_costs_one_request_and_no_tokens_and_the_answer_is_charged(chain):
    net, factory, workspace = chain
    net.groq = "429"
    assert await flow.call_model(_config(workspace), "p") == "RESPUESTA_DE_OPENROUTER"
    refused, answered = _day(factory, "groq"), _day(factory, "openrouter")
    assert (refused["requests"], refused["tokens_in"], refused["tokens_out"]) == (1, 0, 0)
    assert (answered["requests"], answered["tokens_in"], answered["tokens_out"]) == (1, 3, 2)


async def test_an_attempt_that_dies_mid_run_is_charged_what_it_spent(chain):
    """Groq answers two tool rounds (10 in / 5 out each) and refuses the third. Three
    requests reached it and 20 / 10 tokens were spent; the step used to be charged one
    request and nothing, because only a loop that FINISHES sends its totals. That
    under-counted exactly the windows (tpm, tpd, rpd) the router protects."""
    net, factory, workspace = chain
    net.groq = "two_tool_rounds_then_429"
    assert await flow.call_model(_config(workspace), "p") == "RESPUESTA_DE_OPENROUTER"
    assert net.groq_calls == 3
    day = _day(factory, "groq")
    assert (day["requests"], day["tokens_in"], day["tokens_out"]) == (3, 20, 10)
    answered = _day(factory, "openrouter")
    assert (answered["requests"], answered["tokens_in"], answered["tokens_out"]) == (1, 3, 2)


async def test_a_provider_error_body_never_reaches_the_exception_or_the_events(chain):
    """ADR-011: a provider's 401 can echo part of the key it rejected, and the message
    ends up in a step's error column and in the SSE stream. Only the integer is kept."""
    net, factory, workspace = chain
    net.groq = "401"
    secret = "sk-SENTINEL-KEY-123456"
    net.error_body = f"Incorrect API key provided: {secret}."
    with pytest.raises(RuntimeError) as caught:
        await flow.call_model(_config(workspace), "p")
    assert getattr(caught.value, "status_code", None) == 401
    assert secret not in str(caught.value) and secret not in repr(caught.value.args)
    with factory() as session:
        stored = " ".join(e.payload for e in session.query(cdb.CMHWorkflowEvent).all())
    assert secret not in stored


async def test_a_token_limit_now_takes_a_provider_out_of_the_list(chain, monkeypatch):
    """tpd used to be dead: nothing ever wrote a token. Groq's limit here is 10
    tokens at a 0.9 threshold, so it is usable at 0 and at 5 and gone at 10."""
    net, factory, workspace = chain
    limited = {"threshold": 0.9, "providers": [
        {"endpoint_host": "api.groq.com", "order": 1, "model": "m-groq", "limits": {"tpd": 10}},
        {"endpoint_host": "openrouter.ai", "order": 2, "model": "m-or:free", "limits": {}}]}
    monkeypatch.setattr(router, "load_quota_config", lambda path=None: limited)
    answers = [await flow.call_model(_config(workspace), "p") for _ in range(3)]
    assert answers == ["RESPUESTA_DE_GROQ", "RESPUESTA_DE_GROQ", "RESPUESTA_DE_OPENROUTER"]
    assert net.hits.count("api.groq.com") == 2  # the third never reached Groq
    assert [e["reason"] for e in _fallbacks(factory)] == ["quota:tpd"]


async def test_rounds_are_charged_as_requests_not_one_per_step(chain, monkeypatch):
    net, factory, workspace = chain

    async def fake(config, candidate, prompt, record):
        record("model_metrics", metrics={"input_tokens": 100, "output_tokens": 40, "rounds": 3})
        return "artifact"

    monkeypatch.setattr(flow, "_run_one_candidate", fake)
    await flow.call_model(_config(workspace), "p")
    day = _day(factory, "groq")
    assert (day["requests"], day["tokens_in"], day["tokens_out"]) == (3, 100, 40)


async def test_an_attempt_that_fails_after_reporting_its_usage_is_not_charged_twice(
        chain, monkeypatch):
    """The evidence guard raises after the loop ended: the tokens were spent and
    reported, and adding 'the failed call' on top would count that call twice."""
    net, factory, workspace = chain

    async def fake(config, candidate, prompt, record):
        record("model_metrics", metrics={"input_tokens": 7, "output_tokens": 3, "rounds": 1})
        raise ValueError("answered without any successful tool call")

    monkeypatch.setattr(flow, "_run_one_candidate", fake)
    with pytest.raises(ValueError):
        await flow.call_model(_config(workspace), "p")
    day = _day(factory, "groq")
    assert (day["requests"], day["tokens_in"], day["tokens_out"]) == (1, 7, 3)


async def test_a_failing_quota_write_does_not_take_the_step_down(chain, monkeypatch):
    """N1 of an earlier round: a quota write that failed after the model had
    answered threw the artifact away."""
    net, factory, workspace = chain

    def broken(*args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(router, "record_usage", broken)
    assert await flow.call_model(_config(workspace), "p") == "RESPUESTA_DE_GROQ"


async def test_the_scheduler_forwards_how_many_rounds_the_reported_totals_cover(
        chain, monkeypatch):
    """The loop emits one metrics event with tokens summed over every round and one
    usage bucket per round. The buckets are not forwarded (per-route attribution has
    no business in an event); their COUNT is, because it is the number of requests."""
    import json as _json
    from types import SimpleNamespace
    from src.task_scheduler import TaskScheduler

    net, factory, workspace = chain
    metrics = {"input_tokens": 30, "output_tokens": 9, "total_tokens": 39,
               "usage_buckets": [{"input_tokens": 10}, {"input_tokens": 10}, {"input_tokens": 10}]}

    async def fake_stream(**kwargs):
        yield f'data: {_json.dumps({"type": "metrics", "data": metrics})}\n\n'
        yield 'data: {"delta": "hola"}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr("src.agent_loop.stream_agent_loop", fake_stream)
    seen = []
    task = SimpleNamespace(owner="admin", name="t", prompt="p", workspace=str(workspace),
                           allowed_tools=_json.dumps(["read_file"]), max_steps=3)
    await TaskScheduler(None)._run_agent_loop(
        GROQ, "m-groq", task, "sid", system_prompt="s", override_user_message="p",
        foreground_controlled=True, require_tool_evidence=False,
        event_sink=lambda kind, **payload: seen.append((kind, payload)))
    forwarded = [payload["metrics"] for kind, payload in seen if kind == "model_metrics"]
    assert len(forwarded) == 1
    assert forwarded[0]["rounds"] == 3
    assert (forwarded[0]["input_tokens"], forwarded[0]["output_tokens"]) == (30, 9)
    assert "usage_buckets" not in forwarded[0]
