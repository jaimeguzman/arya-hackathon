# ponytail: not a poll loop — called from IntakeService / processor
"""Eligibility re-check when eligibility-relevant intake fields change."""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schemas import EligibilityCheckRequest
from backend.models.tables import IntakeRecord
from backend.services.eligibility_service import EligibilityService

logger = logging.getLogger(__name__)

WATCH_PATHS = (
    ("patient_data", "zip_code"),
    ("insurance_data", "payer_name"),
    ("insurance_data", "plan_name"),
    ("clinical_data", "icd_codes"),
    ("clinical_data", "primary_diagnosis"),
    ("care_request", "service_types_needed"),
)


def _get(bucket: dict[str, Any], key: str) -> Any:
    return (bucket or {}).get(key)


def relevant_changed(before: IntakeRecord | dict, after: IntakeRecord) -> bool:
    def snap(obj: IntakeRecord | dict) -> dict[str, Any]:
        if isinstance(obj, dict):
            return obj
        return {
            "patient_data": obj.patient_data or {},
            "insurance_data": obj.insurance_data or {},
            "clinical_data": obj.clinical_data or {},
            "care_request": obj.care_request or {},
        }

    b, a = snap(before), snap(after)
    for bucket, key in WATCH_PATHS:
        if _get(b.get(bucket, {}), key) != _get(a.get(bucket, {}), key):
            return True
    return False


async def on_intake_updated(
    session: AsyncSession,
    intake: IntakeRecord,
    *,
    previous: Optional[dict[str, Any]] = None,
    eligibility: EligibilityService | None = None,
) -> None:
    if previous is not None and not relevant_changed(previous, intake):
        return

    zip_code = (intake.patient_data or {}).get("zip_code")
    payer = (intake.insurance_data or {}).get("payer_name")
    plan = (intake.insurance_data or {}).get("plan_name")
    icds = (intake.clinical_data or {}).get("icd_codes")
    icd = None
    if isinstance(icds, list) and icds:
        icd = icds[0]
    elif isinstance(icds, str):
        icd = icds
    elif (intake.clinical_data or {}).get("primary_diagnosis"):
        # no fuzzy ICD — leave None → NEEDS_MORE_INFO unless icd present
        pass

    if not zip_code or not payer:
        return

    svc = eligibility or EligibilityService()
    prev_decision = intake.eligibility_decision
    req = EligibilityCheckRequest(
        icd_code=icd,
        insurance_payer=str(payer),
        insurance_plan=str(plan) if plan else None,
        zip_code=str(zip_code),
        service_types_needed=(intake.care_request or {}).get("service_types_needed"),
        intake_record_id=intake.id,
        persist=True,
    )
    result = await svc.check(session, req)
    if prev_decision == "ACCEPT" and result.decision in ("DECLINE", "NEEDS_MORE_INFO"):
        intake.human_review_required = True
        logger.info(
            "eligibility worsened %s -> %s for intake %s — human_review_required",
            prev_decision,
            result.decision,
            intake.id,
        )
