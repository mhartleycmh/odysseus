"""PATCH of an endpoint's base URL lifts ``user:pass@`` out of it, as POST does.

POST /model-endpoints has always split the credential into ``api_key`` (ADR-026, the
decision of 2026-09-29). PATCH stored the URL as typed, so an endpoint edited in place
kept the credential in its ``base_url`` and every run froze it into
``cmh_workflow_steps.config``. The review of 2026-09-29 reproduced that.

The route is a closure inside ``setup_model_routes``, so the logic lives in two small
module-level helpers and these tests drive those with plain objects.
"""

import base64
from types import SimpleNamespace

import pytest


@pytest.fixture
def mr():
    import routes.model_routes as module
    return module


def test_a_patched_base_url_has_its_credential_lifted_and_its_suffix_cut(mr):
    base, key = mr._patched_base_url(" https://revuser:S3CRET@openrouter.ai/api/v1/chat/completions/ ")
    assert base == "https://openrouter.ai/api/v1"
    assert key.startswith("Basic ")
    assert base64.b64decode(key.split()[1]).decode() == "revuser:S3CRET"


def test_the_credential_moves_to_api_key_and_never_stays_in_the_url(mr):
    ep = SimpleNamespace(base_url="https://openrouter.ai/api/v1", api_key="old")
    mr._apply_base_url_update(ep, {"base_url": "https://u:p@openrouter.ai/api/v2"})
    assert ep.base_url == "https://openrouter.ai/api/v2"
    assert ep.api_key.startswith("Basic ") and "@" not in ep.base_url


def test_an_explicit_api_key_in_the_same_patch_wins_over_the_one_in_the_url(mr):
    """The api_key branch runs first and has already stored it."""
    ep = SimpleNamespace(base_url="https://h.example/v1", api_key="new-key")
    mr._apply_base_url_update(ep, {"base_url": "https://u:p@h.example/v2", "api_key": "new-key"})
    assert ep.api_key == "new-key" and ep.base_url == "https://h.example/v2"


def test_a_blank_api_key_in_the_patch_does_not_count_as_explicit(mr):
    ep = SimpleNamespace(base_url="https://h.example/v1", api_key=None)
    mr._apply_base_url_update(ep, {"base_url": "https://u:p@h.example/v2", "api_key": "   "})
    assert ep.api_key.startswith("Basic ")


def test_a_url_without_credentials_leaves_the_stored_key_alone(mr):
    ep = SimpleNamespace(base_url="https://h.example/v1", api_key="keep-me")
    mr._apply_base_url_update(ep, {"base_url": "https://h.example/v2"})
    assert ep.base_url == "https://h.example/v2" and ep.api_key == "keep-me"


@pytest.mark.parametrize("body", [{"base_url": "   "}, {"base_url": None}, {"base_url": 5}, {}])
def test_nothing_changes_when_there_is_no_usable_base_url(mr, body):
    ep = SimpleNamespace(base_url="https://h.example/v1", api_key="keep-me")
    mr._apply_base_url_update(ep, body)
    assert (ep.base_url, ep.api_key) == ("https://h.example/v1", "keep-me")


# --- the credential has to AUTHENTICATE, through the real routes -----------------------------
#
# The review of revision-fase1-r7 found that the credential these routes move into api_key
# is a finished ``Basic <base64>`` value, and that build_headers wrapped it in "Bearer ":
# the request went out as ``Authorization: Bearer Basic ...``, which no server accepts. The
# tests above checked only the stored form, so nothing could see it. These drive the real
# PATCH and POST routes (ASGI, in-memory database) and then build the header the way the
# runner does (task_scheduler: build_headers(ep.api_key, normalize_base(ep.base_url))) and
# send it.

import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

EXPECTED_BASIC = "Basic " + base64.b64encode(b"bob:s3cret").decode()


@pytest.fixture
def routes_and_db(monkeypatch):
    import core.database as cdb
    import routes.model_routes as module
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(module, "SessionLocal", factory)
    monkeypatch.setattr(module, "require_admin", lambda request: None)
    monkeypatch.setattr(module, "_load_settings", lambda: {})       # never touch the real files
    monkeypatch.setattr(module, "_save_settings", lambda settings: None)
    app = FastAPI()
    app.include_router(module.setup_model_routes(model_discovery=None))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    yield client, factory, cdb
    engine.dispose()


async def _authorization_the_runner_sends(row):
    """The header a workflow step would send to this row, captured at the transport."""
    from src.endpoint_resolver import build_headers, normalize_base
    seen = {}

    def handler(request):
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await client.post(row.base_url + "/chat/completions",
                          headers=build_headers(row.api_key, normalize_base(row.base_url)), json={})
    return seen["authorization"]


async def test_an_endpoint_edited_with_user_and_password_in_the_url_still_authenticates(
        routes_and_db):
    client, factory, cdb = routes_and_db
    with factory() as db:
        db.add(cdb.ModelEndpoint(id="ep1", name="gw", base_url="http://127.0.0.1:59999/v1",
                                 endpoint_kind="local", is_enabled=True))
        db.commit()
    async with client:
        response = await client.patch("/api/model-endpoints/ep1",
                                      json={"base_url": "http://bob:s3cret@127.0.0.1:59998/v1"})
    assert response.status_code == 200, response.text
    with factory() as db:
        row = db.get(cdb.ModelEndpoint, "ep1")
        assert row.base_url == "http://127.0.0.1:59998/v1"      # no credential left in the URL
        assert "s3cret" not in row.base_url
        assert await _authorization_the_runner_sends(row) == EXPECTED_BASIC


