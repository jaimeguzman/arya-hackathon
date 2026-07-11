"""Features 23/24: coverage rules and decision-engine bias."""

from pathlib import Path

import pytest

from app.eligibility.checks import check_coverage, check_insurance
from app.eligibility.decision import decide_eligibility
from app.eligibility.reference_data import load_reference_data
from app.safety.eligibility import EligibilityStatus

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data" / "reference"

SERVED_ZIP = "11201"


@pytest.fixture(scope="module")
def data():
    return load_reference_data(DATA_DIR)


def plan_of(data, payer, plan):
    return next(p for p in data.plans if p.payer == payer and p.plan == plan)


class TestCoverage:
    def test_covered_service_passes(self, data):
        plan = plan_of(data, "Medicare", "Medicare Part A")
        result = check_coverage(plan, "skilled_nursing")
        assert result.status is EligibilityStatus.ACCEPT
        assert result.documentation_needs == ()

    def test_uncovered_service_declines_with_reason(self, data):
        plan = plan_of(data, "Humana", "Humana Gold Plus HMO")
        assert "speech_therapy" not in plan.covers
        result = check_coverage(plan, "speech_therapy")
        assert result.status is EligibilityStatus.DECLINE
        assert "service not covered" in result.reason

    def test_prior_auth_surfaces_documentation_need(self, data):
        plan = plan_of(data, "Humana", "Humana Gold Plus HMO")
        assert plan.requires_prior_auth
        result = check_coverage(plan, "skilled_nursing")
        assert result.status is EligibilityStatus.ACCEPT
        assert any(
            "prior authorization required" in need
            for need in result.documentation_needs
        )

    def test_unresolved_plan_needs_more_info(self):
        result = check_coverage(None, "skilled_nursing")
        assert result.status is EligibilityStatus.NEEDS_MORE_INFO

    def test_missing_service_type_needs_more_info(self, data):
        plan = plan_of(data, "Medicare", "Medicare Part A")
        for missing in (None, "", "  "):
            result = check_coverage(plan, missing)
            assert result.status is EligibilityStatus.NEEDS_MORE_INFO


class TestDecisionEngineBias:
    def test_all_facts_good_accepts(self, data):
        decision = decide_eligibility(
            SERVED_ZIP, "Medicare", "Medicare Part A", "skilled_nursing", True, data
        )
        assert decision.status is EligibilityStatus.ACCEPT

    def test_unserved_zip_declines(self, data):
        decision = decide_eligibility(
            "99999", "Medicare", "Medicare Part A", "skilled_nursing", True, data
        )
        assert decision.status is EligibilityStatus.DECLINE
        assert any("zip not served" in r for r in decision.reasons)

    def test_unaccepted_payer_declines(self, data):
        decision = decide_eligibility(
            SERVED_ZIP, "Nonexistent Payer", "Some Plan", "skilled_nursing", True, data
        )
        assert decision.status is EligibilityStatus.DECLINE

    def test_uncovered_service_declines(self, data):
        decision = decide_eligibility(
            SERVED_ZIP,
            "Humana",
            "Humana Gold Plus HMO",
            "speech_therapy",
            True,
            data,
        )
        assert decision.status is EligibilityStatus.DECLINE

    def test_prior_auth_carried_into_accept(self, data):
        decision = decide_eligibility(
            SERVED_ZIP,
            "Humana",
            "Humana Gold Plus HMO",
            "skilled_nursing",
            True,
            data,
        )
        assert decision.status is EligibilityStatus.ACCEPT
        assert any(
            "prior authorization required" in n for n in decision.documentation_needs
        )

    @pytest.mark.parametrize(
        "kwargs, expected_fragment",
        [
            (dict(patient_zip=None), "zip"),
            (dict(payer=None), "payer"),
            (dict(plan=None), "plan"),
            (dict(service_type=None), "service"),
            (dict(caregivers_available=None), "caregiver matching has not been run"),
            (dict(caregivers_available=False), "no qualified caregiver matched"),
        ],
    )
    def test_ambiguity_never_declines(self, data, kwargs, expected_fragment):
        base = dict(
            patient_zip=SERVED_ZIP,
            payer="Medicare",
            plan="Medicare Part A",
            service_type="skilled_nursing",
            caregivers_available=True,
        )
        base.update(kwargs)
        decision = decide_eligibility(data=data, **base)
        assert decision.status is EligibilityStatus.NEEDS_MORE_INFO
        assert decision.status is not EligibilityStatus.DECLINE
        assert any(expected_fragment in r for r in decision.reasons)

    def test_fuzzy_plan_match_needs_confirmation_not_decline(self, data):
        fuzzy_check = check_insurance("Medicare", "Medicare Prt A", data)
        assert fuzzy_check.fuzzy, "precondition: name must route through fuzzy match"
        decision = decide_eligibility(
            SERVED_ZIP, "Medicare", "Medicare Prt A", "skilled_nursing", True, data
        )
        assert decision.status is EligibilityStatus.NEEDS_MORE_INFO
        assert any("needs confirmation" in r for r in decision.reasons)

    def test_multiple_missing_items_all_listed(self, data):
        decision = decide_eligibility(None, None, None, None, None, data)
        assert decision.status is EligibilityStatus.NEEDS_MORE_INFO
        assert len(decision.reasons) >= 4
