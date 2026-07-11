"""Shared state object that flows through the orchestrator graph.

The orchestrator is input-agnostic: whether a referral arrived by voice call or
by fax, the upstream component (Voice Agent / Document Pipeline) populates the
same structured fields here, and the same graph runs over them.

ponytail: TypedDict over a Pydantic model — LangGraph channels want a plain
mapping; ceiling: no runtime field validation; upgrade: swap to a Pydantic
state if we start ingesting untrusted external payloads directly.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Optional, TypedDict


class ReferralState(TypedDict, total=False):
    """Everything the orchestrator reads and writes for one referral.

    `total=False` so callers only provide what they have — the Document
    Pipeline may fill many fields, a minimal family phone call very few.
    """

    # --- identity / provenance ---
    referral_id: str
    # source: fax | inbound_call_provider | inbound_call_family |
    #         inbound_call_patient | physician_referral | snf_referral
    source: str

    # --- structured inputs the Eligibility Agent needs ---
    zip_code: Optional[str]
    payer: Optional[str]
    plan: Optional[str]
    service_type: Optional[str]
    diagnosis_code: Optional[str]
    # documents already supplied with the referral (used to compute what's still missing)
    provided_documents: list[str]

    # --- who to contact for follow-up ---
    # {"name": ..., "phone": ..., "role": "provider" | "family" | "patient"}
    contact: dict[str, Any]

    # gaps flagged upstream (e.g. by the Document Pipeline's completeness check)
    gaps: list[str]

    # --- filled by the graph ---
    # eligibility: serialized EligibilityResult (see eligibility.py)
    eligibility: Optional[dict[str, Any]]
    # decision: ACCEPT | DECLINE | NEEDS_MORE_INFO (mirrors eligibility.status)
    decision: Optional[str]
    # followup: serialized FollowUpAction chosen for this referral (see followup/agent.py)
    followup: Optional[dict[str, Any]]

    # terminal intake status (matches postgres_init.sql intake_status enum):
    # new | processing | pending_documents | eligible | accepted | declined | escalated
    status: str
    human_review_required: bool

    # append-only breadcrumb of node names, for tests and the demo trace
    trace: Annotated[list[str], operator.add]


def initial_state(**fields: Any) -> ReferralState:
    """Build a clean input state, guaranteeing the append-only channels exist."""
    state: ReferralState = {
        "status": "new",
        "human_review_required": False,
        "provided_documents": [],
        "gaps": [],
        "trace": [],
    }
    state.update(fields)  # type: ignore[typeddict-item]
    return state
