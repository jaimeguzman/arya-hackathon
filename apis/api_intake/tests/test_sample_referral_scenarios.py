"""Acceptance test — Task 3 completion criteria.

Runs the 4 canonical sample referral scenarios
(data/synthetic/sample_referrals.json) through POST /eligibility-check and
asserts the expected ACCEPT / DECLINE / NEEDS_MORE_INFO decision for each,
with every decision completing well inside the 3-second mid-call budget
(PROJECT.md: the live-call eligibility loop must finish in 2-3 seconds).
"""

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REFERRALS_PATH = _REPO_ROOT / "data" / "synthetic" / "sample_referrals.json"

DECISION_BUDGET_SECONDS = 3.0

# scenario id -> expected decision, from the scenarios' own design:
# REF-1001 complete clean referral        -> ACCEPT
# REF-1002 missing F2F documentation      -> ACCEPT (gap surfaces as required doc)
# REF-1003 messy scan, low-confidence OCR -> ACCEPT (gaps are doc-quality issues)
# REF-1004 family call, no insurance yet  -> NEEDS_MORE_INFO (never a hard decline)
EXPECTED_STATUS = {
    "REF-1001": "ACCEPT",
    "REF-1002": "ACCEPT",
    "REF-1003": "ACCEPT",
    "REF-1004": "NEEDS_MORE_INFO",
}


def _load_referrals() -> list[dict]:
    return json.loads(_REFERRALS_PATH.read_text())["referrals"]


def _request_payload(referral: dict) -> dict:
    insurance = referral.get("insurance") or {}
    payer = insurance.get("payer")
    return {
        "patient_zip": (referral.get("patient") or {}).get("address", {}).get("zip"),
        # 'unknown' is the dataset's sentinel for "caller did not know".
        "payer": None if payer in (None, "unknown") else payer,
        "insurance_plan": insurance.get("plan"),
        "service_type": (referral.get("care_request") or {}).get("service_types", [None])[0],
        "diagnosis_code": (referral.get("clinical") or {})
        .get("primary_diagnosis", {})
        .get("icd10"),
    }


class TestSampleReferralScenarios:
    def test_all_four_scenarios_decide_correctly_within_budget(self):
        referrals = _load_referrals()
        assert len(referrals) == 4

        for referral in referrals:
            referral_id = referral["referral_id"]
            started = time.perf_counter()
            response = client.post("/eligibility-check", json=_request_payload(referral))
            elapsed = time.perf_counter() - started

            assert response.status_code == 200, referral_id
            body = response.json()
            assert body["status"] == EXPECTED_STATUS[referral_id], (
                f"{referral_id} ({referral['scenario']}): expected "
                f"{EXPECTED_STATUS[referral_id]}, got {body['status']} — {body['reasons']}"
            )
            assert body["reasons"], referral_id
            assert elapsed < DECISION_BUDGET_SECONDS, (
                f"{referral_id}: decision took {elapsed:.2f}s (budget {DECISION_BUDGET_SECONDS}s)"
            )

    def test_accepted_scenarios_surface_documentation_requirements(self):
        referrals = {r["referral_id"]: r for r in _load_referrals()}
        # REF-1002's known gap is the face-to-face note — the decision must
        # surface it so the Voice Agent can chase it (PROJECT.md Feature 4).
        response = client.post(
            "/eligibility-check", json=_request_payload(referrals["REF-1002"])
        )
        docs = response.json()["required_documentation"]
        assert any("face-to-face" in doc for doc in docs)

    def test_family_call_scenario_is_never_hard_declined(self):
        referrals = {r["referral_id"]: r for r in _load_referrals()}
        response = client.post(
            "/eligibility-check", json=_request_payload(referrals["REF-1004"])
        )
        body = response.json()
        assert body["status"] == "NEEDS_MORE_INFO"
        assert any("insurance" in reason for reason in body["reasons"])
