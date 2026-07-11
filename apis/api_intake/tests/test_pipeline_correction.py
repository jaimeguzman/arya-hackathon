"""Layer 5 Correction Agent tests — all three confidence outcomes."""

from datetime import date
from pathlib import Path

import pytest

from app.pipeline.correction import (
    CorrectionAction,
    CorrectionConfidence,
    correct_failures,
    ocr_substitution_candidates,
)
from app.pipeline.validation import (
    Medication,
    ValidationRecord,
    load_validation_reference,
    validate_record,
)

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "reference"
TODAY = date(2026, 7, 11)


@pytest.fixture(scope="module")
def reference():
    return load_validation_reference(DATA_DIR)


def _run(record, reference):
    report = validate_record(
        record, reference, nppes_lookup=lambda npi: None, today=TODAY
    )
    return correct_failures(record, report, reference)


def test_ocr_candidates_include_confusion_substitutions():
    candidates = ocr_substitution_candidates("M17.1I")
    assert "M17.11" in candidates
    assert "M17.1I" not in candidates


def test_icd_ocr_error_auto_corrected_high_confidence(reference):
    record = ValidationRecord(icd_codes=("M17.1I",))
    result = _run(record, reference)
    assert len(result.corrections) == 1
    correction = result.corrections[0]
    assert correction.original_value == "M17.1I"
    assert correction.corrected_value == "M17.11"
    assert correction.confidence is CorrectionConfidence.HIGH
    assert correction.action is CorrectionAction.AUTO_CORRECT
    assert result.gap_list == ()
    assert result.auto_corrected == (correction,)


def test_member_id_ocr_error_medium_confidence_flagged(reference):
    record = ValidationRecord(member_id="H12O456789", payer="Humana")
    result = _run(record, reference)
    assert len(result.corrections) == 1
    correction = result.corrections[0]
    assert correction.original_value == "H12O456789"
    assert correction.corrected_value == "H120456789"
    assert correction.confidence is CorrectionConfidence.MEDIUM
    assert correction.action is CorrectionAction.APPLY_FLAG_REVIEW
    assert correction in result.flagged_for_review
    assert result.gap_list == ()


def test_uncorrectable_dosage_low_confidence_gap_listed(reference):
    record = ValidationRecord(
        medications=(Medication(name="Lisinopril", dosage="200mg"),)
    )
    result = _run(record, reference)
    assert len(result.corrections) == 1
    correction = result.corrections[0]
    assert correction.corrected_value is None
    assert correction.confidence is CorrectionConfidence.LOW
    assert correction.action is CorrectionAction.HUMAN_REVIEW
    assert len(result.gap_list) == 1
    gap = result.gap_list[0]
    assert gap.field == "medications[0].dosage"
    assert gap.original_value == "200mg"


def test_unknown_rule_falls_back_to_human_review_with_gap(reference):
    record = ValidationRecord(patient_zip="00000")
    result = _run(record, reference)
    assert len(result.corrections) == 1
    correction = result.corrections[0]
    assert correction.confidence is CorrectionConfidence.LOW
    assert correction.action is CorrectionAction.HUMAN_REVIEW
    assert result.gap_list[0].field == "patient_zip"


def test_ambiguous_icd_correction_not_applied(reference):
    # No single-substitution candidate exists in the reference table.
    record = ValidationRecord(icd_codes=("X99.99",))
    result = _run(record, reference)
    correction = result.corrections[0]
    assert correction.corrected_value is None
    assert correction.confidence is CorrectionConfidence.LOW
    assert result.gap_list[0].field == "icd_codes[0]"


def test_valid_record_produces_empty_report(reference):
    record = ValidationRecord(icd_codes=("M17.11",))
    result = _run(record, reference)
    assert result.corrections == ()
    assert result.gap_list == ()
