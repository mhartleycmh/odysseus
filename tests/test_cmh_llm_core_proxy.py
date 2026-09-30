"""Under ``local-only`` nothing leaves the machine, and that includes a system proxy.

httpx sends every request through HTTP_PROXY / HTTPS_PROXY / ALL_PROXY, and NO_PROXY can
name hosts but not a private RANGE. The review of 2026-09-29 measured, with a proxy set,
http://127.0.0.1:1234, http://localhost and http://192.168.1.50 all going through it. The
shared client now sends a route the cost gate calls local through its direct transport,
whatever the environment says. Nothing is sent here: the transport httpx WOULD pick is
asked for, which is the same decision the real request takes.
"""

import httpx
import pytest

import src.llm_core as llm_core

PROXY_VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


@pytest.fixture
def proxied(monkeypatch):
    for name in PROXY_VARIABLES:
        monkeypatch.setenv(name, "http://proxy.invalid:3128")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setattr(llm_core, "_http_client", None)
    client = llm_core._get_http_client()
    yield client
    monkeypatch.setattr(llm_core, "_http_client", None)


def test_the_environment_really_does_make_httpx_use_the_proxy(monkeypatch):
    """The control: a plain client, built with the same environment, proxies loopback. Without
    this the tests below could pass because no proxy was ever configured."""
    for name in PROXY_VARIABLES:
        monkeypatch.setenv(name, "http://proxy.invalid:3128")
    plain = httpx.AsyncClient()
    assert plain._transport_for_url(httpx.URL("http://127.0.0.1:1234/v1")) is not plain._transport


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:1234/v1", "http://localhost:1234/v1", "http://192.168.1.50:1234/v1",
    "http://10.0.0.5/v1", "http://172.16.0.9:1234/v1", "http://[::1]:1234/v1",
    "http://[fe80::1]:1/v1", "http://[fd00::7]:1/v1", "http://169.254.1.2/v1",
    "http://gpu.local:1234/v1", "http://host.docker.internal:1234/v1",
])
def test_a_local_route_never_goes_through_the_system_proxy(proxied, url):
    assert proxied._transport_for_url(httpx.URL(url)) is proxied._transport


@pytest.mark.parametrize("url", [
    "https://api.groq.com/openai/v1", "https://openrouter.ai/api/v1",
    "http://8.8.8.8/v1", "http://100.64.0.1:1234/v1", "http://192.169.0.1/v1",
])
def test_a_remote_route_still_uses_the_proxy(proxied, url):
    """The rule is 'what the gate calls local', not 'everything': a cloud call keeps the
    proxy the machine is configured with (100.64.0.0/10 is NOT local, ADR-032)."""
    assert proxied._transport_for_url(httpx.URL(url)) is not proxied._transport