async def test_an_endpoint_created_with_user_and_password_in_the_url_still_authenticates(
        routes_and_db):
    client, factory, cdb = routes_and_db
    async with client:
        response = await client.post("/api/model-endpoints", data={
            "base_url": "http://bob:s3cret@127.0.0.1:59997/v1", "endpoint_kind": "local",
            "skip_probe": "true", "name": "gw"})
    assert response.status_code == 200, response.text
    with factory() as db:
        row = db.query(cdb.ModelEndpoint).one()
        assert "s3cret" not in row.base_url
        assert await _authorization_the_runner_sends(row) == EXPECTED_BASIC


async def test_an_ordinary_key_is_still_sent_as_a_bearer_token(routes_and_db):
    client, factory, cdb = routes_and_db
    with factory() as db:
        db.add(cdb.ModelEndpoint(id="ep2", name="x", base_url="http://127.0.0.1:59996/v1",
                                 endpoint_kind="local", is_enabled=True, api_key="sk-plain-key"))
        db.commit()
    with factory() as db:
        assert await _authorization_the_runner_sends(db.get(cdb.ModelEndpoint, "ep2")) == \
            "Bearer sk-plain-key"


async def test_the_patch_route_really_calls_the_helper_that_lifts_the_credential(
        routes_and_db):
    """Without the credential in the URL nothing about the key may change, and the
    base_url is still updated: the route must go through _apply_base_url_update."""
    client, factory, cdb = routes_and_db
    with factory() as db:
        db.add(cdb.ModelEndpoint(id="ep3", name="x", base_url="http://127.0.0.1:59995/v1",
                                 endpoint_kind="local", is_enabled=True, api_key="keep-me"))
        db.commit()
    async with client:
        response = await client.patch("/api/model-endpoints/ep3",
                                      json={"base_url": "http://127.0.0.1:59994/v1"})
    assert response.status_code == 200, response.text
    with factory() as db:
        row = db.get(cdb.ModelEndpoint, "ep3")
        assert (row.base_url, row.api_key) == ("http://127.0.0.1:59994/v1", "keep-me")


@pytest.mark.parametrize("value", ["Basic abc123", "Basic  spaced"])
def test_build_headers_passes_a_basic_credential_through_unchanged(value):
    from src.endpoint_resolver import build_headers
    for base in ("http://127.0.0.1:1234/v1", "https://api.groq.com/openai/v1",
                 "https://openrouter.ai/api/v1"):
        assert build_headers(value, base)["Authorization"] == value


def test_build_headers_still_wraps_anything_else_in_bearer():
    from src.endpoint_resolver import build_headers
    assert build_headers("gsk-abc", "https://api.groq.com/openai/v1")["Authorization"] == \
        "Bearer gsk-abc"
    assert "Authorization" not in build_headers(None, "http://127.0.0.1:1234/v1")


# --- the PATCH that ESTADO_AGENTIC_OS tells the user to send (U1) ---------------------------------
#
# supports_tools has no control in the interface, so U1 asks the user to PATCH it from the browser
# console. The route ALTERNATES is_enabled when the body is missing, empty or malformed, so a typo
# disables the endpoint instead of failing. The instruction rests on that behaviour of Odysseus's
# own route (routes/model_routes.py, toggle_model_endpoint): if an upgrade changes it, U1 must
# change with it. Measured in memory, through the real route; not against a live session.


async def _patch_state(routes_and_db, **request):
    client, factory, cdb = routes_and_db
    with factory() as db:
        db.add(cdb.ModelEndpoint(id="g1", name="groq", base_url="https://api.groq.com/openai/v1",
                                 endpoint_kind="api", is_enabled=True, api_key="gsk-TEST-DUMMY"))
        db.commit()
    async with client:
        response = await client.patch("/api/model-endpoints/g1", **request)
    assert response.status_code == 200, response.text
    with factory() as db:
        row = db.get(cdb.ModelEndpoint, "g1")
        return row.is_enabled, row.supports_tools


async def test_the_body_u1_names_sets_supports_tools_and_leaves_the_endpoint_enabled(routes_and_db):
    assert await _patch_state(routes_and_db, json={"supports_tools": True}) == (True, True)


@pytest.mark.parametrize("request_kwargs", [
    {},                                                                    # no body at all
    {"json": {}},                                                          # an empty object
    {"content": b'{"supports_tools": tru',                                 # a typo in the JSON
     "headers": {"content-type": "application/json"}},
], ids=["no body", "empty object", "malformed json"])
async def test_a_patch_without_a_usable_body_disables_the_endpoint_instead_of_failing(
        routes_and_db, request_kwargs):
    enabled, supports_tools = await _patch_state(routes_and_db, **request_kwargs)
    assert enabled is False and supports_tools is None
