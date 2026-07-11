"""Shared Redis key conventions and connection module.

Single source of truth for every Redis key the system uses
(app_spec database_schema/redis):

- ``pipeline:{doc_id}``                       — document pipeline layer state
- ``call:{call_sid}``                         — live call state
- ``eligibility_cache:{zip}:{payer}:{plan}``  — cached eligibility results (short TTL)
- ``retry_queue``                             — scheduled callbacks and follow-ups

Like ``CallModeStore``, ``RedisState`` takes any Redis-compatible client
(``redis.Redis`` in production; a fake in tests) so every contract is
testable without a running server. ``get_redis_client()`` builds the real
client from ``REDIS_URL``.
"""

from __future__ import annotations

import json

from app.config import get_settings


def pipeline_key(doc_id: str) -> str:
    return f"pipeline:{doc_id}"


def call_key(call_sid: str) -> str:
    return f"call:{call_sid}"


def eligibility_cache_key(zip_code: str, payer: str, plan: str) -> str:
    return f"eligibility_cache:{zip_code}:{payer}:{plan}"


RETRY_QUEUE_KEY = "retry_queue"


def get_redis_client():
    """Real Redis client from REDIS_URL. Raises if the URL is not configured."""
    settings = get_settings()
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is not configured (see .env.example)")
    import redis

    return redis.Redis.from_url(settings.redis_url)


def _decode(raw) -> str:
    return raw.decode() if isinstance(raw, bytes) else raw


class RedisState:
    """Typed accessors for each key family, over an injected client."""

    def __init__(self, client, *, eligibility_ttl_seconds: int) -> None:
        self._client = client
        self._eligibility_ttl_seconds = eligibility_ttl_seconds

    # -- pipeline:{doc_id} ---------------------------------------------------
    def set_pipeline_state(self, doc_id: str, state: dict) -> None:
        self._client.set(pipeline_key(doc_id), json.dumps(state))

    def get_pipeline_state(self, doc_id: str) -> dict | None:
        raw = self._client.get(pipeline_key(doc_id))
        return None if raw is None else json.loads(_decode(raw))

    # -- call:{call_sid} -----------------------------------------------------
    def set_call_field(self, call_sid: str, field: str, value: str) -> None:
        self._client.hset(call_key(call_sid), field, value)

    def get_call_field(self, call_sid: str, field: str) -> str | None:
        raw = self._client.hget(call_key(call_sid), field)
        return None if raw is None else _decode(raw)

    # -- eligibility_cache:{zip}:{payer}:{plan} (short TTL) --------------------
    def cache_eligibility(
        self, zip_code: str, payer: str, plan: str, result: dict
    ) -> None:
        self._client.set(
            eligibility_cache_key(zip_code, payer, plan),
            json.dumps(result),
            ex=self._eligibility_ttl_seconds,
        )

    def get_cached_eligibility(
        self, zip_code: str, payer: str, plan: str
    ) -> dict | None:
        raw = self._client.get(eligibility_cache_key(zip_code, payer, plan))
        return None if raw is None else json.loads(_decode(raw))

    # -- retry_queue (sorted set scored by due timestamp) ----------------------
    def schedule_retry(self, payload: dict, due_at_epoch: float) -> None:
        self._client.zadd(RETRY_QUEUE_KEY, {json.dumps(payload): due_at_epoch})

    def due_retries(self, now_epoch: float) -> list[dict]:
        raw_items = self._client.zrangebyscore(RETRY_QUEUE_KEY, 0, now_epoch)
        return [json.loads(_decode(item)) for item in raw_items]
