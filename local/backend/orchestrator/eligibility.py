"""Eligibility contract + a stub implementation.

THE CONTRACT (this file's `EligibilityClient` / `EligibilityResult`) is the
seam between the Orchestrator (Task 4) and the Eligibility Agent (Task 3).
Task 3 replaces `StubEligibilityClient` with a real implementation that
traverses Neo4j + PostgreSQL — the orchestrator graph imports only the
`EligibilityClient` protocol, so that swap requires zero graph changes.

Safety (must-have.md #3): eligibility is DETERMINISTIC CODE, never an LLM
judgment. This module has no LLM import and never will. The status enum here
(ACCEPT / DECLINE / NEEDS_MORE_INFO) is the one used across PROJECT.md,
WORKFLOW.md and architecture.md; it maps 1:1 onto must-have.md #3's code-sample
names (provisional_yes / provisional_no / needs_review).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable

from backend.orchestrator.eligibility_core import check_eligibility
from backend.orchestrator.eligibility_data import (
    EligibilityDataProvider,
    FallbackDataProvider,
)


class EligibilityStatus(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"
    NEEDS_MORE_INFO = "NEEDS_MORE_INFO"


@dataclass
class EligibilityResult:
    """What the Eligibility Agent returns for one referral.

    `reasons` is always populated so a decline/needs-info can be spoken back to
    the caller and shown on the dashboard — the "with specific reasons" part of
    PROJECT.md Feature 3.
    """

    status: EligibilityStatus
    reasons: list[str] = field(default_factory=list)
    zip_ok: Optional[bool] = None
    payer_ok: Optional[bool] = None
    caregiver_ok: Optional[bool] = None
    # documents still required before start-of-care (drives the gap-chase follow-up)
    missing_documents: list[str] = field(default_factory=list)
    # caregivers the Eligibility Agent matched (empty for the stub)
    matched_caregivers: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@runtime_checkable
class EligibilityClient(Protocol):
    """The single method the orchestrator calls. Async because the real
    implementation will do async DB/graph I/O (SQLAlchemy + neo4j drivers)."""

    async def check(
        self,
        *,
        zip_code: Optional[str],
        payer: Optional[str],
        plan: Optional[str],
        service_type: Optional[str],
        diagnosis_code: Optional[str] = None,
        provided_documents: Optional[list[str]] = None,
    ) -> EligibilityResult: ...


# --------------------------------------------------------------------------- #
# STUB — replaced by Task 3's real check_eligibility().                        #
# Deterministic, offline, no DB. Exists only so the orchestrator graph and its #
# routing are fully testable before the real Eligibility Agent lands. The tiny #
# fixtures below are consistent with local/data/ but are NOT the source of     #
# truth — the real client reads the databases.                                 #
# --------------------------------------------------------------------------- #

_SERVED_ZIPS = {"10001", "10002", "10003", "11201", "11205", "11101", "10451"}
_ACCEPTED_PAYERS = {"Medicare", "Medicaid_NY", "Humana", "Aetna", "UnitedHealthcare"}
# illustrative required-docs per plan; the real client reads COVERS.requiredDocs from Neo4j
_PLAN_REQUIRED_DOCS = {
    "Medicare Part A": ["physician_orders", "face_to_face_encounter", "homebound_certification"],
    "Medicare Part B": ["physician_orders"],
    "NY Medicaid Managed Care": ["physician_orders", "prior_authorization"],
    "Humana Gold Plus HMO": ["physician_orders", "face_to_face_encounter", "prior_authorization"],
}


class StubEligibilityClient:
    """Deterministic stand-in. See module header — Task 3 replaces this."""

    async def check(
        self,
        *,
        zip_code: Optional[str],
        payer: Optional[str],
        plan: Optional[str],
        service_type: Optional[str],
        diagnosis_code: Optional[str] = None,
        provided_documents: Optional[list[str]] = None,
    ) -> EligibilityResult:
        provided = set(provided_documents or [])
        zip_ok = bool(zip_code) and zip_code in _SERVED_ZIPS
        payer_ok = bool(payer) and payer in _ACCEPTED_PAYERS

        # Hard, unambiguous facts fail fast -> DECLINE (WORKFLOW.md: decline only
        # on black-and-white facts, so the caller can seek help elsewhere sooner).
        if not zip_ok:
            return EligibilityResult(
                status=EligibilityStatus.DECLINE,
                zip_ok=zip_ok,
                payer_ok=payer_ok,
                reasons=[f"Service area not covered: zip {zip_code or 'unknown'}"],
            )
        if not payer_ok:
            return EligibilityResult(
                status=EligibilityStatus.DECLINE,
                zip_ok=zip_ok,
                payer_ok=payer_ok,
                reasons=[f"Insurance not accepted: {payer or 'unknown'}"],
            )

        # Missing the info needed to match care -> NEEDS_MORE_INFO (bias toward
        # this over DECLINE on any ambiguity; never guess).
        if not service_type or not plan:
            missing_fields = [
                name
                for name, val in (("service_type", service_type), ("insurance_plan", plan))
                if not val
            ]
            return EligibilityResult(
                status=EligibilityStatus.NEEDS_MORE_INFO,
                zip_ok=zip_ok,
                payer_ok=payer_ok,
                caregiver_ok=None,
                reasons=[f"Cannot determine eligibility without: {', '.join(missing_fields)}"],
            )

        # Served + accepted + enough info to match -> ACCEPT, but still surface
        # any documents required before start-of-care.
        required = _PLAN_REQUIRED_DOCS.get(plan, ["physician_orders"])
        missing_docs = [d for d in required if d not in provided]
        return EligibilityResult(
            status=EligibilityStatus.ACCEPT,
            zip_ok=True,
            payer_ok=True,
            caregiver_ok=True,
            missing_documents=missing_docs,
            reasons=["Service area, insurance, and a matching caregiver are available"],
        )


# --------------------------------------------------------------------------- #
# REAL client — the team's deterministic core + the DB/JSON data-fetch layer.  #
# This is the seamless connection between Task 3 (eligibility) and Task 4       #
# (orchestrator): the graph injects this and gets real, domain-grounded        #
# decisions with no code change to the graph itself.                           #
# --------------------------------------------------------------------------- #
class RealEligibilityClient:
    """Fetches the facts (served zips, accepted plans, caregiver availability)
    from `data_provider`, feeds them to the team's deterministic
    `check_eligibility()` core, and maps the verdict onto the orchestrator's
    `EligibilityResult`. Also computes `missing_documents` (the core returns
    only status + reasons; gap-chasing is the orchestrator's concern)."""

    def __init__(self, data_provider: Optional[EligibilityDataProvider] = None) -> None:
        # default: DB-backed with automatic JSON fallback when the DB is down
        self._data: EligibilityDataProvider = data_provider or FallbackDataProvider()

    async def check(
        self,
        *,
        zip_code: Optional[str],
        payer: Optional[str],
        plan: Optional[str],
        service_type: Optional[str],
        diagnosis_code: Optional[str] = None,
        provided_documents: Optional[list[str]] = None,
    ) -> EligibilityResult:
        provided = set(provided_documents or [])
        served = await self._data.served_zips()
        accepted = await self._data.accepted_plans()
        available = await self._data.caregivers_available(
            service_type=service_type, zip_code=zip_code
        )

        core = check_eligibility(
            patient_zip=zip_code,
            insurance_plan=plan,
            service_area_zips=served,
            accepted_plans=accepted,
            caregivers_available=available,
        )

        status = EligibilityStatus(core.status.value)
        missing_docs: list[str] = []
        if status is EligibilityStatus.ACCEPT:
            required = await self._data.required_documents(
                plan=plan, service_type=service_type
            )
            missing_docs = [d for d in required if d not in provided]

        return EligibilityResult(
            status=status,
            reasons=list(core.reasons),
            zip_ok=bool(zip_code) and zip_code in served,
            payer_ok=bool(plan) and plan in accepted,
            caregiver_ok=available,
            missing_documents=missing_docs,
        )
