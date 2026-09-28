"""Candidate order, policy precedence, quota windows and provider fallback (D3)."""

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as cdb
from src import cmh_workflows as flow
from src.cmh_provider_router import (
    DEFAULT_POLICY, FREE_CLOUD_FIRST, LOCAL_ONLY, is_fallback_error, quota_exceeded,
    record_usage, resolve_candidates, resolve_policy, usable_candidates,
    usage_snapshot, window_start,
)

GROQ = "https://api.groq.com/openai/v1"
CEREBRAS = "https://api.cerebras.ai/v1"
OPENROUTER = "https://openrouter.ai/api/v1"
LOCAL = "http://127.0.0.1:59999/v1"
ANTHROPIC = "https://api.anthropic.com"

CONFIG = {
    "threshold": 0.9,
    "providers": [
        {"endpoint_host": "api.groq.com", "order": 1, "model": "openai/gpt-oss-120b",
         "limits": {"rpd": 1000, "tpd": 200000}},
        {"endpoint_host": "api.cerebras.ai", "order": 2, "model": "gpt-oss-120b",
         "limits": {"rpm": 5, "tpd": 1000000}},
        {"endpoint_host": "openrouter.ai", "order": 3, "model": "some/model:free",
         "limits": {"rpd": 50}},
    ],
}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    cdb.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    # Registered deliberately out of policy order, so a passing order test
    # proves the policy ordered them and not the insertion order.
    for eid, url, kind in (("anthropic", ANTHROPIC, "api"), ("local", LOCAL, "local"),
                           ("openrouter", OPENROUTER, "api"), ("cerebras", CEREBRAS, "api"),
                           ("groq", GROQ, "api")):
        session.add(cdb.ModelEndpoint(id=eid, name=eid, base_url=url, endpoint_kind=kind,
                                      is_enabled=True,
                                      cached_models=json.dumps(["cmh-local"])))
    session.commit()
    yield session
    session.close()
    engine.dispose()


# --- policy precedence ------------------------------------------------------

def test_the_step_wins_over_the_agent_and_the_agent_over_the_automation():
    assert resolve_policy({"provider_policy": LOCAL_ONLY},
                          {"provider_policy": FREE_CLOUD_FIRST},
                          {"provider_policy": FREE_CLOUD_FIRST}) == LOCAL_ONLY
    assert resolve_policy({}, {"provider_policy": LOCAL_ONLY},
                          {"provider_policy": FREE_CLOUD_FIRST}) == LOCAL_ONLY
    assert resolve_policy({}, {}, {"provider_policy": LOCAL_ONLY}) == LOCAL_ONLY
    assert resolve_policy({}, {}, {}) == DEFAULT_POLICY


def test_an_unknown_policy_name_is_not_honoured():
    """A typo must not silently become a policy; it falls through to the default."""
    assert resolve_policy({"provider_policy": "free_cloud_first"}) == DEFAULT_POLICY
    assert resolve_policy({"provider_policy": "local-only "}) == LOCAL_ONLY


# --- candidate order --------------------------------------------------------

def test_free_cloud_first_orders_groq_cerebras_openrouter_then_local(db):
    order = [c["endpoint_id"] for c in
             resolve_candidates(db, FREE_CLOUD_FIRST, config=CONFIG)]
    assert order == ["groq", "cerebras", "openrouter", "local"]


def test_local_only_never_reaches_the_cloud(db):
    candidates = resolve_candidates(db, LOCAL_ONLY, config=CONFIG)
    assert [c["endpoint_id"] for c in candidates] == ["local"]


def test_a_paid_endpoint_never_enters_the_list(db):
    """Anthropic is registered and enabled; no policy may surface it."""
    for policy in (FREE_CLOUD_FIRST, LOCAL_ONLY):
        ids = [c["endpoint_id"] for c in resolve_candidates(db, policy, config=CONFIG)]
        assert "anthropic" not in ids


