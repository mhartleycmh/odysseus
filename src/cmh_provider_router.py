"""Ordered free-provider candidates, with fallback and free-tier quotas (D3).

A step no longer freezes one route. It freezes an **ordered list of
candidates**, resolved when the run is created, and the executor walks it: the
first candidate that is free (``cmh_cost_policy``), within quota and reachable
wins. Freezing the list rather than re-resolving per attempt keeps the point-3
guarantee — what a step will call cannot change under it mid-run — while
letting the step survive a provider outage.

Quotas are counted here, not at the provider. Ours is an estimate of theirs: we
see our own requests and the tokens the run reports, never their clock or their
other clients. That is why the threshold is below 1.0 — the margin absorbs the
difference instead of pretending there is none.
"""

import asyncio
import hashlib
import json
import logging
import math
import os
import pathlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

#: Route the free cloud first and keep the local runtime as the last resort
#: (D3), or never leave the machine at all.
FREE_CLOUD_FIRST = "free-cloud-first"
LOCAL_ONLY = "local-only"
PROVIDER_POLICIES = frozenset({FREE_CLOUD_FIRST, LOCAL_ONLY})
DEFAULT_POLICY = FREE_CLOUD_FIRST

#: Conditions that retire a candidate and move to the next one. A wrong answer
#: is not one of them: only refusals to answer justify changing provider.
FALLBACK_STATUS = frozenset({402, 408, 429, 500, 502, 503, 504})

_CONFIG = pathlib.Path(__file__).resolve().parents[1] / "config" / "cmh_free_quotas.json"
_WINDOW_KINDS = {"minute": timedelta(minutes=1), "day": timedelta(days=1)}


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- policy -----------------------------------------------------------------

def normalize_policy(value: Any) -> Optional[str]:
    """A recognised policy name, or None when the level does not set one."""
    name = str(value or "").strip().lower()
    return name if name in PROVIDER_POLICIES else None


def resolve_policy(step: Any = None, agent: Any = None, automation: Any = None) -> str:
    """Policy of the most specific level that defines one: step > agent > automation.

    Precedence is by specificity, not by who wrote it last: a step that names a
    policy means *this step*, and an agent-wide or schedule-wide default must
    not override it. Levels that define nothing are skipped, so an automation's
    default still applies to steps that stay silent.
    """
    for level in (step, agent, automation):
        if level is None:
            continue
        raw = level.get("provider_policy") if isinstance(level, dict) else getattr(
            level, "provider_policy", None)
        policy = normalize_policy(raw)
        if policy:
            return policy
    return DEFAULT_POLICY


# --- quota configuration ----------------------------------------------------

def load_quota_config(path: Optional[pathlib.Path] = None) -> dict:
    """Read config/cmh_free_quotas.json. A missing file means no known limits.

    Missing limits do not mean unlimited: they mean unmeasured. The router then
    cannot pre-empt a 429, and falls back reactively when one arrives.
    """
    target = pathlib.Path(path or os.environ.get("CMH_FREE_QUOTAS", _CONFIG))
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Free-tier quotas unreadable (%s); running without pre-emptive limits", exc)
        return {"threshold": 0.9, "providers": []}
    data.setdefault("threshold", 0.9)
    data.setdefault("providers", [])
    return data


def provider_for_host(config: dict, host: str) -> Optional[dict]:
    for provider in config.get("providers", []):
        if str(provider.get("endpoint_host", "")).lower() == (host or "").lower():
            return provider
    return None


# --- quota windows ----------------------------------------------------------

def window_start(kind: str, at: Optional[datetime] = None) -> datetime:
    """Start of the window `at` falls in. Truncation, never a rolling window.

    A rolling window would need the request log this table exists to avoid.
    """
    moment = at or now()
    if kind == "minute":
        return moment.replace(second=0, microsecond=0)
    if kind == "day":
        return moment.replace(hour=0, minute=0, second=0, microsecond=0)
    raise ValueError(f"Unknown window kind: {kind}")


def _usage_row(db, endpoint_id: str, kind: str, at: Optional[datetime] = None):
    from core.database import CMHProviderQuota
    start = window_start(kind, at)
    return db.query(CMHProviderQuota).filter(
        CMHProviderQuota.endpoint_id == endpoint_id,
        CMHProviderQuota.window_kind == kind,
        CMHProviderQuota.window_start == start).first()


