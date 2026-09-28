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

import json
import logging
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


def resolve_candidates(db, policy: str = DEFAULT_POLICY, owner: Optional[str] = None,
                       local_model: Optional[str] = None,
                       config: Optional[dict] = None) -> list[dict]:
    """The ordered candidate list a step freezes, under this policy.

    ``free-cloud-first``: the free providers in the order the config declares,
    then every enabled local runtime. ``local-only``: local runtimes alone, so
    nothing leaves the machine. Every candidate is checked against the cost gate
    on the way out, so a misconfigured row cannot enter the list at all.
    """
    from src.cmh_cost_policy import endpoint_host, is_local_endpoint, is_zero_cost_endpoint

    settings = config or load_quota_config()
    rows = _endpoint_rows(db, owner)
    candidates: list[dict] = []

    if policy != LOCAL_ONLY:
        for provider in sorted(settings.get("providers", []),
                               key=lambda p: p.get("order", 99)):
            host = str(provider.get("endpoint_host", "")).lower()
            model = provider.get("model")
            if not model:
                continue  # PENDIENTE in the config: nothing to freeze yet
            for row in rows:
                if endpoint_host(getattr(row, "base_url", "")) != host:
                    continue
                if not is_zero_cost_endpoint(row, model):
                    continue
                candidates.append({"endpoint_id": row.id, "endpoint_url": row.base_url,
                                   "model": model, "host": host})
                break

    for row in rows:
        if not is_local_endpoint(row):
            continue
        model = local_model or _first_cached_model(row)
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
    if status in FALLBACK_STATUS:
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

    # `or []` on both branches: a provider that answers {"data": null} is a
    # bad payload, not a crash in the step that asked which model to use.
    entries = (models.get("data") if isinstance(models, dict) else models) or []
    usable = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        model_id = str(entry.get("id") or "")
        if not model_id.lower().endswith(_FREE_SUFFIX):
            continue
        supported = entry.get("supported_parameters") or []
        if "tools" not in [str(p).lower() for p in supported]:
            continue
        try:
            context = int(entry.get("context_length") or 0)
        except (TypeError, ValueError):
            context = 0
        usable.append((-context, model_id))
    usable.sort()
    return usable[0][1] if usable else None
