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

import ipaddress
import logging
import os
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

#: The only values that switch the gate off. Everything else, including a typo or
#: an empty string, leaves it ON: a switch that guards money fails closed.
_OFF = {"0", "false", "no", "off"}

#: Hosts whose free tier the CMH chain is allowed to use. Exact host match,
#: never a suffix match: ``api.groq.com.example.net`` is not Groq.
#:
#: Cerebras was here until 2026-09-29 and was removed on measurement, not on
#: preference: it has no permanent free tier. Its trial is 5 USD of credit that
#: expires in 30 days, and the API goes inactive without a verified payment
#: method, so it fails the very condition D1 rests on — accounts with no card.
#: Canon 05, rows of 2026-09-29. Removing it from this set is what makes the
#: gate refuse ``api.cerebras.ai`` instead of treating it as free.
FREE_HOSTS = frozenset({"api.groq.com", "openrouter.ai"})

#: On OpenRouter only the ``:free`` model variants cost nothing; every other
#: model on the same host is billed against account credit.
FREE_MODEL_SUFFIX_HOSTS = frozenset({"openrouter.ai"})
_FREE_SUFFIX = ":free"

#: An admin who labels an endpoint ``api`` or ``proxy`` has declared it external.
#: A loopback URL under those kinds is a tunnel to somewhere else, so it is
#: never treated as a local runtime.
_EXTERNAL_KINDS = frozenset({"api", "proxy"})
_LOOPBACK_HOSTS = frozenset({"localhost", "0.0.0.0", "host.docker.internal"})

#: What "a private network" means for ``local-only``. ADR-026 sets the rule (loopback
#: or a private network) and ADR-032 fixes the list: RFC1918, link-local, and the
#: IPv6 unique-local range, which is RFC1918's analogue. Loopback is judged
#: separately, and the names in ``_LOOPBACK_HOSTS`` and ``*.local`` are ADR-032's too.
#: NOT 100.64.0.0/10 (carrier-grade NAT, where Tailscale lives). That is an ASSUMPTION
#: of ADR-032, not something ADR-026 says: a GPU behind Tailscale is outside
#: ``local-only`` until someone decides otherwise.
_PRIVATE_NETWORKS = tuple(ipaddress.ip_network(cidr) for cidr in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "169.254.0.0/16", "fe80::/10",
    "fc00::/7",
))


class ZeroCostViolation(Exception):
    """Raised when a paid route is about to be used by the CMH chain."""


def enforced() -> bool:
    """CMH_ZERO_COST (default on) turns the gate from blocking into logging.

    Only ``0``, ``false``, ``no`` or ``off`` switch it off; any other value, a
    typo or an empty string included, leaves it enforcing. It used to be the other
    way round (only ``1/true/yes/on`` kept it on), so ``CMH_ZERO_COST=enabled``
    silently turned the gate off. Switching off is a diagnostic setting: the
    violation is logged and the call proceeds. It is never an operating mode.
    """
    return os.environ.get("CMH_ZERO_COST", "true").strip().lower() not in _OFF


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


def endpoint_scheme(base_url: Optional[str]) -> str:
    """Scheme of a base URL (``urlparse`` already lowercases it), or "" if unparsable."""
    try:
        return urlparse(base_url or "").scheme
    except ValueError:
        return ""


def strip_userinfo(base_url: Optional[str]) -> str:
    """The URL without ``user:pass@``; path, query and fragment stay.

    What a run FREEZES for each candidate. A row whose base_url still carries
    credentials (ADR-026 lifts them into ``api_key`` on the way in, but a row written
    before that, or edited through a path that did not split them, still has them)
    must not put them into ``cmh_workflow_steps.config``. Unlike :func:`redact_url`
    this keeps the query: a provider may need ``?api-version=`` to be called at all.
    """
    if not base_url:
        return base_url or ""
    try:
        parts = urlparse(base_url)
    except ValueError:
        return base_url
    if "@" not in parts.netloc:
        return base_url
    return parts._replace(netloc=parts.netloc.rsplit("@", 1)[-1]).geturl()


def redact_url(base_url: Optional[str]) -> str:
    """The URL without credentials, query or fragment: safe for a message or an event.

    A base URL may carry ``user:pass@`` (ADR-026 moves it to ``api_key`` on the way
    in, but a row written before that, or by a path that does not split it, still
    has it) or a key in the query string. Anything that prints a URL goes through here.
    """
    if not base_url:
        return ""
    try:
        parts = urlparse(base_url)
        host = parts.netloc.rsplit("@", 1)[-1]
        return urlunparse((parts.scheme, host, parts.path, "", "", ""))
    except ValueError:
        return "URL no interpretable"


