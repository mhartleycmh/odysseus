"""Zero-cost gate (D1): the predicate, and the three places that enforce it."""

import json
import logging

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as cdb
from routes import cmh_control_routes as control
from routes import cmh_workflow_routes as routes
from src import cmh_workflows as flow
from src.cmh_cost_policy import (
    ZeroCostViolation, assert_zero_cost, describe, enforced, is_local_endpoint,
    has_userinfo, is_reachable_without_leaving_the_network, is_zero_cost_endpoint, redact_url,
)

LOCAL = "http://127.0.0.1:59999/v1"
GROQ = "https://api.groq.com/openai/v1"
OPENROUTER = "https://openrouter.ai/api/v1"
CEREBRAS = "https://api.cerebras.ai/v1"
ANTHROPIC = "https://api.anthropic.com"


def ep(base_url, kind="auto", id="e1"):
    return {"id": id, "base_url": base_url, "endpoint_kind": kind}


# --- the predicate ----------------------------------------------------------

@pytest.mark.parametrize("endpoint, model, expected", [
    (ep(LOCAL, "local"), "cmh-local", True),
    (ep(LOCAL, "auto"), "cmh-local", True),            # unlabelled loopback is still local
    (ep("http://localhost:1234/v1", "auto"), "m", True),
    (ep(GROQ, "api"), "openai/gpt-oss-120b", True),
    # Cerebras left FREE_HOSTS on 2026-09-29: no permanent free tier, the
    # trial expires and the API needs a verified card. Canon 05 of that date.
    (ep(CEREBRAS, "api"), "gpt-oss-120b", False),
    (ep(OPENROUTER, "api"), "some/model:free", True),
    (ep(OPENROUTER, "api"), "some/model", False),      # paid variant on a free host
    # the suffix is ":free" with its colon: a name that merely ends in "free" is billed
    (ep(OPENROUTER, "api"), "vendor/x-free", False),
    (ep(OPENROUTER, "api"), "vendor/model:freeish", False),
    (ep(OPENROUTER, "api"), "Vendor/Model:FREE", True),
    # a free host over plain http would send the key in the clear: not "free" for us
    (ep("http://api.groq.com/openai/v1", "api"), "m", False),
    (ep("http://openrouter.ai/api/v1", "api"), "some/model:free", False),
    (ep("HTTPS://API.GROQ.COM/openai/v1", "api"), "m", True),
    (ep("api.groq.com/openai/v1", "api"), "m", False),   # no scheme, no host
    (ep(OPENROUTER, "api"), None, False),              # unknown model fails closed
    (ep(ANTHROPIC, "api"), "claude-sonnet-5", False),
    (ep("https://api.openai.com/v1", "api"), "gpt-4", False),
])
def test_zero_cost_classification(endpoint, model, expected):
    assert is_zero_cost_endpoint(endpoint, model) is expected


def test_a_lookalike_host_is_not_the_free_host():
    """FREE_HOSTS is an exact host match, never a suffix match."""
    assert is_zero_cost_endpoint(ep("https://api.groq.com.attacker.example/v1", "api"), "m") is False
    assert is_zero_cost_endpoint(ep("https://notapi.groq.com/v1", "api"), "m") is False


