"""Feature 25 — eligibility result caching in Redis keyed by zip:payer:plan.

Uses a fake Redis (with TTL simulation) to assert: a repeated check within
the TTL is served from the cache without re-running the decision engine;
expiry triggers a fresh decision; partial inputs are never cached.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.eligibility.cache import CachedEligibilityDecider
from app.eligibility.decision import decide_eligibility
from app.eligibility.reference_data import load_reference_data
from app.redis_state import RedisState, eligibility_cache_key
from app.safety.eligibility import EligibilityStatus

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data" / "reference"

TTL_SECONDS = 300
SERVED_ZIP = "11201"
PAYER = "Medicare"
PLAN = "Medicare Part A"
SERVICE = "skilled_nursing"


class FakeRedisWithClock:
    """In-memory Redis stand-in with a manually advanced clock for TTLs."""

    def __init__(self):
        self.kv = {}
        self.expiry = {}
        self.now = 0.0

    def advance(self, seconds):
        self.now += seconds

    def set(self, key, value, ex=None):
        self.kv[key] = value
        if ex is not None:
            self.expiry[key] = self.now + ex

    def get(self, key):
        if key in self.expiry and self.now >= self.expiry[key]:
            self.kv.pop(key, None)
            self.expiry.pop(key, None)
        return self.kv.get(key)


@pytest.fixture(scope="module")
def data():
    return load_reference_data(DATA_DIR)


@pytest.fixture
def fake_redis():
    return FakeRedisWithClock()


@pytest.fixture
def decider(fake_redis, data):
    state = RedisState(fake_redis, eligibility_ttl_seconds=TTL_SECONDS)
    return CachedEligibilityDecider(state, data)


def test_first_check_is_a_miss_and_populates_cache(decider, fake_redis):
    decision = decider.decide(SERVED_ZIP, PAYER, PLAN, SERVICE, True)
    assert decision.status is EligibilityStatus.ACCEPT
    assert eligibility_cache_key(SERVED_ZIP, PAYER, PLAN) in fake_redis.kv


def test_repeated_check_hits_cache_without_second_traversal(decider, data):
    first = decider.decide(SERVED_ZIP, PAYER, PLAN, SERVICE, True)
    with patch(
        "app.eligibility.cache.decide_eligibility",
        side_effect=AssertionError("decision engine must not run on a cache hit"),
    ):
        second = decider.decide(SERVED_ZIP, PAYER, PLAN, SERVICE, True)
    assert second == first


def test_cache_expiry_triggers_fresh_decision(decider, fake_redis, data):
    decider.decide(SERVED_ZIP, PAYER, PLAN, SERVICE, True)
    fake_redis.advance(TTL_SECONDS + 1)
    expected = decide_eligibility(SERVED_ZIP, PAYER, PLAN, SERVICE, True, data)
    with patch(
        "app.eligibility.cache.decide_eligibility", return_value=expected
    ) as fresh:
        decision = decider.decide(SERVED_ZIP, PAYER, PLAN, SERVICE, True)
    fresh.assert_called_once()
    assert decision == expected


def test_entry_is_written_with_the_configured_short_ttl(decider, fake_redis):
    decider.decide(SERVED_ZIP, PAYER, PLAN, SERVICE, True)
    key = eligibility_cache_key(SERVED_ZIP, PAYER, PLAN)
    assert fake_redis.expiry[key] == fake_redis.now + TTL_SECONDS


def test_different_non_key_inputs_bypass_the_cached_entry(decider):
    accepted = decider.decide(SERVED_ZIP, PAYER, PLAN, SERVICE, True)
    assert accepted.status is EligibilityStatus.ACCEPT
    # Same zip:payer:plan key, but caregiver matching not run — must not
    # be served the cached ACCEPT.
    pending = decider.decide(SERVED_ZIP, PAYER, PLAN, SERVICE, None)
    assert pending.status is EligibilityStatus.NEEDS_MORE_INFO


def test_partial_inputs_are_never_cached(decider, fake_redis):
    decision = decider.decide(SERVED_ZIP, PAYER, None, SERVICE, True)
    assert decision.status is EligibilityStatus.NEEDS_MORE_INFO
    assert fake_redis.kv == {}