def is_reachable_without_leaving_the_network(host: str) -> bool:
    """Whether a host is loopback or on a private network.

    Decision of 2026-09-29: ``local-only`` means loopback **or** a private
    network (RFC1918, link-local, ``.local``), so a GPU on CMH's own LAN counts
    and a public host does not. Before this, the label alone decided: a row an
    admin marked ``local`` on ``https://gpu.corp.example/v1`` passed both this
    and the cost gate, and ``local-only`` — a policy whose docstring promises
    nothing leaves the machine — froze it at the head of the list.
    """
    name = (host or "").strip().lower().rstrip(".")
    if not name:
        return False
    if name in _LOOPBACK_HOSTS or name.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(name.strip("[]"))
    except ValueError:
        return False
    # Named networks, not ``address.is_private``. That property is whatever the
    # running Python says it is: it includes 192.0.2.0/24 (documentation),
    # 240.0.0.0/4 (reserved) and more than the decision lists, and it has moved
    # between releases. It also made ``is_link_local`` redundant, which is how a
    # mutant dropping link-local survived: the measured 2026-09-29 result was that
    # nothing distinguished the two. This gate is where "costs nothing" is decided,
    # so it says exactly what ADR-032 lists (ADR-026 plus fc00::/7 and the names).
    return bool(address.is_loopback or any(
        address.version == network.version and address in network
        for network in _PRIVATE_NETWORKS))


def is_local_endpoint(endpoint: Any) -> bool:
    """Whether this endpoint is a local runtime, and therefore free.

    The HOST decides, not the label. ``endpoint_kind`` still disqualifies — an
    admin who wrote ``api`` or ``proxy`` declared a tunnel — but writing
    ``local`` on a public host no longer makes it local. ``auto`` is the
    database default, so a loopback endpoint nobody relabelled still counts.
    """
    kind = (_field(endpoint, "endpoint_kind") or "auto").strip().lower()
    if kind in _EXTERNAL_KINDS:
        return False
    return is_reachable_without_leaving_the_network(
        endpoint_host(_field(endpoint, "base_url")))


def is_zero_cost_endpoint(endpoint: Any, model: Optional[str] = None) -> bool:
    """Whether this endpoint, for this model, costs nothing to call.

    True for a local runtime, or for a host in :data:`FREE_HOSTS` reached over
    https: a free host over plain http would send the API key in the clear, and the
    gate does not call that route free. On OpenRouter the model must additionally
    end in ``:free``; an unknown model fails closed, because the gate cannot
    confirm what it cannot see.
    """
    if is_local_endpoint(endpoint):
        return True
    base_url = _field(endpoint, "base_url")
    host = endpoint_host(base_url)
    if host not in FREE_HOSTS:
        return False
    if endpoint_scheme(base_url) != "https":
        return False
    if host in FREE_MODEL_SUFFIX_HOSTS:
        name = (model or "").strip().lower()
        return name.endswith(_FREE_SUFFIX)
    return True


def describe(endpoint: Any, model: Optional[str] = None) -> str:
    """Short identification of a route, for messages and events. No secrets.

    The URL goes through :func:`redact_url`: this used to promise "no secrets" and
    print ``user:pass@host`` as stored, and the text of a ZeroCostViolation ends up
    in the detail of an HTTP 400.
    """
    endpoint_id = _field(endpoint, "id") or "sin id"
    base_url = redact_url(_field(endpoint, "base_url")) or "sin URL"
    return f"endpoint {endpoint_id} ({base_url}), modelo {model or 'sin modelo'}"


def assert_zero_cost(endpoint: Any, model: Optional[str] = None) -> None:
    """Raise :class:`ZeroCostViolation` unless the route is free.

    Honours :func:`enforced`: with the gate switched off (``CMH_ZERO_COST=false``)
    the violation is written to the log and the call proceeds, so switching it off
    leaves a trace instead of being silent.
    """
    if is_zero_cost_endpoint(endpoint, model):
        return
    if not enforced():
        logger.warning("Costo cero (D1) DESACTIVADO por CMH_ZERO_COST: se deja pasar %s",
                       describe(endpoint, model))
        return
    raise ZeroCostViolation(
        f"Costo cero (D1): {describe(endpoint, model)} no es gratuito. "
        f"Permitidos: endpoints locales y {', '.join(sorted(FREE_HOSTS))} por https "
        f"(en openrouter.ai, solo modelos terminados en '{_FREE_SUFFIX}')."
    )


def endpoint_for_url(db, endpoint_url: Optional[str], owner: Optional[str] = None,
                     model: Optional[str] = None):
    """The enabled endpoint row a URL resolves to, ON THE SAME HOST, or None.

    Starts from the runner's own ranking (``select_endpoint_for_url``), which
    matches by SUBSTRING: right for its job (picking among rows that share a base
    URL) and wrong for this one. A row for ``https://api.groq.com``
    substring-matches a task pointed at ``https://api.groq.com.attacker.example
    /v1``: the gate would clear the free row while the call dialled the other
    host. So a winner on a different host is discarded and the bare URL is
    judged on its own, where ``FREE_HOSTS`` refuses it by exact match.

    What this does NOT do: the runner (``task_scheduler._run_agent_loop``) still
    picks the row for its request headers with ``select_endpoint_for_url`` alone,
    so on a URL like that one it would attach the Groq key to the other host. The
    call never gets there, because this gate refuses the URL first and every CMH
    step passes through the gate; a task outside the CMH chain does not. That is
    upstream Odysseus behaviour and it is left as it is (reported by the review of 2026-09-29, P3 #32).
    """
    from core.database import ModelEndpoint
    from src.auth_helpers import owner_filter
    from src.endpoint_resolver import select_endpoint_for_url

    query = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True)  # noqa: E712
    query = owner_filter(query, ModelEndpoint, owner or None)
    row = select_endpoint_for_url(query.all(), endpoint_url or "", model)
    if row is not None and endpoint_host(getattr(row, "base_url", "")) != endpoint_host(endpoint_url):
        return None
    return row


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