@pytest.mark.parametrize("host, expected", [
    # loopback and the names that mean "this machine or its own network"
    ("127.0.0.1", True), ("127.255.255.254", True), ("[::1]", True), ("localhost", True),
    ("gpu.local", True), ("0.0.0.0", True), ("host.docker.internal", True),
    # RFC1918, edge to edge: 10/8, 172.16/12, 192.168/16
    ("10.0.0.1", True), ("10.255.255.254", True),
    ("172.16.0.1", True), ("172.31.255.254", True),
    ("192.168.0.1", True), ("192.168.255.254", True),
    # link-local, IPv4 and IPv6, and the IPv6 unique-local range
    ("169.254.0.1", True), ("169.254.255.254", True), ("[fe80::1]", True), ("[fd00::1]", True),
    # fe80::/10 is fe80 through febf, and fc00::/7 is fc00 through fdff: both ends of each
    ("[febf::1]", True), ("[febf:ffff:ffff:ffff:ffff:ffff:ffff:ffff]", True),
    ("[fc00::1]", True), ("[fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff]", True),
    # one address outside each edge: a PUBLIC host must never be local
    ("9.255.255.255", False), ("11.0.0.1", False),
    ("172.15.255.255", False), ("172.32.0.1", False),
    ("192.167.255.255", False), ("192.169.0.1", False),
    ("169.253.255.255", False), ("169.255.0.1", False),
    ("[fe7f::1]", False), ("[fec0::1]", False), ("[fbff::1]", False), ("[fe00::1]", False),
    ("[fbff:ffff:ffff:ffff:ffff:ffff:ffff:ffff]", False),
    # carrier-grade NAT (Tailscale) is outside local-only by ASSUMPTION of ADR-032 (ADR-026
    # does not say it); reserved and
    # documentation ranges are not "a private network" even though Python calls
    # some of them private
    ("100.64.0.1", False), ("192.0.2.1", False), ("240.0.0.1", False), ("198.18.0.1", False),
    # names
    ("8.8.8.8", False), ("gpu.corp.example", False), ("api.groq.com", False),
    ("gpu.local.example.com", False), ("notlocal", False), ("", False),
])
def test_local_is_exactly_loopback_rfc1918_link_local_and_unique_local(host, expected):
    """The boundary of every range, both sides. The audit's cost-gate mutants showed
    nothing pinned it: 'any 172.x counts as private' survived, and so did dropping
    link-local, because the code leaned on ``ipaddress.is_private`` and the two
    could not be told apart."""
    for kind in ("auto", "local"):
        endpoint = ep(f"http://{host}:1234/v1", kind)
        assert is_local_endpoint(endpoint) is expected, (host, kind)
    for kind in ("api", "proxy"):
        # a label of "api" or "proxy" declares a tunnel: never local, whatever the host
        assert is_local_endpoint(ep(f"http://{host}:1234/v1", kind)) is False, (host, kind)


@pytest.mark.parametrize("url", ["127.0.0.1:1234/v1", "localhost:1234/v1", "gpu.corp/v1", ""])
def test_a_url_without_a_scheme_has_no_host_and_is_therefore_not_local(url):
    """``urlparse`` reads ``localhost:1234/v1`` as scheme ``localhost``: no host, so the
    rule that protects the empty host is the one that answers."""
    assert is_local_endpoint(ep(url, "auto")) is False
    assert is_reachable_without_leaving_the_network("") is False
    assert is_reachable_without_leaving_the_network("  .  ") is False


def test_an_api_labelled_loopback_is_not_local():
    """An admin who labels a route external has declared it a tunnel."""
    assert is_local_endpoint(ep(LOCAL, "api")) is False
    assert is_zero_cost_endpoint(ep(LOCAL, "api"), "m") is False


def test_assert_raises_and_names_the_route():
    with pytest.raises(ZeroCostViolation) as caught:
        assert_zero_cost(ep(ANTHROPIC, "api", id="9a76d7a3"), "claude-sonnet-5")
    message = str(caught.value)
    assert "9a76d7a3" in message and "claude-sonnet-5" in message


def test_the_flag_downgrades_the_gate_to_logging(monkeypatch):
    monkeypatch.setenv("CMH_ZERO_COST", "false")
    assert enforced() is False
    assert_zero_cost(ep(ANTHROPIC, "api"), "claude-sonnet-5")  # does not raise
    monkeypatch.setenv("CMH_ZERO_COST", "true")
    with pytest.raises(ZeroCostViolation):
        assert_zero_cost(ep(ANTHROPIC, "api"), "claude-sonnet-5")


def test_the_gate_is_on_by_default(monkeypatch):
    monkeypatch.delenv("CMH_ZERO_COST", raising=False)
    assert enforced() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "OFF", " False "])
def test_only_an_explicit_off_switches_the_gate_off(monkeypatch, value):
    monkeypatch.setenv("CMH_ZERO_COST", value)
    assert enforced() is False


@pytest.mark.parametrize("value", ["true", "1", "yes", "on", "enabled", "", "  ", "flase", "disabled"])
def test_anything_else_leaves_the_gate_on_a_typo_included(monkeypatch, value):
    """It used to fail OPEN: only 1/true/yes/on kept it on, so ``CMH_ZERO_COST=enabled``
    or a misspelt ``flase`` switched the money guard off without a word."""
    monkeypatch.setenv("CMH_ZERO_COST", value)
    assert enforced() is True
    with pytest.raises(ZeroCostViolation):
        assert_zero_cost(ep(ANTHROPIC, "api"), "claude-sonnet-5")


