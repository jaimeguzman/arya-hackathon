"""Service-area and insurance checks for the Eligibility Agent.

Both checks are deterministic code over reference data (feature 19/20,
core_features/eligibility_engine). Missing input never hard-fails — it maps
to NEEDS_MORE_INFO per the decision-engine bias (DECLINE only on
black-and-white facts).
"""

from dataclasses import dataclass

from app.eligibility.reference_data import PlanContract, ReferenceData
from app.safety.eligibility import EligibilityStatus

# pg_trgm-compatible similarity threshold (Postgres default for the %
# operator). Used by the in-process fallback until the pgvector/pg_trgm
# database path is available (infra feature 1).
FUZZY_MATCH_THRESHOLD = 0.3
TRIGRAM_LENGTH = 3


@dataclass(frozen=True)
class CheckResult:
    status: EligibilityStatus
    reason: str
    matched_plan: PlanContract | None = None
    fuzzy: bool = False
    documentation_needs: tuple[str, ...] = ()


def check_service_area(patient_zip: str | None, data: ReferenceData) -> CheckResult:
    """Hard pass/fail on the agency zip list; missing zip asks for more info."""
    if not patient_zip or not patient_zip.strip():
        return CheckResult(
            status=EligibilityStatus.NEEDS_MORE_INFO,
            reason="patient zip code not provided",
        )
    zip_code = patient_zip.strip()
    if zip_code in data.service_area_zips:
        return CheckResult(
            status=EligibilityStatus.ACCEPT,
            reason=f"zip {zip_code} is in the service area",
        )
    return CheckResult(
        status=EligibilityStatus.DECLINE,
        reason=f"zip not served: {zip_code} is outside the agency service area",
    )


def _trigrams(text: str) -> set[str]:
    """pg_trgm-style trigram set: lowercase, padded like Postgres does."""
    normalized = " ".join(text.lower().split())
    padded = f"  {normalized} "
    return {
        padded[i : i + TRIGRAM_LENGTH]
        for i in range(len(padded) - TRIGRAM_LENGTH + 1)
    }


def trigram_similarity(a: str, b: str) -> float:
    """Jaccard similarity over trigram sets — pg_trgm's similarity()."""
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def fuzzy_match_plan(plan_name: str, data: ReferenceData) -> PlanContract | None:
    """Best contracted plan above the pg_trgm threshold, else None."""
    best: PlanContract | None = None
    best_score = FUZZY_MATCH_THRESHOLD
    for contract in data.plans:
        score = trigram_similarity(plan_name, contract.plan)
        if score > best_score:
            best, best_score = contract, score
    return best


def check_insurance(
    payer: str | None,
    plan: str | None,
    data: ReferenceData,
) -> CheckResult:
    """Payer/plan contract check with fuzzy plan matching before failing."""
    if not payer or not payer.strip():
        return CheckResult(
            status=EligibilityStatus.NEEDS_MORE_INFO,
            reason="insurance payer not provided",
        )
    payer_name = payer.strip()

    accepted_by_name = {p.lower(): p for p in data.accepted_payers}
    canonical_payer = accepted_by_name.get(payer_name.lower())
    if canonical_payer is None:
        return CheckResult(
            status=EligibilityStatus.DECLINE,
            reason=f"payer not accepted: '{payer_name}' is not a contracted payer",
        )

    if not plan or not plan.strip():
        return CheckResult(
            status=EligibilityStatus.NEEDS_MORE_INFO,
            reason=f"insurance plan not provided for payer '{canonical_payer}'",
        )
    plan_name = plan.strip()

    payer_plans = [p for p in data.plans if p.payer == canonical_payer]
    for contract in payer_plans:
        if contract.plan.lower() == plan_name.lower():
            return CheckResult(
                status=EligibilityStatus.ACCEPT,
                reason=f"plan '{contract.plan}' is contracted with {canonical_payer}",
                matched_plan=contract,
            )

    fuzzy = fuzzy_match_plan(plan_name, data)
    if fuzzy is not None and fuzzy.payer == canonical_payer:
        return CheckResult(
            status=EligibilityStatus.ACCEPT,
            reason=(
                f"plan '{plan_name}' fuzzy-matched to contracted plan "
                f"'{fuzzy.plan}' ({canonical_payer})"
            ),
            matched_plan=fuzzy,
            fuzzy=True,
        )

    return CheckResult(
        status=EligibilityStatus.DECLINE,
        reason=(
            f"plan not accepted: '{plan_name}' does not match any contracted "
            f"{canonical_payer} plan"
        ),
    )


def check_coverage(
    matched_plan: PlanContract | None,
    service_type: str | None,
) -> CheckResult:
    """Cross-check InsurancePlan-COVERS->ServiceType and prior-auth needs.

    Feature 23 (core_features/eligibility_engine): an uncovered service is a
    black-and-white DECLINE; REQUIRES_AUTH surfaces 'prior authorization
    required' as a documentation need on a covered service.
    """
    if matched_plan is None:
        return CheckResult(
            status=EligibilityStatus.NEEDS_MORE_INFO,
            reason="insurance plan not resolved — cannot verify service coverage",
        )
    if not service_type or not service_type.strip():
        return CheckResult(
            status=EligibilityStatus.NEEDS_MORE_INFO,
            reason="requested service type not provided",
        )
    service = service_type.strip()
    if service not in matched_plan.covers:
        return CheckResult(
            status=EligibilityStatus.DECLINE,
            reason=(
                f"service not covered: plan '{matched_plan.plan}' "
                f"({matched_plan.payer}) does not cover '{service}'"
            ),
        )
    documentation_needs: tuple[str, ...] = ()
    if matched_plan.requires_prior_auth:
        documentation_needs = (
            f"prior authorization required by {matched_plan.payer} "
            f"plan '{matched_plan.plan}'",
        )
    return CheckResult(
        status=EligibilityStatus.ACCEPT,
        reason=(
            f"service '{service}' is covered by plan "
            f"'{matched_plan.plan}' ({matched_plan.payer})"
        ),
        matched_plan=matched_plan,
        documentation_needs=documentation_needs,
    )
