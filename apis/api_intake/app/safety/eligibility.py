"""Guarantee 3: check_eligibility() is deterministic code — never LLM-decided.

Response generation requires a pre-computed EligibilityResult as a mandatory
input, making it structurally impossible to answer accept/decline from the
LLM's opinion.
"""

from enum import Enum

from pydantic import BaseModel


class EligibilityStatus(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"
    NEEDS_MORE_INFO = "NEEDS_MORE_INFO"


class EligibilityResult(BaseModel):
    status: EligibilityStatus
    reasons: list[str]


def check_eligibility(
    patient_zip: str | None,
    insurance_plan: str | None,
    service_area_zips: set[str],
    accepted_plans: set[str],
    caregivers_available: bool | None,
) -> EligibilityResult:
    """Deterministic eligibility: zip match, insurance acceptance, availability.

    Plain code over known tables/graph data — no LLM involvement.
    """
    reasons: list[str] = []
    unknowns: list[str] = []

    if patient_zip is None:
        unknowns.append("patient zip code not provided")
    elif patient_zip not in service_area_zips:
        reasons.append(f"zip {patient_zip} is outside the service area")

    if insurance_plan is None:
        unknowns.append("insurance plan not provided")
    elif insurance_plan not in accepted_plans:
        reasons.append(f"insurance plan '{insurance_plan}' is not accepted")

    if caregivers_available is None:
        unknowns.append("caregiver availability unknown")
    elif not caregivers_available:
        reasons.append("no caregivers available for the required service")

    if reasons:
        return EligibilityResult(status=EligibilityStatus.DECLINE, reasons=reasons)
    if unknowns:
        return EligibilityResult(status=EligibilityStatus.NEEDS_MORE_INFO, reasons=unknowns)
    return EligibilityResult(
        status=EligibilityStatus.ACCEPT,
        reasons=["zip in service area", "insurance accepted", "caregivers available"],
    )


def generate_eligibility_response(result: EligibilityResult) -> str:
    """Turn a pre-computed EligibilityResult into caller-facing wording.

    The mandatory `result` parameter is the structural enforcement: no code
    path can produce an accept/decline answer without deterministic input.
    """
    detail = "; ".join(result.reasons)
    if result.status is EligibilityStatus.ACCEPT:
        return f"Good news — we can take this referral. ({detail})"
    if result.status is EligibilityStatus.DECLINE:
        return f"Unfortunately we are not able to take this referral: {detail}."
    return f"We need a bit more information before we can decide: {detail}."