def test_switching_the_gate_off_leaves_a_warning_and_no_secret(monkeypatch, caplog):
    monkeypatch.setenv("CMH_ZERO_COST", "false")
    with caplog.at_level(logging.WARNING, logger="src.cmh_cost_policy"):
        assert_zero_cost(ep("https://user:hunter2@api.anthropic.com/v1", "api", id="e9"),
                         "claude-sonnet-5")
    text = " ".join(record.getMessage() for record in caplog.records)
    assert "DESACTIVADO" in text and "e9" in text and "claude-sonnet-5" in text
    assert "hunter2" not in text


def test_an_allowed_route_logs_nothing_even_with_the_gate_off(monkeypatch, caplog):
    monkeypatch.setenv("CMH_ZERO_COST", "false")
    with caplog.at_level(logging.WARNING, logger="src.cmh_cost_policy"):
        assert_zero_cost(ep(GROQ, "api"), "m")
    assert caplog.records == []


# --- what a message or an event may print -------------------------------------

@pytest.mark.parametrize("url, expected", [
    ("https://user:hunter2@openrouter.ai/api/v1", "https://openrouter.ai/api/v1"),
    ("https://openrouter.ai/api/v1?key=hunter2#frag", "https://openrouter.ai/api/v1"),
    ("http://a:b@[fe80::1]:1234/v1", "http://[fe80::1]:1234/v1"),
    # a raw @ inside the password: the LAST @ ends the userinfo, so nothing of it may remain
    ("https://user:p@ss@openrouter.ai/api/v1", "https://openrouter.ai/api/v1"),
    ("https://api.groq.com/openai/v1", "https://api.groq.com/openai/v1"),
    ("", ""), (None, ""),
])
def test_redact_url_drops_userinfo_query_and_fragment(url, expected):
    assert redact_url(url) == expected


@pytest.mark.parametrize("url, expected", [
    ("https://user:hunter2@openrouter.ai/api/v1", True),
    ("https://user:p@ss@openrouter.ai/api/v1", True),          # a raw @ inside the password
    ("https://:onlypass@host.example/v1", True),
    ("http://a:b@[fe80::1]:1234/v1", True),
    ("http://u%40a:p%3Ab@127.0.0.1:1234/v1", True),
    ("https://host.example/v1?email=a@b.com", False),          # an @ in the QUERY is not userinfo
    ("https://host.example/v1/@handle", False),                # nor one in the path
    ("http://127.0.0.1:1234/v1", False), ("", False), (None, False),
])
def test_has_userinfo_sees_a_credential_only_in_the_authority(url, expected):
    assert has_userinfo(url) is expected


def test_redact_url_survives_an_unparsable_url():
    assert "hunter2" not in redact_url("http://user:hunter2@[::1")


def test_describe_and_the_violation_message_never_print_a_credential():
    endpoint = ep("https://user:hunter2@api.anthropic.com/v1?api_key=hunter2", "api", id="e7")
    assert "hunter2" not in describe(endpoint, "claude-sonnet-5")
    assert "api.anthropic.com" in describe(endpoint, "claude-sonnet-5")
    with pytest.raises(ZeroCostViolation) as caught:
        assert_zero_cost(endpoint, "claude-sonnet-5")
    assert "hunter2" not in str(caught.value) and "e7" in str(caught.value)


# --- the three enforcement sites --------------------------------------------

