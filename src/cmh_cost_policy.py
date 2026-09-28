"""Zero-cost gate for CMH agents, workflow definitions and model candidates.

Decision D1 (2026-09-28): no CMH agent, workflow step or automation may reach a
paid endpoint. Only local runtimes and providers whose free tier we rely on are
allowed. The Anthropic endpoint stays registered for the user's personal chat;
it is simply never reachable from this side.

**What this gate can and cannot know.** The classification is *by host*. It
cannot see whether the account behind an API key has a payment method attached,
so it cannot tell a free tier from a paid one on the same host: an account with
a card on file at Groq bills normally and this function still returns True. That
half of the guarantee is operational, not technical — the account is registered
without a payment method — and it is stated here because a reader who takes this
for a billing guarantee would be wrong.

**Why this is not ``endpoint_cost_tracked``.** That neighbour
(``src/endpoint_resolver.py``) answers "should token cost be tallied for this
route", which is a heuristic over any global host and returns True for Groq,
Cerebras and OpenRouter alike. This gate answers the narrower "is this route
free of charge for us", which is an allowlist, not a heuristic. Reusing the
heuristic would block every free provider.
"""

import os
from typing import Any, Optional
from urllib.parse import urlparse

_TRUE = {"1", "true", "yes", "on"}

#: Hosts whose free tier the CMH chain is allowed to use (D3). Exact host
#: match, never a suffix match: ``api.groq.com.example.net`` is not Groq.
FREE_HOSTS = frozenset({"api.groq.com", "api.cerebras.ai", "openrouter.ai"})

#: On OpenRouter only the ``:free`` model variants cost nothing; every other
#: model on the same host is billed against account credit.
FREE_MODEL_SUFFIX_HOSTS = frozenset({"openrouter.ai"})
_FREE_SUFFIX = ":free"

#: An admin who labels an endpoint ``api`` or ``proxy`` has declared it external.
#: A loopback URL under those kinds is a tunnel to somewhere else, so it is
#: never treated as a local runtime.
_EXTERNAL_KINDS = frozenset({"api", "proxy"})
_LOOPBACK_HOSTS = frozenset({"localhost", "0.0.0.0", "host.docker.internal"})


class ZeroCostViolation(Exception):
    """Raised when a paid route is about to be used by the CMH chain."""


def enforced() -> bool:
    """CMH_ZERO_COST (default true) turns the gate from blocking into logging.

    ``false`` is a diagnostic setting: the violation is recorded and the call
    proceeds. It is never an operating mode.
    """
    return os.environ.get("CMH_ZERO_COST", "true").strip().lower() in _TRUE


def _field(endpoint: Any, name: str) -> Optional[str]:
    """Read a field from a ModelEndpoint row or from a plain dict."""
    if endpoint is None:
        return None
    if isinstance(endpoint, dict):
        value = endpoint.get(name)
    else:
        value = getattr(endpoint, name, None)
    return None if value is None else str(value)


def endpoint_host(base_url: Optional[str]) -> str:
    """Lowercased hostname of a base URL, or "" when it cannot be parsed."""
    try:
        host = urlparse(base_url or "").hostname or ""
    except ValueError:
        return ""
    return host.strip().lower().rstrip(".")


def is_local_endpoint(endpoint: Any) -> bool:
    """Whether this endpoint is a local runtime, and therefore free.

    ``endpoint_kind`` defaults to ``"auto"`` in the database, so gating on the
    literal string ``"local"`` alone would reject a loopback endpoint the admin
    never relabelled. An ``auto`` endpoint counts as local only when its host is
    itself loopback or link-local; ``auto`` plus a global host does not.
    """
    kind = (_field(endpoint, "endpoint_kind") or "auto").strip().lower()
    if kind in _EXTERNAL_KINDS:
        return False
    if kind == "local":
        return True
    host = endpoint_host(_field(endpoint, "base_url"))
    return bool(host) and (host in _LOOPBACK_HOSTS
                           or host.startswith("127.")
                           or host == "::1"
                           or host.endswith(".local"))


def is_zero_cost_endpoint(endpoint: Any, model: Optional[str] = None) -> bool:
    """Whether this endpoint, for this model, costs nothing to call.

    True for a local runtime, or for a host in :data:`FREE_HOSTS`. On OpenRouter
    the model must additionally end in ``:free``; an unknown model fails closed,
    because the gate cannot confirm what it cannot see.
    """
    if is_local_endpoint(endpoint):
        return True
    host = endpoint_host(_field(endpoint, "base_url"))
    if host not in FREE_HOSTS:
        return False
    if host in FREE_MODEL_SUFFIX_HOSTS:
        name = (model or "").strip().lower()
        return name.endswith(_FREE_SUFFIX)
    return True


def describe(endpoint: Any, model: Optional[str] = None) -> str:
    """Short identification of a route, for messages and events. No secrets."""
    endpoint_id = _field(endpoint, "id") or "sin id"
    base_url = _field(endpoint, "base_url") or "sin URL"
    return f"endpoint {endpoint_id} ({base_url}), modelo {model or 'sin modelo'}"


def assert_zero_cost(endpoint: Any, model: Optional[str] = None) -> None:
    """Raise :class:`ZeroCostViolation` unless the route is free.

    Honours :func:`enforced`: with ``CMH_ZERO_COST=false`` the caller is
    responsible for recording the violation and continuing.
    """
    if is_zero_cost_endpoint(endpoint, model):
        return
    if not enforced():
        return
    raise ZeroCostViolation(
        f"Costo cero (D1): {describe(endpoint, model)} no es gratuito. "
        f"Permitidos: endpoints locales y {', '.join(sorted(FREE_HOSTS))} "
        f"(en openrouter.ai, solo modelos terminados en '{_FREE_SUFFIX}')."
    )


def endpoint_for_url(db, endpoint_url: Optional[str], owner: Optional[str] = None,
                     model: Optional[str] = None):
    """The enabled endpoint row a URL resolves to, or None.

    Uses the same ranking the runner uses (``select_endpoint_for_url``), so the
    row this gate judges is the row the call will actually use. Judging a
    different row than the one that gets called would make the gate decorative.
    """
    from core.database import ModelEndpoint
    from src.auth_helpers import owner_filter
    from src.endpoint_resolver import select_endpoint_for_url

    query = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True)  # noqa: E712
    query = owner_filter(query, ModelEndpoint, owner or None)
    return select_endpoint_for_url(query.all(), endpoint_url or "", model)


def assert_zero_cost_url(db, endpoint_url: Optional[str], model: Optional[str] = None,
                         owner: Optional[str] = None) -> None:
    """Gate a route known only by its base URL, as tasks and steps store it.

    When no enabled row matches the URL the URL is judged on its own, as an
    ``auto`` endpoint. That is not a loophole: an unregistered loopback runtime
    is still free, and an unregistered paid host is still refused. Failing shut
    on every unmatched URL would instead block a local runtime for the sole
    reason that nobody had registered it yet.
    """
    endpoint = endpoint_for_url(db, endpoint_url, owner, model)
    if endpoint is None:
        endpoint = {"base_url": endpoint_url, "endpoint_kind": "auto",
                    "id": "no registrado"}
    assert_zero_cost(endpoint, model)
