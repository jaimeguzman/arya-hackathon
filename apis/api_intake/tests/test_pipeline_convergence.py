"""Feature #32 — Layer 4: both paths converge into standardized raw JSON."""

from __future__ import annotations

import json

import pytest

from app.pipeline.convergence import (
    CONVERGED_FIELD_NAMES,
    converge_document,
    normalize_page_fields,
)
from app.pipeline.extraction_rules import RuleExtractedFields
from app.pipeline.extraction_vision import VisionExtractedFields

RULE_FIELDS = RuleExtractedFields(
    patient_name="Margaret Holloway",
    icd_codes=["I50.9", "E11.9"],
    member_id="H120456789",
    member_id_payer="Humana",
    npi="1234567893",
)

VISION_FIELDS = VisionExtractedFields(
    patient_name="Robert Delgado",
    icd_codes=["M17.11"],
    member_id="1EG4TE5MK73",
    member_id_payer="Medicare",
    npi="1093817465",
)


def _schema_shape(page: dict) -> dict:
    """The structural shape of a normalized page: keys and per-field keys."""
    return {name: sorted(entry.keys()) for name, entry in page.items()}


def test_both_paths_normalize_to_identical_schema():
    rules_page = normalize_page_fields(RULE_FIELDS)
    vision_page = normalize_page_fields(VISION_FIELDS)
    assert _schema_shape(rules_page) == _schema_shape(vision_page)
    assert tuple(rules_page.keys()) == CONVERGED_FIELD_NAMES
    assert tuple(vision_page.keys()) == CONVERGED_FIELD_NAMES


@pytest.mark.parametrize(
    ("fields", "expected_path"),
    [(RULE_FIELDS, "rules"), (VISION_FIELDS, "vision")],
)
def test_every_field_carries_its_extraction_path(fields, expected_path):
    page = normalize_page_fields(fields)
    for name in CONVERGED_FIELD_NAMES:
        assert page[name]["extraction_path"] == expected_path
        assert page[name]["value"] == getattr(fields, name)


def test_normalized_page_is_json_serializable():
    page = normalize_page_fields(RULE_FIELDS)
    assert json.loads(json.dumps(page)) == page


def test_converge_document_merges_pages_from_both_paths():
    converged = converge_document(
        rule_results={1: RULE_FIELDS},
        vision_results={2: VISION_FIELDS},
    )
    assert list(converged.keys()) == [1, 2]
    assert converged[1]["patient_name"]["extraction_path"] == "rules"
    assert converged[2]["patient_name"]["extraction_path"] == "vision"
    assert _schema_shape(converged[1]) == _schema_shape(converged[2])


def test_converge_document_pages_sorted_by_page_number():
    converged = converge_document(
        rule_results={3: RULE_FIELDS},
        vision_results={1: VISION_FIELDS},
    )
    assert list(converged.keys()) == [1, 3]


def test_converge_document_rejects_page_routed_to_both_paths():
    with pytest.raises(ValueError, match=r"\[2\]"):
        converge_document(
            rule_results={2: RULE_FIELDS},
            vision_results={2: VISION_FIELDS},
        )


def test_empty_fields_normalize_with_null_values():
    page = normalize_page_fields(RuleExtractedFields())
    assert page["patient_name"]["value"] is None
    assert page["icd_codes"]["value"] == []
    assert page["member_id"]["value"] is None
    assert page["npi"]["value"] is None
