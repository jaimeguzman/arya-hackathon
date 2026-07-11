"""Tests for the data-backed Eligibility Agent and its endpoint."""

from fastapi.testclient import TestClient

from app.agents.eligibility_agent import (
    EligibilityRequest,
    decide,
    find_available_caregivers,
    resolve_plan,
)
from app.main import app

client = TestClient(app)

# Known-good values from data/reference + data/synthetic datasets.
SERVED_ZIP = "11201"
UNSERVED_ZIP = "99999"
KNOWN_PLAN = "Medicare Part A"
SERVICE = "skilled_nursing"


class TestResolvePlan:
    def test_exact_name(self):
        assert resolve_plan(KNOWN_PLAN)["plan"] == KNOWN_PLAN

    def test_fuzzy_spoken_form(self):
        assert resolve_plan("Humana Gold")["plan"] == "Humana Gold Plus HMO"

    def test_unknown_plan(self):
        assert resolve_plan("Totally Fake Insurance") is None


class TestFindAvailableCaregivers:
    def test_served_zip_has_nurses(self):
        caregivers = find_available_caregivers(SERVED_ZIP, SERVICE)
        assert caregivers
        assert all(c["status"] == "active" for c in caregivers)
        assert all(SERVED_ZIP in c["service_zips"] for c in caregivers)

    def test_unserved_zip_has_none(self):
        assert find_available_caregivers(UNSERVED_ZIP, SERVICE) == []


class TestDecide:
    def test_accept_full_match(self):
        decision = decide(
            EligibilityRequest(
                patient_zip=SERVED_ZIP, insurance_plan=KNOWN_PLAN, service_type=SERVICE
            )
        )
        assert decision.status == "ACCEPT"
        assert decision.matched_plan == KNOWN_PLAN
        assert "face-to-face encounter note" in decision.required_documentation
        assert decision.matched_caregivers

    def test_decline_out_of_area(self):
        decision = decide(
            EligibilityRequest(
                patient_zip=UNSERVED_ZIP, insurance_plan=KNOWN_PLAN, service_type=SERVICE
            )
        )
        assert decision.status == "DECLINE"
        assert any("outside the service area" in reason for reason in decision.reasons)

    def test_needs_more_info_when_zip_missing(self):
        decision = decide(
            EligibilityRequest(patient_zip=None, insurance_plan=KNOWN_PLAN, service_type=SERVICE)
        )
        assert decision.status == "NEEDS_MORE_INFO"


class TestEndpoint:
    def test_eligibility_check_endpoint(self):
        response = client.post(
            "/eligibility-check",
            json={
                "patient_zip": SERVED_ZIP,
                "insurance_plan": KNOWN_PLAN,
                "service_type": SERVICE,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ACCEPT"
        assert body["matched_caregivers"]

    def test_endpoint_decline_out_of_area(self):
        response = client.post(
            "/eligibility-check",
            json={
                "patient_zip": UNSERVED_ZIP,
                "insurance_plan": KNOWN_PLAN,
                "service_type": SERVICE,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "DECLINE"
        assert body["reasons"]

    def test_endpoint_needs_more_info_when_fields_missing(self):
        response = client.post(
            "/eligibility-check",
            json={"insurance_plan": KNOWN_PLAN, "service_type": SERVICE},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "NEEDS_MORE_INFO"
        assert body["reasons"]

    def test_endpoint_rejects_malformed_payload(self):
        response = client.post(
            "/eligibility-check",
            json={"patient_zip": ["not", "a", "string"]},
        )
        assert response.status_code == 422