def test_a_provider_whose_model_is_still_pendiente_is_skipped(db):
    config = {"threshold": 0.9, "providers": [
        {"endpoint_host": "api.groq.com", "order": 1, "model": None, "limits": {}},
        {"endpoint_host": "api.cerebras.ai", "order": 2, "model": "gpt-oss-120b", "limits": {}},
    ]}
    ids = [c["endpoint_id"] for c in resolve_candidates(db, FREE_CLOUD_FIRST, config=config)]
    assert ids == ["cerebras", "local"]


# --- quota windows ----------------------------------------------------------

def test_windows_truncate_rather_than_roll():
    at = datetime(2026, 9, 28, 14, 37, 42, 500000)
    assert window_start("minute", at) == datetime(2026, 9, 28, 14, 37)
    assert window_start("day", at) == datetime(2026, 9, 28)
    with pytest.raises(ValueError):
        window_start("week", at)


def test_usage_accumulates_in_both_windows(db):
    at = datetime(2026, 9, 28, 14, 37)
    record_usage(db, "groq", requests=1, tokens_in=100, tokens_out=50, at=at)
    record_usage(db, "groq", requests=1, tokens_in=10, tokens_out=5, at=at)
    db.commit()
    snapshot = usage_snapshot(db, "groq", at)
    assert snapshot["minute"]["requests"] == 2
    assert snapshot["day"]["tokens_in"] + snapshot["day"]["tokens_out"] == 165


def test_a_new_window_starts_from_zero(db):
    at = datetime(2026, 9, 28, 14, 37)
    record_usage(db, "groq", requests=4, at=at)
    db.commit()
    later = at + timedelta(minutes=1)
    assert usage_snapshot(db, "groq", later)["minute"]["requests"] == 0
    assert usage_snapshot(db, "groq", later)["day"]["requests"] == 4


def test_the_minute_window_stops_a_candidate_at_the_threshold(db):
    at = datetime(2026, 9, 28, 14, 37)
    limits = {"rpm": 5}
    record_usage(db, "cerebras", requests=4, at=at)  # 4 of 5 = 80 %, still under 90 %
    db.commit()
    assert quota_exceeded(db, "cerebras", limits, 0.9, at) is None
    record_usage(db, "cerebras", requests=1, at=at)  # 5 of 5 = 100 %
    db.commit()
    assert quota_exceeded(db, "cerebras", limits, 0.9, at) == "rpm"


def test_the_day_window_stops_a_candidate_at_the_threshold(db):
    at = datetime(2026, 9, 28, 14, 37)
    limits = {"rpd": 1000}
    record_usage(db, "groq", requests=899, at=at)
    db.commit()
    assert quota_exceeded(db, "groq", limits, 0.9, at) is None
    record_usage(db, "groq", requests=1, at=at)  # 900 of 1000 = exactly 90 %
    db.commit()
    assert quota_exceeded(db, "groq", limits, 0.9, at) == "rpd"


def test_an_absent_limit_is_unmeasured_not_unlimited(db):
    """A null limit cannot stop a candidate, and must not be read as infinite."""
    at = datetime(2026, 9, 28, 14, 37)
    record_usage(db, "groq", requests=10_000, at=at)
    db.commit()
    assert quota_exceeded(db, "groq", {"rpd": None}, 0.9, at) is None


def test_token_limits_count_both_directions(db):
    at = datetime(2026, 9, 28, 14, 37)
    record_usage(db, "groq", tokens_in=100_000, tokens_out=80_000, at=at)
    db.commit()
    assert quota_exceeded(db, "groq", {"tpd": 200_000}, 0.9, at) == "tpd"


def test_a_spent_candidate_is_split_out_with_its_reason(db):
    at = datetime(2026, 9, 28, 14, 37)
    record_usage(db, "groq", requests=1000, at=at)
    db.commit()
    candidates = resolve_candidates(db, FREE_CLOUD_FIRST, config=CONFIG)
    ready, skipped = usable_candidates(db, candidates, CONFIG, at)
    assert [c["endpoint_id"] for c in skipped] == ["groq"]
    assert skipped[0]["reason"] == "quota:rpd"
    assert [c["endpoint_id"] for c in ready] == ["cerebras", "openrouter", "local"]


# --- fallback classification ------------------------------------------------

class _Response:
    def __init__(self, status_code):
        self.status_code = status_code


