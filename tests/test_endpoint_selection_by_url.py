"""Picking one endpoint when several enabled rows share a base URL.

A scheduled task stores an endpoint URL, not an endpoint id, so duplicates are
resolvable only by ranking. The repro this guards against: two enabled
Anthropic endpoints, the task took whichever row came first and got a 401 while
chat, which resolves by id, used the working one.
"""
import json

from src.endpoint_resolver import select_endpoint_for_url


class _Ep:
    """Minimal ModelEndpoint stand-in: only the fields the selector reads."""

    def __init__(self, id, base_url, api_key=None, cached=None, hidden=None):
        self.id = id
        self.base_url = base_url
        self.api_key = api_key
        self.cached_models = json.dumps(cached) if cached is not None else None
        self.hidden_models = json.dumps(hidden) if hidden is not None else None
        self.pinned_models = None


URL = "https://api.anthropic.com/v1/messages"


def test_no_candidate_when_nothing_matches():
    assert select_endpoint_for_url([_Ep("a", "http://127.0.0.1:11434/v1")], URL) is None
    assert select_endpoint_for_url([], URL) is None
    assert select_endpoint_for_url([_Ep("a", "https://api.anthropic.com")], "") is None


def test_single_match_is_returned_whatever_its_shape():
    ep = _Ep("only", "https://api.anthropic.com")
    assert select_endpoint_for_url([ep], URL) is ep


def test_prefers_the_endpoint_that_lists_the_model():
    stale = _Ep("aaa-first-by-id", "https://api.anthropic.com", api_key="k1")
    working = _Ep("zzz-last-by-id", "https://api.anthropic.com", api_key="k2",
                  cached=["claude-sonnet-4-5-20250929"])
    # Row order must not decide it: same answer both ways round.
    for rows in ([stale, working], [working, stale]):
        assert select_endpoint_for_url(rows, URL, "claude-sonnet-4-5-20250929") is working


def test_an_endpoint_that_hides_the_model_ranks_last():
    hides = _Ep("aaa", "https://api.anthropic.com", api_key="k1",
                cached=["claude-sonnet-4-5-20250929"], hidden=["claude-sonnet-4-5-20250929"])
    silent = _Ep("bbb", "https://api.anthropic.com", api_key="k2")
    assert select_endpoint_for_url([hides, silent], URL, "claude-sonnet-4-5-20250929") is silent


def test_a_usable_key_beats_a_better_looking_model_list():
    """The caller builds headers from api_key alone. A row that merely LOOKS
    better (its probe cached the model) but carries no credential produces no
    auth header — the 401 this selection exists to avoid."""
    keyless_but_listed = _Ep("aaa", "https://api.anthropic.com", cached=["claude-x"])
    keyed_but_silent = _Ep("bbb", "https://api.anthropic.com", api_key="k")
    for rows in ([keyless_but_listed, keyed_but_silent], [keyed_but_silent, keyless_but_listed]):
        assert select_endpoint_for_url(rows, URL, "claude-x") is keyed_but_silent


def test_a_session_credential_row_does_not_displace_a_keyed_row():
    """A provider_auth_id row (ChatGPT-style subscription) has api_key NULL and
    a populated cache. The scheduler cannot resolve session credentials, so it
    must not pick that row over one with a static key."""
    session_row = _Ep("aaa", "https://api.openai.com/v1", cached=["gpt-5"])
    session_row.provider_auth_id = "sess-1"
    keyed = _Ep("bbb", "https://api.openai.com/v1", api_key="sk-real")
    assert select_endpoint_for_url([session_row, keyed],
                                   "https://api.openai.com/v1/chat/completions", "gpt-5") is keyed


def test_a_hidden_model_loses_even_to_a_keyless_row():
    """Hidden means the probe failed there or an admin disabled it: that row
    cannot serve the model at all, so a credential does not redeem it."""
    keyed_but_hidden = _Ep("aaa", "https://api.anthropic.com", api_key="k", hidden=["claude-x"])
    keyless = _Ep("bbb", "https://api.anthropic.com")
    assert select_endpoint_for_url([keyed_but_hidden, keyless], URL, "claude-x") is keyless


def test_an_exact_base_still_wins_without_a_key_because_local_models_need_none():
    """Deliberate: a local endpoint legitimately has no key, so an exact base
    match must not lose to a keyed substring match pointing elsewhere."""
    exact_local = _Ep("aaa", "http://127.0.0.1:11434/v1")
    keyed_broader = _Ep("bbb", "http://127.0.0.1:11434", api_key="k")
    assert select_endpoint_for_url([keyed_broader, exact_local],
                                   "http://127.0.0.1:11434/v1/chat/completions", "qwen3:8b") is exact_local


def test_a_key_beats_no_key_when_neither_lists_the_model():
    keyless = _Ep("aaa", "https://api.anthropic.com")
    keyed = _Ep("bbb", "https://api.anthropic.com", api_key="k")
    assert select_endpoint_for_url([keyless, keyed], URL, "some-model") is keyed


def test_an_exact_base_beats_a_substring_match():
    # The local-model shape: normalize_base leaves the /v1 on, so the row
    # registered with /v1 matches exactly and the bare host only by substring.
    loose = _Ep("aaa", "http://127.0.0.1:11434", api_key="k1")
    exact = _Ep("bbb", "http://127.0.0.1:11434/v1", api_key="k2")
    url = "http://127.0.0.1:11434/v1/chat/completions"
    assert select_endpoint_for_url([loose, exact], url, "qwen3:8b") is exact
    assert select_endpoint_for_url([exact, loose], url, "qwen3:8b") is exact


def test_ties_break_on_id_so_the_choice_is_reproducible():
    first = _Ep("aaa", "https://api.anthropic.com", api_key="k1")
    second = _Ep("bbb", "https://api.anthropic.com", api_key="k2")
    assert select_endpoint_for_url([second, first], URL) is first
    assert select_endpoint_for_url([first, second], URL) is first


def test_rows_without_a_base_url_are_skipped():
    broken = _Ep("aaa", "")
    good = _Ep("bbb", "https://api.anthropic.com", api_key="k")
    assert select_endpoint_for_url([broken, good], URL) is good


def test_scheduler_uses_the_selector_for_its_headers():
    """The fix is worthless if the scheduler still loops over rows itself."""
    source = __import__("pathlib").Path("src/task_scheduler.py").read_text(encoding="utf-8")
    assert "normalize_base(ep.base_url) in endpoint_url" not in source
    assert source.count("select_endpoint_for_url(eps, endpoint_url") == 2
