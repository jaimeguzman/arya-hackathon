"""Feature 6 — Redis key conventions and connection module.

Round-trips a value through each key type using a fake Redis client and
asserts eligibility cache entries carry a short TTL.
"""

import pytest

from app.redis_state import (
    RETRY_QUEUE_KEY,
    RedisState,
    call_key,
    eligibility_cache_key,
    get_redis_client,
    pipeline_key,
)

TTL_SECONDS = 300


class FakeRedis:
    """Minimal in-memory stand-in recording TTLs passed to set()."""

    def __init__(self):
        self.kv = {}
        self.hashes = {}
        self.zsets = {}
        self.ttls = {}

    def set(self, key, value, ex=None):
        self.kv[key] = value
        if ex is not None:
            self.ttls[key] = ex

    def get(self, key):
        return self.kv.get(key)

    def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def zadd(self, key, mapping):
        self.zsets.setdefault(key, {}).update(mapping)

    def zrangebyscore(self, key, low, high):
        return [
            member
            for member, score in sorted(
                self.zsets.get(key, {}).items(), key=lambda kv: kv[1]
            )
            if low <= score <= high
        ]


@pytest.fixture
def state():
    return RedisState(FakeRedis(), eligibility_ttl_seconds=TTL_SECONDS)


def test_key_builders_match_spec_conventions():
    assert pipeline_key("doc-1") == "pipeline:doc-1"
    assert call_key("CA123") == "call:CA123"
    assert (
        eligibility_cache_key("60601", "aetna", "ppo")
        == "eligibility_cache:60601:aetna:ppo"
    )
    assert RETRY_QUEUE_KEY == "retry_queue"


def test_pipeline_state_round_trip(state):
    payload = {"layer": 3, "validation_status": "pending"}
    state.set_pipeline_state("doc-1", payload)
    assert state.get_pipeline_state("doc-1") == payload
    assert state.get_pipeline_state("missing") is None


def test_call_state_round_trip(state):
    state.set_call_field("CA123", "zip", "60601")
    assert state.get_call_field("CA123", "zip") == "60601"
    assert state.get_call_field("CA123", "plan") is None


def test_eligibility_cache_round_trip_with_short_ttl(state):
    result = {"status": "ACCEPT", "reasons": []}
    state.cache_eligibility("60601", "aetna", "ppo", result)
    assert state.get_cached_eligibility("60601", "aetna", "ppo") == result
    key = eligibility_cache_key("60601", "aetna", "ppo")
    assert state._client.ttls[key] == TTL_SECONDS


def test_retry_queue_round_trip(state):
    state.schedule_retry({"call_sid": "CA123", "action": "callback"}, due_at_epoch=100.0)
    state.schedule_retry({"call_sid": "CA999", "action": "callback"}, due_at_epoch=999.0)
    due = state.due_retries(now_epoch=200.0)
    assert due == [{"call_sid": "CA123", "action": "callback"}]


def test_get_redis_client_requires_configured_url(monkeypatch):
    from app import config
    import app.redis_state as rs

    monkeypatch.setattr(
        rs, "get_settings", lambda: config.Settings(redis_url="", _env_file=None)
    )
    with pytest.raises(RuntimeError):
        get_redis_client()