class _HttpError(Exception):
    def __init__(self, status_code):
        super().__init__(str(status_code))
        self.response = _Response(status_code)


@pytest.mark.parametrize("status, expected", [
    (429, "http:429"), (402, "http:402"), (503, "http:503"), (500, "http:500"),
    (401, None), (400, None), (404, None),
])
def test_only_refusals_to_answer_move_to_the_next_provider(status, expected):
    assert is_fallback_error(_HttpError(status)) == expected


def test_timeouts_fall_back_and_plain_faults_do_not():
    assert is_fallback_error(TimeoutError()) == "timeout"
    assert is_fallback_error(ValueError("bad artifact")) is None


# --- the executor's walk ----------------------------------------------------

@pytest.fixture
def flow_db(db, monkeypatch):
    factory = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(flow, "SessionLocal", factory)
    import src.cmh_provider_router as router
    monkeypatch.setattr(router, "load_quota_config", lambda path=None: CONFIG)
    return factory


def _config(candidates):
    return {"run_id": "r1", "step_key": "uno", "agent_id": "a", "owner": None,
            "name": "n", "workspace": ".", "allowed_tools": ["read_file"],
            "instructions": "i", "instructions_version": 1,
            "endpoint_url": candidates[0]["endpoint_url"], "model": candidates[0]["model"],
            "candidates": candidates}


async def test_a_429_falls_back_to_the_next_candidate_with_all_three_fields(flow_db, monkeypatch):
    candidates = [{"endpoint_id": "groq", "endpoint_url": GROQ, "model": "m", "host": "api.groq.com"},
                  {"endpoint_id": "cerebras", "endpoint_url": CEREBRAS, "model": "m",
                   "host": "api.cerebras.ai"}]
    attempts = []

    async def fake(config, candidate, prompt, record):
        attempts.append(candidate["endpoint_id"])
        if candidate["endpoint_id"] == "groq":
            raise _HttpError(429)
        return "artifact from cerebras"

    monkeypatch.setattr(flow, "_run_one_candidate", fake)
    output = await flow.call_model(_config(candidates), "prompt")
    assert output == "artifact from cerebras"
    assert attempts == ["groq", "cerebras"]

    with flow_db() as session:
        events = [(e.kind, json.loads(e.payload)) for e in
                  session.query(cdb.CMHWorkflowEvent).filter(
                      cdb.CMHWorkflowEvent.kind == "provider_fallback").all()]
    assert len(events) == 1
    payload = events[0][1]
    assert payload["from"] == "groq" and payload["to"] == "cerebras"
    assert payload["reason"] == "http:429"


async def test_a_401_is_not_a_fallback_and_stops_the_step(flow_db, monkeypatch):
    candidates = [{"endpoint_id": "groq", "endpoint_url": GROQ, "model": "m", "host": "api.groq.com"},
                  {"endpoint_id": "cerebras", "endpoint_url": CEREBRAS, "model": "m",
                   "host": "api.cerebras.ai"}]
    attempts = []

    async def fake(config, candidate, prompt, record):
        attempts.append(candidate["endpoint_id"])
        raise _HttpError(401)

    monkeypatch.setattr(flow, "_run_one_candidate", fake)
    with pytest.raises(_HttpError):
        await flow.call_model(_config(candidates), "prompt")
    assert attempts == ["groq"]  # never tried the second


async def test_when_every_candidate_fails_the_step_errors_without_a_paid_fallback(
        flow_db, monkeypatch):
    candidates = [{"endpoint_id": "groq", "endpoint_url": GROQ, "model": "m", "host": "api.groq.com"},
                  {"endpoint_id": "anthropic", "endpoint_url": ANTHROPIC, "model": "claude-opus-5",
                   "host": "api.anthropic.com"}]

    async def fake(config, candidate, prompt, record):
        raise _HttpError(503)

    monkeypatch.setattr(flow, "_run_one_candidate", fake)
    with pytest.raises(RuntimeError, match="Ningun candidato gratuito respondio"):
        await flow.call_model(_config(candidates), "prompt")

    with flow_db() as session:
        kinds = [e.kind for e in session.query(cdb.CMHWorkflowEvent).all()]
    # The paid candidate was removed by the cost gate before any attempt.
    assert "zero_cost_blocked" in kinds


