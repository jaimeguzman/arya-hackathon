"""Deterministic eligibility decision core (must-have.md #3).

VENDORED from the team's safety layer, originally authored on the `develop`
branch at `apis/api_intake/app/safety/eligibility.py` (Task 3). Copied here
verbatim so the orchestrator in `local/backend/` can call the team's actual
deterministic decision function rather than a stub. When the folder trees are
reconciled (see NEXT-STEPS / WORKFLOW), this should collapse back to a single
copy — tracked as a reconciliation item, do not let the two diverge.

This is a PURE function: it receives the pre-fetched facts (served zips,
accepted plans, caregiver availability) and decides. The data-fetch layer that
produces those facts lives in `eligibility_data.py`; the adapter that wires
them together lives in `eligibility.py` (RealEligibilityClient).

No LLM here, ever (must-have.md #3).
"""

from enum import Enum

from pydantic import BaseModel


class CoreEligibilityStatus(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"
    NEEDS_MORE_INFO = "NEEDS_MORE_INFO"


class CoreEligibilityResult(BaseModel):
    status: CoreEligibilityStatus
    reasons: list[str]


def check_eligibility(
    patient_zip: str | None,
    insurance_plan: str | None,
    service_area_zips: set[str],
    accepted_plans: set[str],
    caregivers_available: bool | None,
) -> CoreEligibilityResult:
    """Deterministic eligibility: zip match, insurance acceptance, availability.

    Plain code over known tables/graph data — no LLM involvement. Biases toward
    NEEDS_MORE_INFO over DECLINE: an unknown fact is an `unknown`, not a decline
    reason. DECLINE fires only on a hard, known-false fact.
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
        return CoreEligibilityResult(status=CoreEligibilityStatus.DECLINE, reasons=reasons)
    if unknowns:
        return CoreEligibilityResult(status=CoreEligibilityStatus.NEEDS_MORE_INFO, reasons=unknowns)
    return CoreEligibilityResult(
        status=CoreEligibilityStatus.ACCEPT,
        reasons=["zip in service area", "insurance accepted", "caregivers available"],
    )
