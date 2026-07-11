from fastapi import APIRouter

from app.agents.eligibility_agent import EligibilityDecision, EligibilityRequest, decide

router = APIRouter()


@router.post("/eligibility-check")
def eligibility_check(request: EligibilityRequest) -> EligibilityDecision:
    """Deterministic eligibility decision over the agency's datasets.

    Returns ACCEPT / DECLINE / NEEDS_MORE_INFO with specific reasons,
    matched plan, required documentation, and matched caregiver IDs.
    """
    return decide(request)
