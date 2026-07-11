"""Features 19/20: service-area and insurance checks against reference data."""

from pathlib import Path

import pytest

from app.eligibility.checks import (
    check_insurance,
    check_service_area,
    fuzzy_match_plan,
    trigram_similarity,
)
from app.eligibility.reference_data import load_reference_data
from app.safety.eligibility import EligibilityStatus

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data" / "reference"


@pytest.fixture(scope="module")
def data():
    return load_reference_data(DATA_DIR)


class TestReferenceData:
    def test_loads_zips_payers_and_plans(self, data):
        assert "11201" in data.service_area_zips
        assert "Medicare" in data.accepted_payers
        assert any(p.plan == "Medicare Part A" for p in data.plans)

    def test_missing_dir_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_reference_data(tmp_path)


class TestServiceArea:
    def test_served_zip_passes(self, data):
        result = check_service_area("11201", data)
        assert result.status is EligibilityStatus.ACCEPT

    def test_unserved_zip_hard_fails_with_reason(self, data):
        result = check_service_area("99999", data)
        assert result.status is EligibilityStatus.DECLINE
        assert "zip not served" in result.reason

    def test_missing_zip_needs_more_info(self, data):
        for missing in (None, "", "   "):
            result = check_service_area(missing, data)
            assert result.status is EligibilityStatus.NEEDS_MORE_INFO

    def test_whitespace_around_zip_tolerated(self, data):
        result = check_service_area(" 11201 ", data)
        assert result.status is EligibilityStatus.ACCEPT


class TestInsurance:
    def test_accepted_payer_and_plan_passes(self, data):
        result = check_insurance("Medicare", "Medicare Part A", data)
        assert result.status is EligibilityStatus.ACCEPT
        assert result.matched_plan is not None
        assert result.matched_plan.plan == "Medicare Part A"

    def test_unaccepted_payer_hard_fails_with_reason(self, data):
        result = check_insurance("Cigna", "Cigna PPO", data)
        assert result.status is EligibilityStatus.DECLINE
        assert "payer not accepted" in result.reason

    def test_fuzzy_plan_name_matches_before_failing(self, data):
        # Caller says "Humana Gold Plus" instead of "Humana Gold Plus HMO".
        result = check_insurance("Humana", "Humana Gold Plus", data)
        assert result.status is EligibilityStatus.ACCEPT
        assert result.matched_plan.plan == "Humana Gold Plus HMO"
        assert "fuzzy-matched" in result.reason

    def test_unmatched_plan_hard_fails(self, data):
        result = check_insurance("Humana", "Totally Unknown Plan XYZ", data)
        assert result.status is EligibilityStatus.DECLINE
        assert "plan not accepted" in result.reason

    def test_missing_payer_needs_more_info(self, data):
        result = check_insurance(None, "Medicare Part A", data)
        assert result.status is EligibilityStatus.NEEDS_MORE_INFO

    def test_missing_plan_needs_more_info(self, data):
        result = check_insurance("Medicare", None, data)
        assert result.status is EligibilityStatus.NEEDS_MORE_INFO

    def test_payer_match_is_case_insensitive(self, data):
        result = check_insurance("medicare", "medicare part a", data)
        assert result.status is EligibilityStatus.ACCEPT


class TestFuzzyMatching:
    def test_identical_strings_score_one(self):
        assert trigram_similarity("Medicare Part A", "Medicare Part A") == 1.0

    def test_disjoint_strings_score_zero(self):
        assert trigram_similarity("abc", "xyz") == 0.0

    def test_fuzzy_match_returns_none_below_threshold(self, data):
        assert fuzzy_match_plan("qqqq zzzz", data) is None