def record_usage(db, endpoint_id: str, requests: int = 1, tokens_in: int = 0,
                 tokens_out: int = 0, at: Optional[datetime] = None) -> None:
    """Add one call's consumption to both windows of this endpoint."""
    from core.database import CMHProviderQuota
    for kind in ("minute", "day"):
        row = _usage_row(db, endpoint_id, kind, at)
        if row is None:
            row = CMHProviderQuota(id=str(uuid.uuid4()), endpoint_id=endpoint_id,
                                   window_kind=kind, window_start=window_start(kind, at),
                                   requests=0, tokens_in=0, tokens_out=0)
            db.add(row)
        row.requests += requests
        row.tokens_in += tokens_in
        row.tokens_out += tokens_out


def usage_snapshot(db, endpoint_id: str, at: Optional[datetime] = None) -> dict:
    """Current consumption per window. Zeros when the window just turned over."""
    snapshot = {}
    for kind in ("minute", "day"):
        row = _usage_row(db, endpoint_id, kind, at)
        snapshot[kind] = {
            "window_start": window_start(kind, at).isoformat(),
            "requests": row.requests if row else 0,
            "tokens_in": row.tokens_in if row else 0,
            "tokens_out": row.tokens_out if row else 0,
        }
    return snapshot


_LIMIT_FIELDS = (
    ("rpm", "minute", "requests"),
    ("tpm", "minute", "tokens"),
    ("rpd", "day", "requests"),
    ("tpd", "day", "tokens"),
)


def quota_exceeded(db, endpoint_id: str, limits: dict, threshold: float = 0.9,
                   at: Optional[datetime] = None) -> Optional[str]:
    """Name the limit this endpoint is at or over `threshold` of, or None.

    Checked *before* sending, so the call that would cross the line is never
    made: the router moves to the next candidate instead of spending the last
    request of the window and taking a 429 on the following one.
    """
    snapshot = usage_snapshot(db, endpoint_id, at)
    for field, kind, measure in _LIMIT_FIELDS:
        limit = (limits or {}).get(field)
        if not limit:
            continue  # unmeasured, not unlimited
        window = snapshot[kind]
        used = (window["requests"] if measure == "requests"
                else window["tokens_in"] + window["tokens_out"])
        if used >= limit * threshold:
            return field
    return None


# --- candidate resolution ---------------------------------------------------

def _endpoint_rows(db, owner: Optional[str]) -> list:
    from core.database import ModelEndpoint
    from src.auth_helpers import owner_filter
    query = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True)  # noqa: E712
    return owner_filter(query, ModelEndpoint, owner or None).all()


def _note_dropped(dropped: Optional[list], row, host: str, reason: str) -> None:
    if dropped is not None:
        dropped.append({"endpoint_id": row.id, "host": host, "reason": reason})


def resolve_candidates(db, policy: str = DEFAULT_POLICY, owner: Optional[str] = None,
                       local_model: Optional[str] = None,
                       config: Optional[dict] = None,
                       discovered: Optional[dict] = None,
                       dropped: Optional[list] = None) -> list[dict]:
    """The ordered candidate list a step freezes, under this policy.

    ``free-cloud-first``: the free providers in the order the config declares,
    then every enabled local runtime. ``local-only``: local runtimes alone, so
    nothing leaves the machine. Every candidate is checked against the cost gate
    on the way out, so a misconfigured row cannot enter the list at all.

    ``discovered`` maps a host to the model :func:`discover_free_models` picked
    for it. The config wins: a model written there is never replaced by one
    found at run time.

    A local runtime is called with, in order: the explicit ``local_model``, the
    config's ``local.model`` (the identifier LM Studio was loaded under, so it
    does not change when the winning model does), or what the runtime has
    cached. Never the model of the agent: that is a cloud name.

    A row that cannot enter the list is not skipped in silence: when ``dropped`` is a
    list it receives ``{"endpoint_id", "host", "reason"}`` for it. The reasons are
    ``credential_in_url`` (the URL carries user:pass@; see
    :func:`~src.cmh_cost_policy.has_userinfo`) and ``cost_gate`` (the gate refuses the
    row for that model: plain http on a free host, a model that is not ``:free``).
    """
    from src.cmh_cost_policy import (
        endpoint_host, has_userinfo, is_local_endpoint, is_zero_cost_endpoint,
    )

    settings = config or load_quota_config()
    rows = _endpoint_rows(db, owner)
    candidates: list[dict] = []

    if policy != LOCAL_ONLY:
        for provider in sorted(settings.get("providers", []),
                               key=lambda p: p.get("order", 99)):
            host = str(provider.get("endpoint_host", "")).lower()
            model = provider.get("model") or (discovered or {}).get(host)
            if not model:
                continue  # PENDIENTE in the config and not discovered: nothing to freeze
            for row in rows:
                if endpoint_host(getattr(row, "base_url", "")) != host:
                    continue
                if has_userinfo(row.base_url):
                    _note_dropped(dropped, row, host, "credential_in_url")
                    continue
                if not is_zero_cost_endpoint(row, model):
                    _note_dropped(dropped, row, host, "cost_gate")
                    continue
                candidates.append({"endpoint_id": row.id, "endpoint_url": row.base_url,
                                   "model": model, "host": host})
                break

    configured_local = (settings.get("local") or {}).get("model")
    for row in rows:
        if not is_local_endpoint(row):
            continue
        if has_userinfo(row.base_url):
            _note_dropped(dropped, row, endpoint_host(row.base_url), "credential_in_url")
            continue
        model = local_model or configured_local or _first_cached_model(row)
        if not model:
            continue
        candidates.append({"endpoint_id": row.id, "endpoint_url": row.base_url,
                           "model": model, "host": endpoint_host(row.base_url)})
    return candidates


