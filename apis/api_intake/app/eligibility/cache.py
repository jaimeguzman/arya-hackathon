"""Eligibility result caching in Redis (feature 25).

Wraps the deterministic decision engine with the ``eligibility_cache``
key family from ``app.redis_state`` (``eligibility_cache:{zip}:{payer}:{plan}``,
short TTL). A repeated check for the same zip/payer/plan within the TTL is
served from the cache and never re-runs the underlying traversal; expiry (or
any change in the non-key inputs, service type / caregiver availability)
triggers a fresh decision.

Only fully-keyed lookups are cached: if zip, payer, or plan is missing the
decision is computed fresh every time — partial inputs always yield
NEEDS_MORE_INFO and must stay live as the caller fills in fields mid-call.
"""

from __future__ import annotations

from app.eligibility.decision import EligibilityDecision, decide_eligibility
from app.eligibility.reference_data import ReferenceData
from app.redis_state import RedisState
from app.safety.eligibility import EligibilityStatus


def _decision_to_dict(
    decision: EligibilityDecision,
    service_type: str | None,
    caregivers_available: bool | None,
) -> dict:
    return {
        "status": decision.status.value,
        "reasons": list(decision.reasons),
        "documentation_needs": list(decision.documentation_needs),
        # Non-key inputs stored so a lookup with different values is a miss.
        "service_type": service_type,
        "caregivers_available": caregivers_available,
    }


def _decision_from_dict(payload: dict) -> EligibilityDecision:
    return EligibilityDecision(
        status=EligibilityStatus(payload["status"]),
        reasons=tuple(payload["reasons"]),
        documentation_needs=tuple(payload["documentation_needs"]),
    )


class CachedEligibilityDecider:
    """Decision engine front-end that consults the Redis cache first."""

    def __init__(self, state: RedisState, data: ReferenceData) -> None:
        self._state = state
        self._data = data

    def decide(
        self,
        patient_zip: str | None,
        payer: str | None,
        plan: str | None,
        service_type: str | None,
        caregivers_available: bool | None,
    ) -> EligibilityDecision:
        cacheable = bool(patient_zip and payer and plan)
        if cacheable:
            cached = self._state.get_cached_eligibility(patient_zip, payer, plan)
            if (
                cached is not None
                and cached.get("service_type") == service_type
                and cached.get("caregivers_available") == caregivers_available
            ):
                return _decision_from_dict(cached)

        decision = decide_eligibility(
            patient_zip,
            payer,
            plan,
            service_type,
            caregivers_available,
            self._data,
        )
        if cacheable:
            self._state.cache_eligibility(
                patient_zip,
                payer,
                plan,
                _decision_to_dict(decision, service_type, caregivers_available),
            )
        return decision
