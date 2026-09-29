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


class Network:
    """What each host does when the step calls it. Records who was actually hit."""

    def __init__(self):
        self.groq = "ok"
        self.hits = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.hits.append(request.url.host)
        if request.url.host == "api.groq.com":
            mode = self.groq
            if mode == "ReadTimeout":
                raise httpx.ReadTimeout("simulated", request=request)
            if mode == "ConnectError":
                raise httpx.ConnectError("simulated", request=request)
            if mode != "ok":
                return httpx.Response(int(mode), json={"error": {"message": "simulated"}})
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
