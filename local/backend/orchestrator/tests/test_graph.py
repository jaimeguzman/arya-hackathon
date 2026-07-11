"""Orchestrator graph tests — verify routing + terminal status for every
eligibility outcome, offline, no DB or Twilio. Covers checklist B1-B7, D1-D2."""

from __future__ import annotations

import pytest

from backend.followup.notifications import StubNotificationClient
from backend.followup.agent import FollowUpAgent
from backend.orchestrator.eligibility import (
    EligibilityClient,
    EligibilityResult,
    EligibilityStatus,
    StubEligibilityClient,
)
from backend.orchestrator.graph import build_graph, run_referral
from backend.orchestrator.state import initial_state


def _agent_with_recorder() -> tuple[FollowUpAgent, StubNotificationClient]:
    notifier = StubNotificationClient()
    return FollowUpAgent(notifier=notifier), notifier


# B1 — graph compiles with no live dependencies
def test_graph_compiles_offline():
    assert build_graph() is not None


# B2 / B7 — full node order runs; input-agnostic across sources
@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["inbound_call_provider", "fax"])
async def test_full_node_trace(source):
    state = initial_state(
        referral_id="R-1",
        source=source,
        zip_code="11201",
        payer="Medicare",
        plan="Medicare Part A",
        service_type="skilled_nursing",
        diagnosis_code="Z96.641",
        provided_documents=["physician_orders", "face_to_face_encounter", "homebound_certification"],
        contact={"phone": "+15550000001", "role": "provider"},
    )
    result = await run_referral(state)
    assert result["trace"] == [
        "intake_received",
        "check_eligibility",
        "decide",
        "followup_accept",
    ]


# B3 — ACCEPT (all docs present) -> accepted + SMS confirmation
@pytest.mark.asyncio
async def test_accept_clean_routes_to_accepted():
    agent, notifier = _agent_with_recorder()
    state = initial_state(
        referral_id="R-accept",
        source="inbound_call_provider",
        zip_code="11201",
        payer="Medicare",
        plan="Medicare Part A",
        service_type="skilled_nursing",
        provided_documents=["physician_orders", "face_to_face_encounter", "homebound_certification"],
        contact={"phone": "+15550000001", "role": "provider"},
    )
    result = await run_referral(state, followup_agent=agent)
    assert result["decision"] == "ACCEPT"
    assert result["status"] == "accepted"
    assert result["followup"]["intent"] == "confirmation"
    assert notifier.sent and notifier.sent[0].channel == "sms"


# B3 variant — ACCEPT with missing docs -> pending_documents
@pytest.mark.asyncio
async def test_accept_missing_docs_routes_to_pending_documents():
    state = initial_state(
        referral_id="R-pending",
        source="fax",
        zip_code="11201",
        payer="Medicare",
        plan="Medicare Part A",
        service_type="skilled_nursing",
        provided_documents=["physician_orders"],  # F2F + homebound missing
        contact={"phone": "+15550000002", "role": "provider"},
    )
    result = await run_referral(state)
    assert result["decision"] == "ACCEPT"
    assert result["status"] == "pending_documents"
    assert "face_to_face_encounter" in result["eligibility"]["missing_documents"]


# B4 — DECLINE (out of area) -> declined, terminal, no gap-chase
@pytest.mark.asyncio
async def test_decline_out_of_area():
    state = initial_state(
        referral_id="R-decline",
        source="inbound_call_provider",
        zip_code="90210",  # not served
        payer="Medicare",
        plan="Medicare Part A",
        service_type="skilled_nursing",
        contact={"phone": "+15550000003", "role": "provider"},
    )
    result = await run_referral(state)
    assert result["decision"] == "DECLINE"
    assert result["status"] == "declined"
    assert result["followup"]["terminal"] is True


# B5 — NEEDS_MORE_INFO (family call, minimal data) -> processing + human review
@pytest.mark.asyncio
async def test_needs_more_info_family_call():
    state = initial_state(
        referral_id="R-family",
        source="inbound_call_family",
        zip_code="11201",
        payer="Medicare",
        plan=None,  # unknown -> ambiguous
        service_type=None,
        contact={"phone": "+15550000004", "role": "family"},
    )
    result = await run_referral(state)
    assert result["decision"] == "NEEDS_MORE_INFO"
    assert result["status"] == "processing"
    assert result["human_review_required"] is True
    assert result["followup"]["intent"] == "gap_chase"


# B6 / D2 — a custom eligibility client is honored; decision follows it exactly.
# Proves the graph reads only the injected client's result (no hidden LLM/decision path).
@pytest.mark.asyncio
async def test_graph_uses_injected_eligibility_client():
    class AlwaysDecline:
        async def check(self, **kwargs) -> EligibilityResult:
            return EligibilityResult(
                status=EligibilityStatus.DECLINE, reasons=["forced"]
            )

    client: EligibilityClient = AlwaysDecline()  # type: ignore[assignment]
    state = initial_state(
        referral_id="R-inject",
        source="fax",
        zip_code="11201",
        payer="Medicare",
        plan="Medicare Part A",
        service_type="skilled_nursing",
        contact={"phone": "+15550000005"},
    )
    result = await run_referral(state, eligibility_client=client)
    assert result["decision"] == "DECLINE"


# D1 — the stub honors the documented contract shape
@pytest.mark.asyncio
async def test_eligibility_contract_shape():
    result = await StubEligibilityClient().check(
        zip_code="11201",
        payer="Medicare",
        plan="Medicare Part A",
        service_type="skilled_nursing",
        provided_documents=[],
    )
    data = result.to_dict()
    for key in ("status", "reasons", "zip_ok", "payer_ok", "caregiver_ok", "missing_documents"):
        assert key in data
    assert data["status"] in {"ACCEPT", "DECLINE", "NEEDS_MORE_INFO"}
