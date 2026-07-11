"""Feature #18: EligibilityResult model — one status + structured reasons,
JSON-serializable for API responses and audit records."""

import json

import pytest
from pydantic import ValidationError

from app.safety.eligibility import EligibilityResult, EligibilityStatus


def test_status_enum_has_exactly_three_values():
    assert {s.value for s in EligibilityStatus} == {
        "ACCEPT",
        "DECLINE",
        "NEEDS_MORE_INFO",
    }


@pytest.mark.parametrize("status", list(EligibilityStatus))
def test_each_status_constructs_and_serializes_to_json(status):
    result = EligibilityResult(status=status, reasons=["reason one", "reason two"])
    payload = json.loads(result.model_dump_json())
    assert payload == {"status": status.value, "reasons": ["reason one", "reason two"]}


def test_invalid_status_is_rejected():
    with pytest.raises(ValidationError):
        EligibilityResult(status="MAYBE", reasons=[])


def test_reasons_must_be_a_list_of_strings():
    with pytest.raises(ValidationError):
        EligibilityResult(status=EligibilityStatus.ACCEPT, reasons="not-a-list")
