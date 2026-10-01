"""OpenRouter's model is discovered when a run is created, and the second link of
the chain finally enters the frozen list.

``config/cmh_free_quotas.json`` gives OpenRouter ``model: null`` because the free
catalogue turns over, and ``resolve_candidates`` skips a provider without a model.
Nothing ever filled it in: ``pick_openrouter_free_model`` had no caller outside its
own tests, so with U1, U2 and U4 done the real chain was Groq -> LM Studio and the
blueprint's Groq -> OpenRouter -> LM Studio existed only on paper.

Only the network is fake, through ``llm_core._get_http_client``. The key is a
recognisable dummy so the tests can prove it is sent as a header and appears in
no note, no event and no frozen config.
"""

import asyncio
import json
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as cdb
import src.cmh_provider_router as router
import src.llm_core as llm_core
from routes import cmh_control_routes as control
from routes import cmh_workflow_routes as routes
from src import cmh_workflows as flow
from src.cmh_provider_router import (
    FREE_CLOUD_FIRST, discover_free_models, resolve_candidates,
)

SECRET = "sk-or-DUMMY-KEY-FOR-TESTS"
GROQ = "https://api.groq.com/openai/v1"
OPENROUTER = "https://openrouter.ai/api/v1"
LOCAL = "http://127.0.0.1:59999/v1"
USER_PATH = "/api/v1/models/user"
GENERAL_PATH = "/api/v1/models"
T0 = datetime(2026, 9, 29, 12, 0)

CONFIG = {
    "threshold": 0.9,
    "discovery": {"ttl_s": 21600, "timeout_s": 15},
    "providers": [
        {"endpoint_host": "api.groq.com", "order": 1, "model": "openai/gpt-oss-120b", "limits": {}},
        {"endpoint_host": "openrouter.ai", "order": 2, "model": None, "limits": {}},
    ],
}


def _model(model_id, context, tools=True):
    return {"id": model_id, "context_length": context,
            "supported_parameters": ["tools", "temperature"] if tools else ["temperature"]}


CATALOGUE = {"data": [
    _model("small/model:free", 8_000),
    _model("big/model:free", 128_000),
    _model("huge/model", 1_000_000),              # not :free
    _model("huger/model:free", 2_000_000, tools=False),  # no tool calling
]}


class Catalogue:
    """What OpenRouter answers on each path, and who asked."""

    def __init__(self):
        self.responses = {}
        self.requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append((path, request.headers.get("authorization")))
        outcome = self.responses.get(path)
        if callable(outcome):
            raise outcome(request)
        if outcome is None:
            return httpx.Response(404, json={"error": "not found"})
        status, body = outcome
        return httpx.Response(status, json=body)

    def paths(self):
        return [p for p, _ in self.requests]


