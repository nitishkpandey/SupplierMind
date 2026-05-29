"""Task 1.6 Component C — sanctions cache + bounded backoff + pending_review.

No network: _fetch is monkeypatched to return canned (status_code, json) pairs,
and sleep is recorded instead of real waiting. The contract under test:
  - cache: same company within TTL returns without a second API call
  - backoff: 429/5xx retries 1s/2s/4s, then returns pending_review (not "clear")
  - no silent failures: every result has an explicit status
"""

import pytest

from app.services.sanctions import (
    _SANCTIONS_CACHE,
    SanctionsService,
    normalize_company_name,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    _SANCTIONS_CACHE.clear()
    yield
    _SANCTIONS_CACHE.clear()


def make_service(responses, slept):
    """Service whose _fetch yields each response in turn; records sleeps."""
    svc = SanctionsService(sleep=lambda s: slept.append(s))
    seq = iter(responses)

    def fake_fetch(name):
        item = next(seq)
        if isinstance(item, Exception):
            raise item
        return item

    svc._fetch = fake_fetch
    return svc


HIT = (200, {"results": [{"score": 0.9, "datasets": ["eu_fsf_sanctions"]}]})
CLEAN = (200, {"results": []})


# ── normalize_company_name ───────────────────────────────────────────
def test_normalize_strips_suffix_case_and_whitespace():
    assert normalize_company_name("  ACME GmbH ") == "acme"
    assert normalize_company_name("Foo Ltd.") == "foo"
    assert normalize_company_name("Bar B.V.") == "bar"


def test_normalize_keeps_distinct_names_distinct():
    assert normalize_company_name("Acme Steel") != normalize_company_name("Acme Plastics")


# ── interpret / verdicts ─────────────────────────────────────────────
def test_sanctions_match_is_flagged():
    svc = make_service([HIT], [])
    r = svc.screen_company("Bad Corp")
    assert r.is_flagged is True
    assert r.status == "flagged"


def test_no_results_is_clear():
    svc = make_service([CLEAN], [])
    r = svc.screen_company("Good Corp")
    assert r.is_flagged is False
    assert r.status == "clear"


# ── cache ────────────────────────────────────────────────────────────
def test_second_call_hits_cache_no_api(caplog):
    calls = []
    svc = SanctionsService(sleep=lambda s: None)
    svc._fetch = lambda name: (calls.append(name), CLEAN)[1]
    svc.screen_company("Cached Co")
    svc.screen_company("Cached Co")
    assert len(calls) == 1  # second served from cache


def test_cache_key_is_normalized():
    calls = []
    svc = SanctionsService(sleep=lambda s: None)
    svc._fetch = lambda name: (calls.append(name), CLEAN)[1]
    svc.screen_company("ACME GmbH")
    svc.screen_company("  acme  ")  # normalizes to same key
    assert len(calls) == 1


# ── backoff + pending_review ─────────────────────────────────────────
def test_429_then_success_retries_with_backoff():
    slept = []
    svc = make_service([(429, None), HIT], slept)
    r = svc.screen_company("Flaky Corp")
    assert r.status == "flagged"
    assert slept == [1]  # one backoff before the successful retry


def test_persistent_429_returns_pending_review_not_clear():
    slept = []
    svc = make_service([(429, None), (429, None), (429, None)], slept)
    r = svc.screen_company("Throttled Corp")
    assert r.status == "pending_review"
    assert r.is_flagged is False
    assert r.reason  # explains why
    assert slept == [1, 2, 4]  # bounded 3-step backoff


def test_pending_review_is_not_cached():
    slept = []
    # First screen: persistent 429 → pending (must NOT poison cache).
    # Second screen: API recovers → clean verdict.
    svc = make_service([(429, None), (429, None), (429, None), CLEAN], slept)
    first = svc.screen_company("Recovering Corp")
    second = svc.screen_company("Recovering Corp")
    assert first.status == "pending_review"
    assert second.status == "clear"


def test_network_exception_retries_then_pending():
    slept = []
    svc = make_service(
        [RuntimeError("boom"), RuntimeError("boom"), RuntimeError("boom")], slept
    )
    r = svc.screen_company("Down Corp")
    assert r.status == "pending_review"
    assert slept == [1, 2, 4]