@pytest.fixture
def factory(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    cdb.Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    for module in (flow, routes, control):
        monkeypatch.setattr(module, "SessionLocal", session_factory, raising=False)
    monkeypatch.setattr(routes, "catalog", lambda: [{"id": "project"}])
    monkeypatch.setattr(control, "catalog", lambda: [{"id": "project"}])
    monkeypatch.setattr(control, "owner_is_admin_or_single_user", lambda owner: owner == "admin")
    monkeypatch.setattr(routes, "validate_task_tools", lambda tools, owner: set(tools))
    monkeypatch.setattr(routes, "validate_task_workspace",
                        lambda workspace, owner, persisted=True: workspace)
    monkeypatch.setattr(control, "validate_task_tools", lambda tools, owner: set(tools))
    monkeypatch.setattr(control, "validate_task_workspace",
                        lambda workspace, owner, persisted=True: workspace)
    monkeypatch.setattr(control, "protected_area", lambda path: None)
    monkeypatch.setattr(routes, "protected_area", lambda path: None)
    with session_factory() as db:
        for key, url in (("free", GROQ), ("paid", ANTHROPIC)):
            db.add(cdb.ScheduledTask(id=f"task-{key}", owner="admin", name=key, task_type="llm",
                                     endpoint_url=url, model=f"model-{key}",
                                     prompt="unused", status="paused"))
            db.add(cdb.CMHAgent(id=f"agent-{key}", owner="admin", name=key, project_id="project",
                                role=key, instructions=key, model=f"model-{key}",
                                allowed_tools=json.dumps(["read_file"]), workspace=str(tmp_path),
                                status="active", task_id=f"task-{key}"))
        db.commit()
    yield session_factory
    flow._ACTIVE.clear()
    engine.dispose()


@pytest.fixture
def client(factory):
    app = FastAPI()

    @app.middleware("http")
    async def as_admin(request, call_next):
        request.state.current_user = "admin"
        return await call_next(request)

    app.include_router(control.setup_cmh_control_routes())
    app.include_router(routes.setup_cmh_workflow_routes())
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _agent_body(task_id, model):
    return {"name": "n", "project_id": "project", "role": "r", "instructions": "i",
            "model": model, "allowed_tools": ["read_file"], "workspace": ".",
            "task_id": task_id}


async def test_site_1_creating_an_agent_on_a_paid_endpoint_is_refused(client):
    async with client:
        paid = await client.post("/api/cmh/agents", json=_agent_body("task-paid", "model-paid"))
        assert paid.status_code == 400
        assert "Costo cero" in paid.json()["detail"]
        free = await client.post("/api/cmh/agents", json=_agent_body("task-free", "model-free"))
        assert free.status_code == 201, free.text


async def test_site_1_editing_an_agent_onto_a_paid_endpoint_is_refused(client):
    async with client:
        moved = await client.put("/api/cmh/agents/agent-free",
                                 json=_agent_body("task-paid", "model-paid"))
        assert moved.status_code == 400
        assert "Costo cero" in moved.json()["detail"]


def _definition(agent_id):
    return {"name": "d", "project_id": "project",
            "steps": [{"key": "uno", "agent_id": agent_id, "depends_on": [],
                       "independent_of": [], "requires_approval": False}]}


async def test_site_2_a_definition_on_a_paid_endpoint_is_refused(client):
    async with client:
        paid = await client.post("/api/cmh/workflows", json=_definition("agent-paid"))
        assert paid.status_code == 400
        assert "Costo cero" in paid.json()["detail"]
        free = await client.post("/api/cmh/workflows", json=_definition("agent-free"))
        assert free.status_code == 201, free.text


async def test_site_2_run_creation_refuses_a_step_moved_onto_a_paid_endpoint(client, factory):
  async with client:
    created = await client.post("/api/cmh/workflows", json=_definition("agent-free"))
    assert created.status_code == 201
    # The definition froze nothing but an agent id, so repoint the agent after
    # the fact: the snapshot gate is the one that must still catch it.
    with factory() as db:
        agent = db.query(cdb.CMHAgent).filter(cdb.CMHAgent.id == "agent-free").first()
        # The model moves with the task: _snapshot rejects a task/agent model
        # mismatch first, and that 400 would mask the cost gate behind it.
        agent.task_id, agent.model = "task-paid", "model-paid"
        db.commit()
    run = await client.post(f"/api/cmh/workflows/{created.json()['id']}/runs",
                            json={"initial_input": "x"})
    assert run.status_code == 400
    assert "Costo cero" in run.json()["detail"]


def test_site_3_a_paid_candidate_is_blocked_and_the_step_gets_no_paid_fallback(factory):
    """call_model records zero_cost_blocked per candidate and refuses to run."""
    events = []
    config = {"run_id": "r1", "step_key": "uno", "agent_id": "agent-paid", "owner": "admin",
              "name": "n", "workspace": ".", "allowed_tools": ["read_file"],
              "instructions": "i", "instructions_version": 1,
              "endpoint_url": ANTHROPIC, "model": "claude-sonnet-5"}
    blocked = flow._zero_cost_candidates(config, lambda kind, **p: events.append((kind, p)))
    assert blocked == []
    assert [kind for kind, _ in events] == ["zero_cost_blocked"]
    assert events[0][1]["endpoint_url"] == ANTHROPIC


def test_site_3_the_blocked_event_carries_no_credential(factory):
    url = "https://user:hunter2@api.anthropic.com/v1?key=hunter2"
    events = []
    config = {"run_id": "r1", "step_key": "uno", "agent_id": "a", "owner": "admin",
              "endpoint_url": url, "model": "claude-sonnet-5"}
    assert flow._zero_cost_candidates(config, lambda kind, **p: events.append((kind, p))) == []
    assert events[0][1]["endpoint_url"] == "https://api.anthropic.com/v1"
    assert "hunter2" not in json.dumps(events)


def test_site_3_a_free_candidate_passes_without_an_event(factory):
    events = []
    config = {"run_id": "r1", "step_key": "uno", "agent_id": "agent-free", "owner": "admin",
              "endpoint_url": GROQ, "model": "openai/gpt-oss-120b"}
    allowed = flow._zero_cost_candidates(config, lambda kind, **p: events.append((kind, p)))
    assert len(allowed) == 1 and allowed[0]["endpoint_url"] == GROQ
    assert events == []


def test_site_3_the_event_is_recorded_even_when_the_gate_is_not_enforcing(factory, monkeypatch):
    """CMH_ZERO_COST=false must be diagnosable, not silent."""
    monkeypatch.setenv("CMH_ZERO_COST", "false")
    events = []
    config = {"run_id": "r1", "step_key": "uno", "agent_id": "a", "owner": "admin",
              "endpoint_url": ANTHROPIC, "model": "claude-sonnet-5"}
    assert flow._zero_cost_candidates(config, lambda kind, **p: events.append((kind, p))) == []
    assert [kind for kind, _ in events] == ["zero_cost_blocked"]


def test_site_3_the_registered_row_decides_not_the_bare_url(factory):
    """A loopback URL an admin labelled `api` is judged by the row, not the URL."""
    with factory() as db:
        db.add(cdb.ModelEndpoint(id="tunnel", name="t", base_url=LOCAL,
                                 endpoint_kind="api", is_enabled=True))
        db.commit()
    events = []
    config = {"run_id": "r1", "step_key": "uno", "agent_id": "a", "owner": "admin",
              "endpoint_url": LOCAL, "model": "m"}
    assert flow._zero_cost_candidates(config, lambda kind, **p: events.append((kind, p))) == []
    assert [kind for kind, _ in events] == ["zero_cost_blocked"]


# --- the twin LLM task (§3.5) -----------------------------------------------

async def test_creating_an_agent_without_a_task_id_creates_its_paused_twin(client, factory):
    """The user no longer builds the task by hand and pastes its id."""
    with factory() as db:
        db.add(cdb.ModelEndpoint(id="groq", name="groq", base_url=GROQ,
                                 endpoint_kind="api", is_enabled=True))
        db.commit()
    body = {"name": "Investigador", "project_id": "project", "role": "investigador",
            "instructions": "i", "allowed_tools": ["read_file"], "workspace": "."}
    async with client:
        created = await client.post("/api/cmh/agents", json=body)
    assert created.status_code == 201, created.text
    task_id = created.json()["task_id"]
    assert task_id

    with factory() as db:
        task = db.query(cdb.ScheduledTask).filter(cdb.ScheduledTask.id == task_id).first()
    assert task.task_type == "llm"
    assert task.status == "paused"          # the workflow engine drives it, not cron
    assert task.email_results is False      # canon rule of 2026-09-24 for pilots
    assert task.notifications_enabled is False
    assert task.endpoint_url == GROQ        # first free candidate, not a paid one


async def test_the_twin_task_never_lands_on_a_paid_endpoint(client, factory):
    """Only Anthropic is registered, so no free candidate exists."""
    with factory() as db:
        db.add(cdb.ModelEndpoint(id="anthropic", name="a", base_url=ANTHROPIC,
                                 endpoint_kind="api", is_enabled=True))
        db.commit()
    body = {"name": "Investigador", "project_id": "project", "role": "investigador",
            "instructions": "i", "allowed_tools": ["read_file"], "workspace": "."}
    async with client:
        created = await client.post("/api/cmh/agents", json=body)
    assert created.status_code == 201, created.text
    with factory() as db:
        task = db.query(cdb.ScheduledTask).filter(
            cdb.ScheduledTask.id == created.json()["task_id"]).first()
    # No free candidate means no endpoint at all, never the paid one that was
    # sitting right there. _snapshot refuses the step later, with its own 400.
    assert task.endpoint_url is None


async def test_an_agent_workspace_inside_a_financial_folder_is_refused(client, monkeypatch):
    """The guard already existed (cmh_control_routes.py:158); this fixes it for
    the twin-task path too, where a workspace now reaches a task as well."""
    monkeypatch.setattr(control, "protected_area",
                        lambda path: "Modelo Financiero Nuevo")
    body = {"name": "Investigador", "project_id": "project", "role": "investigador",
            "instructions": "i", "allowed_tools": ["read_file"], "workspace": "."}
    async with client:
        refused = await client.post("/api/cmh/agents", json=body)
    assert refused.status_code == 400
    assert "Modelo Financiero Nuevo" in refused.json()["detail"]
