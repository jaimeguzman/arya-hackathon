"""Decision engine composing the deterministic eligibility checks.

Feature 24 (workflows/decision_engine) bias: DECLINE fires only on
black-and-white facts (zip unambiguously outside the service area, payer or
plan unambiguously not contracted, service unambiguously not covered). Any
ambiguity — missing fields, a fuzzy-matched plan name, no caregiver match
yet — yields NEEDS_MORE_INFO listing the specific missing items.
"""

from dataclasses import dataclass, field

from app.eligibility.checks import (
    CheckResult,
    check_coverage,
    check_insurance,
    check_service_area,
)
from app.eligibility.reference_data import ReferenceData
from app.safety.eligibility import EligibilityStatus


@dataclass(frozen=True)
class EligibilityDecision:
    status: EligibilityStatus
    reasons: tuple[str, ...]
    documentation_needs: tuple[str, ...] = field(default=())


def decide_eligibility(
    patient_zip: str | None,
    payer: str | None,
    plan: str | None,
    service_type: str | None,
    caregivers_available: bool | None,
    data: ReferenceData,
) -> EligibilityDecision:
    """Compose all checks into a single biased decision.

    `caregivers_available` is the clinical-matching outcome (features 21/22):
    True = at least one qualified caregiver matched, False = none matched yet,
    None = matching not run. Both False and None are ambiguity — staffing can
    change — so neither ever produces a DECLINE.
    """
    checks: list[CheckResult] = [
        check_service_area(patient_zip, data),
        check_insurance(payer, plan, data),
    ]
    insurance = checks[1]
    checks.append(check_coverage(insurance.matched_plan, service_type))

    declines = [c.reason for c in checks if c.status is EligibilityStatus.DECLINE]
    if declines:
        return EligibilityDecision(
            status=EligibilityStatus.DECLINE,
            reasons=tuple(declines),
        )

    missing = [
        c.reason for c in checks if c.status is EligibilityStatus.NEEDS_MORE_INFO
    ]
    if insurance.fuzzy:
        missing.append(
            f"insurance plan name needs confirmation: {insurance.reason}"
        )
    if caregivers_available is None:
        missing.append("caregiver matching has not been run yet")
    elif not caregivers_available:
        missing.append("no qualified caregiver matched yet for the requested service")

    documentation_needs = tuple(
        need for c in checks for need in c.documentation_needs
    )

    if missing:
        return EligibilityDecision(
            status=EligibilityStatus.NEEDS_MORE_INFO,
            reasons=tuple(missing),
            documentation_needs=documentation_needs,
        )

    return EligibilityDecision(
        status=EligibilityStatus.ACCEPT,
        reasons=tuple(c.reason for c in checks),
        documentation_needs=documentation_needs,
    )
