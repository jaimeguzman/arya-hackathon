"""The Intake Agent orchestrator — a LangGraph state machine.

The "brain" from WORKFLOW.md: it never talks to a caller or reads a document
directly. It takes an already-structured referral (from a voice extraction or
the Document Pipeline), runs the deterministic eligibility check, and routes to
the right follow-up action based on ACCEPT / DECLINE / NEEDS_MORE_INFO.

    intake_received -> check_eligibility -> decide -.-> followup_accept    -> END
                                                    |-> followup_decline   -> END
                                                    '-> followup_needs_info -> END

Dependencies (eligibility client, follow-up agent) are injected in build_graph()
so the whole machine runs against stubs offline, and Task 3's real Eligibility
Agent / Task 1's real Twilio client drop in with no graph changes.
"""

from __future__ import annotations

from typing import Any, Optional

from langgraph.graph import END, StateGraph

from backend.followup.agent import FollowUpAgent
from backend.orchestrator.eligibility import EligibilityClient, StubEligibilityClient
from backend.orchestrator.state import ReferralState


def build_graph(
    eligibility_client: Optional[EligibilityClient] = None,
    followup_agent: Optional[FollowUpAgent] = None,
):
    """Compile and return the orchestrator graph. All dependencies default to
    offline stubs, so `build_graph()` with no args is runnable anywhere."""

    elig: EligibilityClient = eligibility_client or StubEligibilityClient()
    followup = followup_agent or FollowUpAgent()

    async def intake_received(state: ReferralState) -> dict[str, Any]:
        return {"status": "processing", "trace": ["intake_received"]}

    async def check_eligibility(state: ReferralState) -> dict[str, Any]:
        result = await elig.check(
            zip_code=state.get("zip_code"),
            payer=state.get("payer"),
            plan=state.get("plan"),
            service_type=state.get("service_type"),
            diagnosis_code=state.get("diagnosis_code"),
            provided_documents=state.get("provided_documents"),
        )
        return {"eligibility": result.to_dict(), "trace": ["check_eligibility"]}

    async def decide(state: ReferralState) -> dict[str, Any]:
        # The decision comes ONLY from the eligibility result — never the LLM
        # (must-have.md #3). This node just records it for routing + audit.
        decision = (state.get("eligibility") or {}).get("status")
        return {"decision": decision, "trace": ["decide"]}

    async def followup_accept(state: ReferralState) -> dict[str, Any]:
        action = await followup.plan_initial("ACCEPT", dict(state))
        missing = (state.get("eligibility") or {}).get("missing_documents") or []
        status = "pending_documents" if missing else "accepted"
        return {
            "status": status,
            "followup": action.to_dict(),
            "trace": ["followup_accept"],
        }

    async def followup_decline(state: ReferralState) -> dict[str, Any]:
        action = await followup.plan_initial("DECLINE", dict(state))
        return {
            "status": "declined",
            "followup": action.to_dict(),
            "trace": ["followup_decline"],
        }

    async def followup_needs_info(state: ReferralState) -> dict[str, Any]:
        action = await followup.plan_initial("NEEDS_MORE_INFO", dict(state))
        return {
            "status": "processing",
            "human_review_required": True,
            "followup": action.to_dict(),
            "trace": ["followup_needs_info"],
        }

    def route_decision(state: ReferralState) -> str:
        decision = state.get("decision")
        if decision == "ACCEPT":
            return "followup_accept"
        if decision == "DECLINE":
            return "followup_decline"
        return "followup_needs_info"

    graph = StateGraph(ReferralState)
    graph.add_node("intake_received", intake_received)
    graph.add_node("check_eligibility", check_eligibility)
    graph.add_node("decide", decide)
    graph.add_node("followup_accept", followup_accept)
    graph.add_node("followup_decline", followup_decline)
    graph.add_node("followup_needs_info", followup_needs_info)

    graph.set_entry_point("intake_received")
    graph.add_edge("intake_received", "check_eligibility")
    graph.add_edge("check_eligibility", "decide")
    graph.add_conditional_edges(
        "decide",
        route_decision,
        {
            "followup_accept": "followup_accept",
            "followup_decline": "followup_decline",
            "followup_needs_info": "followup_needs_info",
        },
    )
    graph.add_edge("followup_accept", END)
    graph.add_edge("followup_decline", END)
    graph.add_edge("followup_needs_info", END)

    return graph.compile()


async def run_referral(
    inputs: ReferralState,
    eligibility_client: Optional[EligibilityClient] = None,
    followup_agent: Optional[FollowUpAgent] = None,
) -> ReferralState:
    """Convenience: build the graph and run one referral to a terminal state."""
    app = build_graph(eligibility_client, followup_agent)
    return await app.ainvoke(inputs)  # type: ignore[return-value]