@pytest.fixture
def world(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(cdb.ModelEndpoint(id="groq", name="groq", base_url=GROQ,
                                      endpoint_kind="api", is_enabled=True, api_key="gsk-DUMMY"))
        session.add(cdb.ModelEndpoint(id="orr", name="orr", base_url=OPENROUTER,
                                      endpoint_kind="api", is_enabled=True, api_key=SECRET))
        session.add(cdb.ModelEndpoint(id="lms", name="lms", base_url=LOCAL,
                                      endpoint_kind="local", is_enabled=True,
                                      cached_models=json.dumps(["cmh-local"])))
        session.commit()
    net = Catalogue()
    client = httpx.AsyncClient(transport=httpx.MockTransport(net.handler))
    monkeypatch.setattr(llm_core, "_get_http_client", lambda *a, **k: client)
    router.clear_discovery_cache()
    yield factory, net, tmp_path
    router.clear_discovery_cache()
    engine.dispose()


# --- what discovery asks, and in which order --------------------------------

async def test_the_accounts_own_list_is_asked_first_and_its_pick_follows_the_rule(world):
    factory, net, _ = world
    net.responses[USER_PATH] = (200, CATALOGUE)
    with factory() as db:
        found, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert found == {"openrouter.ai": "big/model:free"}  # longest context among :free WITH tools
    assert net.paths() == [USER_PATH]
    assert notes == [{"provider": "openrouter.ai", "outcome": "ok", "model": "big/model:free",
                      "source": "models/user", "reason": None}]


async def test_the_key_travels_as_a_header_and_appears_in_no_note(world):
    factory, net, _ = world
    net.responses[USER_PATH] = (200, CATALOGUE)
    with factory() as db:
        _, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert net.requests[0][1] == f"Bearer {SECRET}"
    assert SECRET not in json.dumps(notes)


async def test_the_general_list_is_used_only_when_the_accounts_list_is_not_there(world):
    factory, net, _ = world
    net.responses[GENERAL_PATH] = (200, CATALOGUE)  # /models/user answers 404
    with factory() as db:
        found, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert found == {"openrouter.ai": "big/model:free"}
    assert net.paths() == [USER_PATH, GENERAL_PATH]
    assert notes[0]["source"] == "models"
    assert "404" in notes[0]["reason"] and "sin el filtro de la cuenta" in notes[0]["reason"]


async def test_an_empty_accounts_list_does_not_widen_to_the_general_one(world):
    """A 200 with nothing eligible is the account saying no. Asking the unfiltered
    catalogue would pick a model the account's own privacy settings exclude."""
    factory, net, _ = world
    net.responses[USER_PATH] = (200, {"data": [_model("huge/model", 1_000_000)]})
    net.responses[GENERAL_PATH] = (200, CATALOGUE)  # would offer a good one
    with factory() as db:
        found, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert found == {}
    assert GENERAL_PATH not in net.paths()
    assert notes[0]["outcome"] == "failed" and "account" in notes[0]["reason"]


# --- the general list is a fallback for a missing route, not for a failing one -----

@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
async def test_a_failing_accounts_list_does_not_widen_to_the_general_one(world, status):
    """ADR-028 says the general list is used 'only if that route does not exist'.
    Every non-200 used to widen it, and the choice was then cached for six hours as if
    the account's filter had been applied."""
    factory, net, _ = world
    net.responses[USER_PATH] = (status, {"error": "no"})
    net.responses[GENERAL_PATH] = (200, CATALOGUE)      # would offer a model the account excludes
    with factory() as db:
        found, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert found == {}
    assert net.paths() == [USER_PATH]
    assert notes[0]["outcome"] == "failed" and notes[0]["reason"] == f"http:{status}"


@pytest.mark.parametrize("error, reason", [
    (lambda request: httpx.ReadTimeout("slow", request=request), "connection:ReadTimeout"),
    (lambda request: httpx.ConnectTimeout("slow", request=request), "connection:ConnectTimeout"),
    (lambda request: httpx.RemoteProtocolError("garbled", request=request),
     "connection:RemoteProtocolError"),
])
async def test_any_network_failure_of_the_accounts_list_leaves_the_provider_out(world, error, reason):
    """ReadTimeout is the failure timeout_s exists for; narrowing the except to
    ConnectError let it escape create_run and no test noticed."""
    factory, net, _ = world
    net.responses[USER_PATH] = error
    net.responses[GENERAL_PATH] = (200, CATALOGUE)
    with factory() as db:
        found, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert found == {} and net.paths() == [USER_PATH]
    assert notes[0]["reason"] == reason


async def test_a_200_that_is_not_json_is_reported_and_does_not_widen(world, monkeypatch):
    factory, net, _ = world

    def handler(request):
        net.requests.append((request.url.path, request.headers.get("authorization")))
        if request.url.path == USER_PATH:
            return httpx.Response(200, content=b"<html>not json</html>")
        return httpx.Response(200, json=CATALOGUE)

    monkeypatch.setattr(llm_core, "_get_http_client",
                        lambda *a, **k: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with factory() as db:
        found, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert found == {} and notes[0]["reason"] == "invalid json"
    assert GENERAL_PATH not in net.paths()


@pytest.mark.parametrize("payload", [{"data": 5}, {"data": None}, {"data": "x"}, [], 7,
                                     {"data": [{"id": "a:free", "supported_parameters": "tools"}]}])
async def test_a_payload_of_the_wrong_shape_is_no_model_and_no_exception(world, payload):
    factory, net, _ = world
    net.responses[USER_PATH] = (200, payload)
    with factory() as db:
        found, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert found == {} and notes[0]["outcome"] == "failed"
    assert notes[0]["reason"] == "no eligible model in the account's own list"


def test_an_infinite_context_length_does_not_break_the_pick():
    """int(float('inf')) is an OverflowError, and 1e999 parses to inf."""
    entry = {"id": "x/y:free", "supported_parameters": ["tools"], "context_length": float("inf")}
    assert router.pick_openrouter_free_model({"data": [entry]}) == "x/y:free"


async def test_a_rule_that_raises_is_a_failed_discovery_not_a_failed_run(world, monkeypatch):
    factory, net, _ = world
    net.responses[USER_PATH] = (200, CATALOGUE)

    def broken(payload):
        raise TypeError("boom")

    monkeypatch.setitem(router._DISCOVERY_RULES, "openrouter.ai", broken)
    with factory() as db:
        found, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert found == {} and notes[0]["reason"] == "unexpected payload:TypeError"


# --- nothing is sent without the key, nor over http, nor to a malformed URL ---------

@pytest.mark.parametrize("key", [None, "", "   "])
async def test_no_key_means_no_request_and_the_note_says_so(world, key):
    factory, net, _ = world
    net.responses[USER_PATH] = (200, CATALOGUE)
    with factory() as db:
        db.get(cdb.ModelEndpoint, "orr").api_key = key
        db.commit()
        found, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert found == {} and net.requests == []
    assert notes[0]["outcome"] == "failed" and notes[0]["reason"] == "no api key"


async def test_the_key_is_never_sent_over_plain_http(world):
    factory, net, _ = world
    net.responses[USER_PATH] = (200, CATALOGUE)
    with factory() as db:
        db.get(cdb.ModelEndpoint, "orr").base_url = "http://openrouter.ai/api/v1"
        db.commit()
        found, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert found == {} and net.requests == []
    assert notes[0]["reason"] == "not https"


@pytest.mark.parametrize("url", ["https://openrouter.ai:notaport/api/v1",
                                 "https://openrouter.ai:99999999/api/v1"])
async def test_a_malformed_base_url_leaves_the_provider_out_instead_of_failing_the_run(world, url):
    factory, net, _ = world
    with factory() as db:
        db.get(cdb.ModelEndpoint, "orr").base_url = url
        db.commit()
        found, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert found == {} and net.requests == []
    assert notes[0]["outcome"] == "failed" and notes[0]["reason"] == "invalid url"


# --- the knobs: read from the config, validated, and the timeout is a total ---------

@pytest.mark.parametrize("bad", [None, 0, -5, True, "15", float("inf"), float("nan"), [], {}])
def test_a_knob_that_is_not_a_positive_number_falls_back_to_the_default(bad):
    for name in ("ttl_s", "timeout_s", "failure_ttl_s", "unfiltered_ttl_s"):
        knobs = router.discovery_knobs({"discovery": {name: bad}})
        assert knobs == router._DEFAULT_DISCOVERY, (name, bad)


def test_a_valid_knob_replaces_the_default_and_an_unknown_one_is_ignored():
    knobs = router.discovery_knobs({"discovery": {"ttl_s": 1000, "timeout_s": 7.5, "novel": 3}})
    assert knobs["ttl_s"] == 1000.0 and knobs["timeout_s"] == 7.5
    assert "novel" not in knobs


async def test_a_null_ttl_in_the_config_does_not_fail_after_a_successful_discovery(world):
    factory, net, _ = world
    net.responses[USER_PATH] = (200, CATALOGUE)
    with factory() as db:
        found, _ = await discover_free_models(
            db, config={**CONFIG, "discovery": {"ttl_s": None, "timeout_s": None}}, at=T0)
    assert found == {"openrouter.ai": "big/model:free"}


async def test_the_ttl_comes_from_the_config_and_its_edges_hold(world):
    factory, net, _ = world
    net.responses[USER_PATH] = (200, CATALOGUE)
    config = {**CONFIG, "discovery": {"ttl_s": 1000, "timeout_s": 15}}   # not the default
    with factory() as db:
        await discover_free_models(db, config=config, at=T0)
        _, at_edge = await discover_free_models(db, config=config, at=T0 + timedelta(seconds=999))
        assert at_edge[0]["outcome"] == "cached" and len(net.requests) == 1
        _, past = await discover_free_models(db, config=config, at=T0 + timedelta(seconds=1001))
    assert past[0]["outcome"] == "ok" and len(net.requests) == 2


async def test_a_failure_is_remembered_briefly_and_then_asked_again(world):
    """While a provider is down every new run used to wait the full timeout again."""
    factory, net, _ = world
    with factory() as db:                                      # both routes answer 404
        await discover_free_models(db, config=CONFIG, at=T0)
        asked = len(net.requests)
        _, recent = await discover_free_models(db, config=CONFIG, at=T0 + timedelta(seconds=59))
        assert len(net.requests) == asked
        assert recent[0]["outcome"] == "failed" and "fallo reciente" in recent[0]["reason"]
        net.responses[USER_PATH] = (200, CATALOGUE)
        found, later = await discover_free_models(db, config=CONFIG,
                                                  at=T0 + timedelta(seconds=61))
    assert found == {"openrouter.ai": "big/model:free"} and later[0]["outcome"] == "ok"


async def test_the_failure_ttl_comes_from_the_config_and_its_edges_hold(world):
    """Only ttl_s, timeout_s and unfiltered_ttl_s were pinned to values other than the defaults:
    a failure_ttl_s read from the code's constant instead of the config passed every test."""
    factory, net, _ = world
    config = {**CONFIG, "discovery": {"ttl_s": 21600, "timeout_s": 15, "failure_ttl_s": 10}}
    with factory() as db:
        await discover_free_models(db, config=config, at=T0)           # both routes answer 404
        asked = len(net.requests)
        _, inside = await discover_free_models(db, config=config, at=T0 + timedelta(seconds=9))
        assert inside[0]["outcome"] == "failed" and len(net.requests) == asked
        net.responses[USER_PATH] = (200, CATALOGUE)
        found, outside = await discover_free_models(db, config=config, at=T0 + timedelta(seconds=11))
    assert found == {"openrouter.ai": "big/model:free"} and outside[0]["outcome"] == "ok"


async def test_a_choice_from_the_unfiltered_list_is_trusted_for_a_shorter_time(world):
    factory, net, _ = world
    net.responses[GENERAL_PATH] = (200, CATALOGUE)              # /models/user answers 404
    config = {**CONFIG, "discovery": {"ttl_s": 21600, "timeout_s": 15, "unfiltered_ttl_s": 100}}
    with factory() as db:
        _, first = await discover_free_models(db, config=config, at=T0)
        assert first[0]["source"] == "models" and "404" in first[0]["reason"]
        before = len(net.requests)
        _, inside = await discover_free_models(db, config=config, at=T0 + timedelta(seconds=99))
        assert inside[0]["outcome"] == "cached" and len(net.requests) == before
        _, outside = await discover_free_models(db, config=config, at=T0 + timedelta(seconds=101))
    assert outside[0]["outcome"] == "ok" and len(net.requests) > before


async def test_rotating_the_key_does_not_serve_the_previous_accounts_model(world):
    factory, net, _ = world
    net.responses[USER_PATH] = (200, CATALOGUE)
    with factory() as db:
        await discover_free_models(db, config=CONFIG, at=T0)
        db.get(cdb.ModelEndpoint, "orr").api_key = "sk-or-ROTATED-KEY"
        db.commit()
        _, notes = await discover_free_models(db, config=CONFIG, at=T0 + timedelta(hours=1))
    assert notes[0]["outcome"] == "ok" and len(net.requests) == 2
    assert net.requests[1][1] == "Bearer sk-or-ROTATED-KEY"


async def test_timeout_s_is_passed_to_the_request(world, monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.extensions["timeout"])
        return httpx.Response(200, json=CATALOGUE)

    factory, _, _ = world
    monkeypatch.setattr(llm_core, "_get_http_client",
                        lambda *a, **k: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    config = {**CONFIG, "discovery": {"ttl_s": 21600, "timeout_s": 7}}
    with factory() as db:
        await discover_free_models(db, config=config, at=T0)
    assert seen == [{"connect": 7.0, "read": 7.0, "write": 7.0, "pool": 7.0}]


async def test_timeout_s_bounds_the_whole_discovery_even_if_the_server_drips(world, monkeypatch):
    """httpx applies its timeout per phase: a server that keeps answering slowly never
    trips it. The total budget is enforced around the whole attempt."""
    async def slow(request):
        await asyncio.sleep(5)
        return httpx.Response(200, json=CATALOGUE)

    factory, _, _ = world
    monkeypatch.setattr(llm_core, "_get_http_client",
                        lambda *a, **k: httpx.AsyncClient(transport=httpx.MockTransport(slow)))
    config = {**CONFIG, "discovery": {"ttl_s": 21600, "timeout_s": 0.2}}
    started = asyncio.get_running_loop().time()
    with factory() as db:
        found, notes = await discover_free_models(db, config=config, at=T0)
    assert asyncio.get_running_loop().time() - started < 2
    assert found == {} and notes[0]["reason"] == "timeout"


async def test_an_invalid_url_error_from_the_client_is_a_failed_discovery(world, monkeypatch):
    """httpx.InvalidURL is not an httpx.HTTPError: narrowing to HTTPError alone would
    let it escape create_run."""
    factory, net, _ = world

    class Client:
        async def get(self, *args, **kwargs):
            raise httpx.InvalidURL("bad url")

    monkeypatch.setattr(llm_core, "_get_http_client", lambda *a, **k: Client())
    with factory() as db:
        found, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert found == {} and notes[0]["reason"] == "invalid url"


async def test_repointing_the_row_does_not_serve_the_model_of_the_previous_url(world):
    factory, net, _ = world
    net.responses[USER_PATH] = (200, CATALOGUE)
    with factory() as db:
        await discover_free_models(db, config=CONFIG, at=T0)
        db.get(cdb.ModelEndpoint, "orr").base_url = "https://openrouter.ai/api/v2"
        db.commit()
        _, notes = await discover_free_models(db, config=CONFIG, at=T0 + timedelta(hours=1))
    assert notes[0]["outcome"] != "cached"


async def test_timeout_s_reaches_the_second_request_too(world, monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.extensions["timeout"])
        if request.url.path == USER_PATH:
            return httpx.Response(404, json={"error": "no such route"})
        return httpx.Response(200, json=CATALOGUE)

    factory, _, _ = world
    monkeypatch.setattr(llm_core, "_get_http_client",
                        lambda *a, **k: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    config = {**CONFIG, "discovery": {"ttl_s": 21600, "timeout_s": 7}}
    with factory() as db:
        await discover_free_models(db, config=config, at=T0)
    assert seen == [{"connect": 7.0, "read": 7.0, "write": 7.0, "pool": 7.0}] * 2


# --- failures leave the provider out and say why ----------------------------

async def test_a_rejected_key_fails_the_discovery_and_says_why_without_the_key(world):
    factory, net, _ = world
    net.responses[USER_PATH] = (401, {"error": "bad key"})
    net.responses[GENERAL_PATH] = (401, {"error": "bad key"})
    with factory() as db:
        found, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert found == {}
    assert notes[0]["outcome"] == "failed" and notes[0]["reason"] == "http:401"
    assert net.paths() == [USER_PATH]      # a rejection is not "the route is missing"
    assert SECRET not in json.dumps(notes)


async def test_a_network_failure_does_not_raise_and_is_reported(world):
    factory, net, _ = world
    net.responses[USER_PATH] = lambda request: httpx.ConnectError("simulated", request=request)
    net.responses[GENERAL_PATH] = lambda request: httpx.ConnectError("simulated", request=request)
    with factory() as db:
        found, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert found == {}
    assert notes[0]["reason"] == "connection:ConnectError"


# --- cost, cache, precedence -------------------------------------------------

async def test_the_result_is_reused_within_the_ttl_and_asked_again_after_it(world):
    factory, net, _ = world
    net.responses[USER_PATH] = (200, CATALOGUE)
    with factory() as db:
        await discover_free_models(db, config=CONFIG, at=T0)
        found, notes = await discover_free_models(db, config=CONFIG, at=T0 + timedelta(hours=1))
        assert found == {"openrouter.ai": "big/model:free"}
        assert notes[0]["outcome"] == "cached"
        assert len(net.requests) == 1
        await discover_free_models(db, config=CONFIG, at=T0 + timedelta(hours=7))
    assert len(net.requests) == 2


async def test_a_model_written_in_the_config_is_never_asked_for_nor_replaced(world):
    factory, net, _ = world
    pinned = json.loads(json.dumps(CONFIG))
    pinned["providers"][1]["model"] = "pinned/model:free"
    with factory() as db:
        found, notes = await discover_free_models(db, config=pinned, at=T0)
        candidates = resolve_candidates(db, FREE_CLOUD_FIRST, config=pinned,
                                        discovered={"openrouter.ai": "other/model:free"})
    assert found == {} and notes == [] and net.requests == []
    assert [c["model"] for c in candidates if c["endpoint_id"] == "orr"] == ["pinned/model:free"]


async def test_no_registered_account_means_no_request(world):
    factory, net, _ = world
    with factory() as db:
        db.query(cdb.ModelEndpoint).filter(cdb.ModelEndpoint.id == "orr").delete()
        db.commit()
        found, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert found == {} and notes == [] and net.requests == []


def test_a_discovered_model_enters_second_and_a_missing_one_leaves_the_provider_out(world):
    factory, _, _ = world
    with factory() as db:
        with_it = resolve_candidates(db, FREE_CLOUD_FIRST, config=CONFIG,
                                     discovered={"openrouter.ai": "big/model:free"})
        without = resolve_candidates(db, FREE_CLOUD_FIRST, config=CONFIG)
    assert [c["endpoint_id"] for c in with_it] == ["groq", "orr", "lms"]
    assert [c["endpoint_id"] for c in without] == ["groq", "lms"]


def test_a_row_that_still_carries_a_credential_is_not_frozen_and_is_reported(world):
    """A row written before ADR-026, or edited through a path that did not split the URL,
    still has user:pass@ in its base_url. Freezing it would persist the credential;
    stripping it would leave the runner unable to find the row by URL, so the step would
    go out with no Authorization (the URL form authenticated). It is left out, and said."""
    factory, _, _ = world
    with factory() as db:
        db.get(cdb.ModelEndpoint, "orr").base_url = "https://revuser:hunter2@openrouter.ai/api/v1"
        db.get(cdb.ModelEndpoint, "lms").base_url = "http://lmsuser:hunter2@127.0.0.1:59999/v1"
        db.commit()
        dropped = []
        candidates = resolve_candidates(db, FREE_CLOUD_FIRST, config=CONFIG, dropped=dropped,
                                        discovered={"openrouter.ai": "big/model:free"})
    assert [c["endpoint_id"] for c in candidates] == ["groq"]
    assert "hunter2" not in json.dumps(candidates)
    assert sorted((d["endpoint_id"], d["reason"]) for d in dropped) == [
        ("lms", "credential_in_url"), ("orr", "credential_in_url")]


def test_a_free_host_over_plain_http_is_dropped_by_the_gate_and_reported(world):
    factory, _, _ = world
    with factory() as db:
        db.get(cdb.ModelEndpoint, "groq").base_url = "http://api.groq.com/openai/v1"
        db.commit()
        dropped = []
        candidates = resolve_candidates(db, FREE_CLOUD_FIRST, config=CONFIG, dropped=dropped,
                                        discovered={"openrouter.ai": "big/model:free"})
    assert [c["endpoint_id"] for c in candidates] == ["orr", "lms"]
    assert dropped == [{"endpoint_id": "groq", "host": "api.groq.com", "reason": "cost_gate"}]


def test_the_list_is_the_same_when_nobody_asks_for_the_dropped_rows(world):
    factory, _, _ = world
    with factory() as db:
        db.get(cdb.ModelEndpoint, "groq").base_url = "http://api.groq.com/openai/v1"
        db.commit()
        assert [c["endpoint_id"] for c in resolve_candidates(db, FREE_CLOUD_FIRST, config=CONFIG)] == [
            "lms"]


async def test_discovery_does_not_query_a_url_that_carries_a_credential(world):
    factory, net, _ = world
    net.responses[USER_PATH] = (200, CATALOGUE)
    with factory() as db:
        db.get(cdb.ModelEndpoint, "orr").base_url = "https://u:p@openrouter.ai/api/v1"
        db.commit()
        found, notes = await discover_free_models(db, config=CONFIG, at=T0)
    assert found == {} and net.requests == []
    assert notes[0]["reason"] == "credential in url"


def test_the_cost_gate_still_refuses_a_discovered_model_that_is_not_free(world):
    factory, _, _ = world
    with factory() as db:
        candidates = resolve_candidates(db, FREE_CLOUD_FIRST, config=CONFIG,
                                        discovered={"openrouter.ai": "huge/model"})
    assert "orr" not in [c["endpoint_id"] for c in candidates]


def test_the_shipped_config_declares_the_discovery_knobs_and_leaves_openrouter_open():
    """The file is what runs. A rule with no knob would fall back to code constants."""
    settings = router.load_quota_config()
    assert set(settings["discovery"]) == {"ttl_s", "timeout_s", "failure_ttl_s",
                                          "unfiltered_ttl_s"}
    assert router.discovery_knobs(settings) == {k: float(v) for k, v in settings["discovery"].items()}
    openrouter = router.provider_for_host(settings, "openrouter.ai")
    assert openrouter["model"] is None


# --- through create_run ------------------------------------------------------

@pytest.fixture
def api(world, monkeypatch):
    factory, net, tmp_path = world
    monkeypatch.setattr(flow, "SessionLocal", factory)
    monkeypatch.setattr(routes, "SessionLocal", factory)
    monkeypatch.setattr(routes, "catalog", lambda: [{"id": "project"}])
    monkeypatch.setattr(control, "owner_is_admin_or_single_user", lambda owner: owner == "admin")
    monkeypatch.setattr(routes, "validate_task_tools", lambda tools, owner: set(tools))
    monkeypatch.setattr(routes, "validate_task_workspace",
                        lambda workspace, owner, persisted=True: workspace)

    async def fake(config, prompt):
        return "artifact"

    monkeypatch.setattr(flow, "call_model", fake)
    with factory() as db:
        db.add(cdb.ScheduledTask(id="task-a", owner="admin", name="a", task_type="llm",
                                 endpoint_url=GROQ, model="openai/gpt-oss-120b",
                                 prompt="unused", status="paused"))
        db.add(cdb.CMHAgent(id="agent-a", owner="admin", name="a", project_id="project",
                            role="a", instructions="a", model="openai/gpt-oss-120b",
                            allowed_tools=json.dumps(["read_file"]), workspace=str(tmp_path),
                            status="active", task_id="task-a"))
        db.commit()
    app = FastAPI()

    @app.middleware("http")
    async def as_admin(request, call_next):
        request.state.current_user = "admin"
        return await call_next(request)

    app.include_router(routes.setup_cmh_workflow_routes())
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    yield client, factory, net
    flow._ACTIVE.clear()


async def _create_run(client):
    definition = await client.post("/api/cmh/workflows", json={
        "name": "synthetic", "project_id": "project",
        "steps": [{"key": "a", "agent_id": "agent-a"}]})
    assert definition.status_code == 201, definition.text
    run = await client.post(f"/api/cmh/workflows/{definition.json()['id']}/runs",
                            json={"initial_input": "synthetic input"})
    assert run.status_code == 201, run.text
    run_id = run.json()["id"]
    for _ in range(200):
        if run_id not in flow._ACTIVE:
            break
        await asyncio.sleep(0.01)
    return run_id


def _stored(factory, run_id):
    with factory() as db:
        step = db.query(cdb.CMHWorkflowStep).filter(cdb.CMHWorkflowStep.run_id == run_id).one()
        events = [(e.kind, json.loads(e.payload)) for e in db.query(cdb.CMHWorkflowEvent).filter(
            cdb.CMHWorkflowEvent.run_id == run_id).all()]
        return step.config, events


async def test_a_run_freezes_openrouter_with_the_model_discovered_for_it(api):
    client, factory, net = api
    net.responses[USER_PATH] = (200, CATALOGUE)
    async with client:
        run_id = await _create_run(client)
    config, events = _stored(factory, run_id)
    frozen = json.loads(config)["candidates"]
    assert [(c["endpoint_id"], c["model"]) for c in frozen] == [
        ("groq", "openai/gpt-oss-120b"), ("orr", "big/model:free"), ("lms", "cmh-local")]
    discovery = [payload for kind, payload in events if kind == "provider_discovery"]
    assert discovery == [{"provider": "openrouter.ai", "outcome": "ok", "model": "big/model:free",
                          "source": "models/user", "reason": None}]
    assert SECRET not in config and SECRET not in json.dumps(events)


async def test_a_run_is_refused_when_a_registered_row_still_carries_a_credential(api):
    client, factory, net = api
    with factory() as db:
        db.get(cdb.ModelEndpoint, "lms").base_url = "http://lmsuser:hunter2@127.0.0.1:59999/v1"
        db.commit()
    async with client:
        definition = await client.post("/api/cmh/workflows", json={
            "name": "synthetic", "project_id": "project",
            "steps": [{"key": "a", "agent_id": "agent-a"}]})
        refused = await client.post(f"/api/cmh/workflows/{definition.json()['id']}/runs",
                                    json={"initial_input": "synthetic input"})
    assert refused.status_code == 400, refused.text
    assert "credenciales" in refused.json()["detail"] and "lms" in refused.json()["detail"]
    assert "hunter2" not in refused.text
    with factory() as db:
        assert db.query(cdb.CMHWorkflowRun).count() == 0


async def test_a_provider_the_gate_left_out_leaves_an_event_in_the_run(api, monkeypatch):
    """An OpenRouter row registered over plain http vanished from the frozen list without a
    trace. Its model is pinned in the config so that discovery is not what leaves it out."""
    client, factory, net = api
    pinned = {"threshold": 0.9, "discovery": {"ttl_s": 21600, "timeout_s": 15}, "providers": [
        {"endpoint_host": "api.groq.com", "order": 1, "model": "openai/gpt-oss-120b", "limits": {}},
        {"endpoint_host": "openrouter.ai", "order": 2, "model": "pinned/model:free", "limits": {}}]}
    monkeypatch.setattr(router, "load_quota_config", lambda path=None: pinned)
    with factory() as db:
        db.get(cdb.ModelEndpoint, "orr").base_url = "http://openrouter.ai/api/v1"
        db.commit()
    async with client:
        run_id = await _create_run(client)
    config, events = _stored(factory, run_id)
    dropped = [payload for kind, payload in events if kind == "provider_dropped"]
    assert dropped == [{"endpoint_id": "orr", "host": "openrouter.ai", "reason": "cost_gate"}]
    assert "orr" not in [c["endpoint_id"] for c in json.loads(config)["candidates"]]


async def test_a_failed_discovery_still_creates_the_run_and_the_event_says_why(api):
    client, factory, net = api
    net.responses[USER_PATH] = (401, {"error": "bad key"})
    net.responses[GENERAL_PATH] = (401, {"error": "bad key"})
    async with client:
        run_id = await _create_run(client)
    config, events = _stored(factory, run_id)
    assert "orr" not in [c["endpoint_id"] for c in json.loads(config)["candidates"]]
    discovery = [payload for kind, payload in events if kind == "provider_discovery"]
    assert len(discovery) == 1 and discovery[0]["outcome"] == "failed"
    assert discovery[0]["reason"] == "http:401"
    assert SECRET not in config and SECRET not in json.dumps(events)


# --- the local candidate has its own model name ------------------------------
#
# A Groq agent carries `openai/gpt-oss-120b`. That name means something only on
# Groq. Calling the local fallback with it asked LM Studio for a model it does not
# have, so the last link of the chain answered 404 - a configuration fault, which
# stops the step instead of falling back.

def test_the_configured_local_identifier_wins_over_what_the_runtime_has_cached(world):
    factory, _, _ = world
    config = {**CONFIG, "local": {"model": "cmh-local"}}
    with factory() as db:
        db.get(cdb.ModelEndpoint, "lms").cached_models = json.dumps(["whatever-is-cached"])
        db.commit()
        local = [c for c in resolve_candidates(db, FREE_CLOUD_FIRST, config=config)
                 if c["endpoint_id"] == "lms"]
    assert [c["model"] for c in local] == ["cmh-local"]


def test_an_explicit_local_model_still_wins_over_the_configured_one(world):
    factory, _, _ = world
    config = {**CONFIG, "local": {"model": "cmh-local"}}
    with factory() as db:
        local = [c for c in resolve_candidates(db, FREE_CLOUD_FIRST, config=config,
                                               local_model="explicit")
                 if c["endpoint_id"] == "lms"]
    assert [c["model"] for c in local] == ["explicit"]


def test_without_a_configured_identifier_the_runtimes_cached_model_is_used(world):
    factory, _, _ = world
    with factory() as db:
        local = [c for c in resolve_candidates(db, FREE_CLOUD_FIRST, config=CONFIG)
                 if c["endpoint_id"] == "lms"]
    assert [c["model"] for c in local] == ["cmh-local"]  # the cached one, from the fixture


async def test_a_groq_agent_gets_the_local_identifier_and_not_its_own_cloud_model(api):
    client, factory, net = api
    with factory() as db:
        db.get(cdb.ModelEndpoint, "lms").cached_models = json.dumps(["whatever-is-cached"])
        db.commit()
    async with client:
        run_id = await _create_run(client)
    config, _ = _stored(factory, run_id)
    local = [c for c in json.loads(config)["candidates"] if c["endpoint_id"] == "lms"]
    assert [c["model"] for c in local] == ["cmh-local"]
    assert local[0]["model"] != "openai/gpt-oss-120b"


async def test_under_local_only_the_only_candidate_is_the_local_one_with_its_identifier(api):
    client, factory, net = api
    async with client:
        definition = await client.post("/api/cmh/workflows", json={
            "name": "synthetic", "project_id": "project",
            "steps": [{"key": "a", "agent_id": "agent-a", "provider_policy": "local-only"}]})
        assert definition.status_code == 201, definition.text
        run = await client.post(f"/api/cmh/workflows/{definition.json()['id']}/runs",
                                json={"initial_input": "synthetic input"})
        assert run.status_code == 201, run.text
    config, _ = _stored(factory, run.json()["id"])
    frozen = json.loads(config)["candidates"]
    assert [(c["endpoint_id"], c["model"]) for c in frozen] == [("lms", "cmh-local")]
    assert net.requests == []  # nothing left the machine, not even a catalogue query


# --- review of revision-fase1-r8 ------------------------------------------------------------------

async def _refused_run(client):
    definition = await client.post("/api/cmh/workflows", json={
        "name": "synthetic", "project_id": "project",
        "steps": [{"key": "a", "agent_id": "agent-a"}]})
    return await client.post(f"/api/cmh/workflows/{definition.json()['id']}/runs",
                             json={"initial_input": "synthetic input"})


async def test_the_refusal_of_a_credential_row_names_the_way_out_that_works(api):
    """Registering another endpoint does not clear the old row: it stays enabled with its
    user:password@ and every run is refused again. Only an edit, a delete or a disable does."""
    client, factory, net = api
    with factory() as db:
        db.get(cdb.ModelEndpoint, "lms").base_url = "http://lmsuser:hunter2@127.0.0.1:59999/v1"
        db.commit()
    async with client:
        refused = await _refused_run(client)
    detail = refused.json()["detail"]
    assert refused.status_code == 400, refused.text
    # The word PATCH appears twice now (the way out, and the case where PATCH itself refuses), so
    # the way out is asserted by its whole phrase: mutant W2 survived the bare word.
    assert "Editalo (un PATCH con esa misma URL" in detail
    assert "registrar otro nuevo no basta" in detail
    assert "eliminalo" in detail and "deshabilitalo" in detail     # the three ways out, all named
    assert "puerto fuera de rango" in detail                       # and the case where PATCH refuses
    assert "hunter2" not in refused.text


async def test_a_task_url_with_credentials_and_an_out_of_range_port_is_a_400(api):
    """split_url_credentials called parsed.port outside its try: ValueError, HTTP 500."""
    client, factory, net = api
    with factory() as db:
        db.get(cdb.ScheduledTask, "task-a").endpoint_url = "http://u:p@127.0.0.1:99999/v1"
        db.commit()
    async with client:
        refused = await _refused_run(client)
    assert refused.status_code == 400, refused.text
    assert "credenciales" in refused.json()["detail"] and "la URL de la tarea" in refused.json()["detail"]


def _pinned_openrouter(model):
    return {"threshold": 0.9, "discovery": {"ttl_s": 21600, "timeout_s": 15}, "providers": [
        {"endpoint_host": "api.groq.com", "order": 1, "model": "openai/gpt-oss-120b", "limits": {}},
        {"endpoint_host": "openrouter.ai", "order": 2, "model": model, "limits": {}}]}


async def test_a_three_step_flow_says_a_dropped_row_once_not_once_per_step(api, monkeypatch):
    """The notes of every step are merged with `if n not in notes`; a flow has several steps."""
    client, factory, net = api
    monkeypatch.setattr(router, "load_quota_config",
                        lambda path=None: _pinned_openrouter("pinned/model:free"))
    with factory() as db:
        db.get(cdb.ModelEndpoint, "orr").base_url = "http://openrouter.ai/api/v1"
        db.commit()
    async with client:
        definition = await client.post("/api/cmh/workflows", json={
            "name": "three", "project_id": "project", "steps": [
                {"key": "a", "agent_id": "agent-a"},
                {"key": "b", "agent_id": "agent-a", "depends_on": ["a"]},
                {"key": "c", "agent_id": "agent-a", "depends_on": ["b"]}]})
        assert definition.status_code == 201, definition.text
        run = await client.post(f"/api/cmh/workflows/{definition.json()['id']}/runs",
                                json={"initial_input": "synthetic input"})
        assert run.status_code == 201, run.text
        run_id = run.json()["id"]
        for _ in range(300):
            if run_id not in flow._ACTIVE:
                break
            await asyncio.sleep(0.01)
    with factory() as db:
        steps = db.query(cdb.CMHWorkflowStep).filter(cdb.CMHWorkflowStep.run_id == run_id).count()
        dropped = [json.loads(e.payload) for e in db.query(cdb.CMHWorkflowEvent).filter(
            cdb.CMHWorkflowEvent.run_id == run_id,
            cdb.CMHWorkflowEvent.kind == "provider_dropped").all()]
    assert steps == 3
    assert dropped == [{"endpoint_id": "orr", "host": "openrouter.ai", "reason": "cost_gate"}]


async def test_a_model_that_is_not_free_on_openrouter_is_dropped_by_the_gate_and_said(api, monkeypatch):
    """The second cause of cost_gate, apart from plain http on a free host."""
    client, factory, net = api
    monkeypatch.setattr(router, "load_quota_config", lambda path=None: _pinned_openrouter("paid/model"))
    async with client:
        run_id = await _create_run(client)
    config, events = _stored(factory, run_id)
    dropped = [payload for kind, payload in events if kind == "provider_dropped"]
    assert dropped == [{"endpoint_id": "orr", "host": "openrouter.ai", "reason": "cost_gate"}]
    assert "orr" not in [c["endpoint_id"] for c in json.loads(config)["candidates"]]


async def test_a_task_url_with_credentials_and_no_scheme_is_a_400_that_does_not_echo_them(api):
    """redact_url cut by netloc, and a URL with no scheme has none: the zero-cost 400 returned the
    whole URL, secret included. The first thing that refuses is creating the definition."""
    client, factory, net = api
    with factory() as db:
        db.get(cdb.ScheduledTask, "task-a").endpoint_url = "u:S3CRET@127.0.0.1:59999"
        db.commit()
    async with client:
        definition = await client.post("/api/cmh/workflows", json={
            "name": "synthetic", "project_id": "project",
            "steps": [{"key": "a", "agent_id": "agent-a"}]})
        refused = definition if definition.status_code != 201 else await client.post(
            f"/api/cmh/workflows/{definition.json()['id']}/runs", json={"initial_input": "x"})
    assert refused.status_code == 400, refused.text
    assert "S3CRET" not in refused.text


async def test_a_task_url_with_credentials_and_no_scheme_is_refused_when_cost_gate_is_disabled(
        api, monkeypatch):
    """Disabling the cost gate must not disable credential protection."""
    client, factory, net = api
    monkeypatch.setenv("CMH_ZERO_COST", "false")
    secret_url = "u:S3CRET@127.0.0.1:59999"
    with factory() as db:
        db.get(cdb.ScheduledTask, "task-a").endpoint_url = secret_url
        db.commit()
    async with client:
        definition = await client.post("/api/cmh/workflows", json={
            "name": "synthetic", "project_id": "project",
            "steps": [{"key": "a", "agent_id": "agent-a"}]})
        refused = definition if definition.status_code != 201 else await client.post(
            f"/api/cmh/workflows/{definition.json()['id']}/runs", json={"initial_input": "x"})
    assert refused.status_code == 400, refused.text
    assert "S3CRET" not in refused.text