async def test_a_successful_call_is_charged_to_the_endpoint_it_used(flow_db, monkeypatch):
    candidates = [{"endpoint_id": "groq", "endpoint_url": GROQ, "model": "m",
                   "host": "api.groq.com"}]

    async def fake(config, candidate, prompt, record):
        return "artifact"

    monkeypatch.setattr(flow, "_run_one_candidate", fake)
    assert await flow.call_model(_config(candidates), "prompt") == "artifact"
    with flow_db() as session:
        assert usage_snapshot(session, "groq")["day"]["requests"] == 1


# --- GET /api/cmh/quotas ----------------------------------------------------

async def test_the_quotas_endpoint_reports_windows_limits_and_provenance(db, monkeypatch):
    import httpx
    from fastapi import FastAPI
    from routes import cmh_control_routes as control
    import src.cmh_provider_router as router

    factory = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(control, "SessionLocal", factory)
    monkeypatch.setattr(control, "owner_is_admin_or_single_user", lambda owner: True)
    monkeypatch.setattr(router, "load_quota_config", lambda path=None: CONFIG)

    with factory() as session:
        record_usage(session, "groq", requests=950)
        session.commit()

    app = FastAPI()

    @app.middleware("http")
    async def as_admin(request, call_next):
        request.state.current_user = "admin"
        return await call_next(request)

    app.include_router(control.setup_cmh_control_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as client:
        body = (await client.get("/api/cmh/quotas")).json()

    assert [p["host"] for p in body["providers"]] == [
        "api.groq.com", "api.cerebras.ai", "openrouter.ai"]
    groq = body["providers"][0]
    assert groq["registered"] is True
    assert groq["windows"]["day"]["requests"] == 950
    assert groq["blocked_by"] == "rpd"          # 950 of 1000 is past 90 %
    assert groq["verified"] is False            # nobody has confirmed the limit yet
    assert groq["windows"]["day"]["resets_at"].endswith("00:00:00")


async def test_when_every_candidate_is_paid_nothing_is_attempted(flow_db, monkeypatch):
    """The gap M8 exposed: a list with one free entry hid the paid-fallback bug.

    With every candidate paid the free list is empty, which is the only state
    in which a 'fall back to the frozen list' regression becomes reachable.
    """
    from src.cmh_cost_policy import ZeroCostViolation
    candidates = [{"endpoint_id": "anthropic", "endpoint_url": ANTHROPIC,
                   "model": "claude-opus-5", "host": "api.anthropic.com"},
                  {"endpoint_id": "openai", "endpoint_url": "https://api.openai.com/v1",
                   "model": "gpt-4", "host": "api.openai.com"}]
    attempts = []

    async def fake(config, candidate, prompt, record):
        attempts.append(candidate["endpoint_id"])
        return "should never be reached"

    monkeypatch.setattr(flow, "_run_one_candidate", fake)
    with pytest.raises(ZeroCostViolation):
        await flow.call_model(_config(candidates), "prompt")
    assert attempts == []


async def test_the_charge_lands_on_the_candidate_that_answered(flow_db, monkeypatch):
    """The gap M10 exposed: with one candidate, 'first' and 'answered' coincide."""
    candidates = [{"endpoint_id": "groq", "endpoint_url": GROQ, "model": "m",
                   "host": "api.groq.com"},
                  {"endpoint_id": "cerebras", "endpoint_url": CEREBRAS, "model": "m",
                   "host": "api.cerebras.ai"}]

    async def fake(config, candidate, prompt, record):
        if candidate["endpoint_id"] == "groq":
            raise _HttpError(429)
        return "artifact"

    monkeypatch.setattr(flow, "_run_one_candidate", fake)
    assert await flow.call_model(_config(candidates), "prompt") == "artifact"
    with flow_db() as session:
        assert usage_snapshot(session, "cerebras")["day"]["requests"] == 1
        # The one that refused is not charged: it never served a request.
        assert usage_snapshot(session, "groq")["day"]["requests"] == 0