def _first_cached_model(row) -> Optional[str]:
    from src.endpoint_resolver import _first_chat_model
    try:
        return _first_chat_model(json.loads(getattr(row, "cached_models", None) or "[]"))
    except ValueError:
        return None


def usable_candidates(db, candidates: Iterable[dict], config: Optional[dict] = None,
                      at: Optional[datetime] = None) -> tuple[list[dict], list[dict]]:
    """Split frozen candidates into (usable now, skipped) by remaining quota.

    Returns the skipped ones too, with the limit that retired each, so the
    caller can emit one event per skip instead of dropping them silently.
    """
    settings = config or load_quota_config()
    threshold = float(settings.get("threshold", 0.9))
    usable, skipped = [], []
    for candidate in candidates or []:
        provider = provider_for_host(settings, candidate.get("host", ""))
        limits = (provider or {}).get("limits") or {}
        hit = quota_exceeded(db, candidate["endpoint_id"], limits, threshold, at)
        (skipped if hit else usable).append(
            {**candidate, "reason": f"quota:{hit}"} if hit else candidate)
    return usable, skipped


def is_fallback_error(exc: BaseException) -> Optional[str]:
    """The reason to try the next candidate, or None to fail the step here.

    Only refusals to answer move on: a rate limit, a payment demand, a timeout
    or a server fault. A bad answer, an auth failure or a bad request are
    configuration problems that the next provider would hit too.
    """
    status = getattr(getattr(exc, "response", None), "status_code", None) or getattr(
        exc, "status_code", None)
    # Any 5xx, not an enumeration of them. The list used to name 500/502/503/504
    # while the commit said "5xx", so 501, 505 and the 529 that providers send
    # when overloaded fell through to killing the step.
    if status in FALLBACK_STATUS or (isinstance(status, int) and 500 <= status <= 599):
        return f"http:{status}"
    if isinstance(exc, TimeoutError):
        return "timeout"
    name = type(exc).__name__
    if name in {"ConnectTimeout", "ReadTimeout", "ConnectError", "ReadError", "PoolTimeout"}:
        return f"connection:{name}"
    return None


def pick_openrouter_free_model(models: Any) -> Optional[str]:
    """First `:free` model that declares tool calling, longest context first.

    The rule the brief fixes, kept pure so it can be tested without a key: the
    payload of ``GET /models`` goes in, a model id comes out.

    A model that does not declare ``tools`` is skipped rather than tried. The
    chain's steps read files, so a model without tool calling cannot satisfy
    ``require_tool_evidence`` and would burn a step's whole round budget before
    failing — the 2026-09-24 measurement of `deepseek-r1:7b`, which answered
    fluently and never called a tool.

    Longest context first because the late steps carry every earlier artifact,
    and a dependency is cut at 40 000 characters per artifact.
    """
    # One definition of what ":free" means, shared with the cost gate: if the
    # two ever disagreed, the router would freeze a model the gate then blocks.
    from src.cmh_cost_policy import _FREE_SUFFIX

    # A payload of the wrong shape is "no model", never an exception: a provider
    # that answers {"data": null}, {"data": 5} or a context_length of 1e999 is a bad
    # payload, not a crash in the run that asked which model to use.
    entries = models.get("data") if isinstance(models, dict) else models
    if not isinstance(entries, list):
        return None
    usable = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        model_id = str(entry.get("id") or "")
        if not model_id.lower().endswith(_FREE_SUFFIX):
            continue
        supported = entry.get("supported_parameters")
        if not isinstance(supported, list) or "tools" not in [str(p).lower() for p in supported]:
            continue
        try:
            context = int(entry.get("context_length") or 0)
        except (TypeError, ValueError, OverflowError):
            context = 0
        usable.append((-context, model_id))
    usable.sort()
    return usable[0][1] if usable else None


