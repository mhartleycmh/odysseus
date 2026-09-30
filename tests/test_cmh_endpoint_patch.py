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
