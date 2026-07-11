"""Integration tests: the team's deterministic core (eligibility_core) + the
JSON data-fetch layer, driven through RealEligibilityClient and the full graph.

Proves Task 3 (eligibility) and Task 4 (orchestrator) are connected with no
gap, using the real local/data seed files (offline, JSON provider — no Docker).
"""

from __future__ import annotations

import pytest

from backend.orchestrator.eligibility import EligibilityStatus, RealEligibilityClient
from backend.orchestrator.eligibility_core import CoreEligibilityStatus, check_eligibility
from backend.orchestrator.eligibility_data import JsonEligibilityDataProvider
from backend.orchestrator.graph import run_referral
from backend.orchestrator.state import initial_state


def _real_client() -> RealEligibilityClient:
    # force the offline JSON provider so tests never depend on Docker
    return RealEligibilityClient(data_provider=JsonEligibilityDataProvider())


# --- the vendored deterministic core, directly (mirrors develop's own tests) ---
def test_core_accept_decline_needs_info():
    zips = {"11201"}
    plans = {"Medicare Part A"}
    assert check_eligibility("11201", "Medicare Part A", zips, plans, True).status is CoreEligibilityStatus.ACCEPT
    assert check_eligibility("90210", "Medicare Part A", zips, plans, False).status is CoreEligibilityStatus.DECLINE
    assert check_eligibility(None, "Medicare Part A", zips, plans, True).status is CoreEligibilityStatus.NEEDS_MORE_INFO


# --- the JSON provider reads the real seed data correctly ---
@pytest.mark.asyncio
async def test_json_provider_reads_seed_data():
    p = JsonEligibilityDataProvider()
    zips = await p.served_zips()
    plans = await p.accepted_plans()
    assert "11201" in zips and "90210" not in zips
    assert "Medicare Part A" in plans
    # an active skilled-nursing (RN/LPN) caregiver exists in 11201
    assert await p.caregivers_available(service_type="skilled_nursing", zip_code="11201") is True
    # no caregiver serves 90210
    assert await p.caregivers_available(service_type="skilled_nursing", zip_code="90210") is False
    # unknown service -> unknown (None) so the core asks for more info
    assert await p.caregivers_available(service_type=None, zip_code="11201") is None


# --- RealEligibilityClient: the full adapter path, per outcome ---
@pytest.mark.asyncio
async def test_real_client_accept_computes_missing_docs():
    result = await _real_client().check(
        zip_code="11201",
        payer="Medicare",
        plan="Medicare Part A",
        service_type="skilled_nursing",
        provided_documents=["physician_orders"],
    )
    assert result.status is EligibilityStatus.ACCEPT
    assert result.zip_ok and result.payer_ok and result.caregiver_ok
    assert "face_to_face_encounter" in result.missing_documents
    assert "homebound_certification" in result.missing_documents
    assert "physician_orders" not in result.missing_documents


@pytest.mark.asyncio
async def test_real_client_accept_all_docs_present_no_gaps():
    result = await _real_client().check(
        zip_code="11201",
        payer="Medicare",
        plan="Medicare Part A",
        service_type="skilled_nursing",
        provided_documents=["physician_orders", "face_to_face_encounter", "homebound_certification"],
    )
    assert result.status is EligibilityStatus.ACCEPT
    assert result.missing_documents == []


@pytest.mark.asyncio
async def test_real_client_decline_out_of_area():
    result = await _real_client().check(
        zip_code="90210", payer="Medicare", plan="Medicare Part A", service_type="skilled_nursing"
    )
    assert result.status is EligibilityStatus.DECLINE
    assert result.zip_ok is False


@pytest.mark.asyncio
async def test_real_client_needs_info_when_plan_unknown():
    result = await _real_client().check(
        zip_code="11201", payer="Medicare", plan=None, service_type=None
    )
    assert result.status is EligibilityStatus.NEEDS_MORE_INFO


# --- end to end through the graph with the real client injected ---
@pytest.mark.asyncio
async def test_graph_with_real_client_end_to_end():
    state = initial_state(
        referral_id="R-real",
        source="fax",
        zip_code="11201",
        payer="Medicare",
        plan="Medicare Part A",
        service_type="skilled_nursing",
        provided_documents=["physician_orders"],
        contact={"phone": "+15550001234", "role": "provider"},
    )
    result = await run_referral(state, eligibility_client=_real_client())
    assert result["decision"] == "ACCEPT"
    assert result["status"] == "pending_documents"  # missing docs -> pending
    assert result["followup"]["intent"] == "confirmation"