# --- model discovery --------------------------------------------------------

#: Hosts whose model is not written in the config but picked, by a rule, from the
#: provider's own catalogue. Any other host with a null model stays PENDIENTE.
_DISCOVERY_RULES = {"openrouter.ai": pick_openrouter_free_model}

#: Starting values, proposed and parametrizable under "discovery" in
#: config/cmh_free_quotas.json. The catalogue changes slowly, so it is asked for
#: at most once per TTL. ``timeout_s`` is the TOTAL time one provider may keep the
#: creation of a run waiting, both requests included. A failure is remembered for
#: ``failure_ttl_s`` so a provider that is down does not cost every new run the
#: full timeout, and a choice made from the general list, which the account's
#: settings did not filter, is trusted for ``unfiltered_ttl_s`` only.
_DEFAULT_DISCOVERY = {"ttl_s": 21600, "timeout_s": 15, "failure_ttl_s": 60,
                      "unfiltered_ttl_s": 900}
_DISCOVERY_CACHE: dict = {}


def clear_discovery_cache() -> None:
    _DISCOVERY_CACHE.clear()


def discovery_knobs(settings: dict) -> dict:
    """The discovery knobs: the config's, where it wrote a positive number.

    ``ttl_s: null`` used to raise TypeError after a successful discovery and
    ``timeout_s: null`` reached httpx as "no limit". Anything that is not a finite
    positive number is ignored, with a warning, and the default stays.
    """
    knobs = dict(_DEFAULT_DISCOVERY)
    for name, value in ((settings or {}).get("discovery") or {}).items():
        if name not in knobs:
            continue
        valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                 and math.isfinite(value) and value > 0)
        if not valid:
            logger.warning("cmh_free_quotas.json: discovery.%s = %r no es un numero positivo; "
                           "se usa %s", name, value, knobs[name])
            continue
        knobs[name] = float(value)
    return knobs


def _cache_key(row) -> tuple:
    """One entry per (row, URL, key): rotating the key or repointing the row starts over.

    Indexing by row id alone served the previous account's model for up to six
    hours after the key changed. Only a hash of the key is kept, never the key.
    """
    secret = str(getattr(row, "api_key", None) or "")
    return (getattr(row, "id", None), getattr(row, "base_url", None),
            hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16])


async def _get_json(client, url: str, headers: dict, timeout: float):
    """``(payload, reason, status)``: a JSON body, or why there is none. Never raises."""
    import httpx
    try:
        response = await client.get(url, headers=headers, timeout=timeout)
    except httpx.InvalidURL:
        return None, "invalid url", None
    except httpx.HTTPError as exc:
        return None, f"connection:{type(exc).__name__}", None
    if response.status_code != 200:
        return None, f"http:{response.status_code}", response.status_code
    try:
        return response.json(), None, 200
    except ValueError:
        return None, "invalid json", 200


async def _discover_one(row, rule, knobs: dict) -> dict:
    """Ask one endpoint for its catalogue and let ``rule`` pick a model.

    The account's own list (``/models/user``) is asked first: it is filtered by
    the account's provider preferences and privacy settings, which is what makes
    the setting the user is asked to change in U2 decide which ``:free`` models
    are eligible. The general list (``/models``) is used ONLY when that route is
    not there, that is when it answers 404. Any other failure (401, 403, 429, 5xx,
    a timeout, an invalid body) fails the discovery: widening on those would pick
    a model the account's own settings exclude, exactly when the filtered list
    could not be read.

    Nothing is sent without the registered key, and never over plain http. Nothing
    here ever reads the key into a note: it goes into the request headers only.
    """
    from src import llm_core
    from src.cmh_cost_policy import endpoint_scheme, has_userinfo
    from src.endpoint_resolver import build_headers, build_models_url, normalize_base

    api_key = str(getattr(row, "api_key", None) or "").strip()
    if not api_key:
        return {"model": None, "source": None, "reason": "no api key"}
    if endpoint_scheme(getattr(row, "base_url", "")) != "https":
        return {"model": None, "source": None, "reason": "not https"}
    if has_userinfo(getattr(row, "base_url", "")):
        # httpx would turn the userinfo into Authorization: Basic next to the key we send.
        return {"model": None, "source": None, "reason": "credential in url"}
    try:
        base = normalize_base(getattr(row, "base_url", ""))
        models_url = build_models_url(base)
    except ValueError:
        return {"model": None, "source": None, "reason": "invalid url"}
    if not models_url:
        return {"model": None, "source": None, "reason": "no models url"}
    headers = build_headers(api_key, base)
    client = llm_core._get_http_client()

    payload, reason, status = await _get_json(client, models_url + "/user", headers,
                                              knobs["timeout_s"])
    source, note = "models/user", None
    if status == 404:
        payload, reason, status = await _get_json(client, models_url, headers, knobs["timeout_s"])
        source = "models"
        note = "models/user no existe (404): se uso el listado general, sin el filtro de la cuenta"
    if reason:
        return {"model": None, "source": None, "reason": reason}
    try:
        model = rule(payload)
    except Exception as exc:  # a rule is code we wrote, a payload is not
        return {"model": None, "source": source,
                "reason": f"unexpected payload:{type(exc).__name__}"}
    if model:
        return {"model": model, "source": source, "reason": note}
    return {"model": None, "source": source,
            "reason": ("no eligible model in the account's own list" if source == "models/user"
                       else "no eligible model")}


async def discover_free_models(db, owner: Optional[str] = None,
                               config: Optional[dict] = None,
                               at: Optional[datetime] = None) -> tuple[dict, list[dict]]:
    """Pick the model of every provider whose config entry leaves it PENDIENTE.

    Returns ``({host: model}, notes)``. One note per attempt, safe to store and
    stream: provider, outcome (ok | cached | failed), model, source, reason. A
    failed discovery leaves that provider out of the list instead of failing the
    run — the chain continues with what it has — but the note says why, so a
    missing OpenRouter is never a silent one.
    """
    from src.cmh_cost_policy import endpoint_host

    settings = config or load_quota_config()
    knobs = discovery_knobs(settings)
    moment = at or now()
    found: dict = {}
    notes: list[dict] = []
    rows = None
    for provider in sorted(settings.get("providers", []), key=lambda p: p.get("order", 99)):
        host = str(provider.get("endpoint_host", "")).lower()
        rule = _DISCOVERY_RULES.get(host)
        if provider.get("model") or rule is None:
            continue  # pinned in the config, or nothing to pick it with
        if rows is None:
            rows = _endpoint_rows(db, owner)
        row = next((r for r in rows if endpoint_host(getattr(r, "base_url", "")) == host), None)
        if row is None:
            continue  # no account registered yet: absence is already visible
        key = _cache_key(row)
        cached = _DISCOVERY_CACHE.get(key)
        if cached and cached["expires"] > moment:
            if cached["model"]:
                found[host] = cached["model"]
                notes.append({"provider": host, "outcome": "cached", "model": cached["model"],
                              "source": cached["source"], "reason": cached["reason"]})
            else:
                notes.append({"provider": host, "outcome": "failed", "model": None,
                              "source": cached["source"],
                              "reason": f"{cached['reason']} (fallo reciente, no se reintenta aun)"})
            continue
        try:
            result = await asyncio.wait_for(_discover_one(row, rule, knobs),
                                            timeout=knobs["timeout_s"])
        except asyncio.TimeoutError:
            result = {"model": None, "source": None, "reason": "timeout"}
        if result["model"]:
            found[host] = result["model"]
            ttl = knobs["ttl_s"] if result["source"] == "models/user" else knobs["unfiltered_ttl_s"]
        else:
            ttl = knobs["failure_ttl_s"]
        _DISCOVERY_CACHE[key] = {**result, "expires": moment + timedelta(seconds=ttl)}
        notes.append({"provider": host, "outcome": "ok" if result["model"] else "failed",
                      "model": result["model"], "source": result["source"],
                      "reason": result["reason"]})
    return found, notes
