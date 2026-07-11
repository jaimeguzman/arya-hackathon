"""Feature #30 — Layer 3 Path B rule-based extraction (Docling + regex)."""

from pathlib import Path

import pytest

from app.pipeline.extraction_rules import (
    EXTRACTION_PATH_RULES,
    extract_document_fields,
    extract_fields,
    extract_icd_codes,
    extract_member_id,
    extract_npi,
    extract_patient_name,
    match_member_id_payer,
    parse_text_layer,
)

SAMPLE_CLEAN_PDF = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "synthetic"
    / "referral_faxes"
    / "REF-1001_complete_clean.pdf"
)


def test_patient_name_after_patient_or_name_label():
    assert extract_patient_name("Patient: John Smith\nDOB: 1950-01-01") == "John Smith"
    assert extract_patient_name("Name: Eleanor Marsh\nGender: F") == "Eleanor Marsh"
    assert extract_patient_name("no labels here") is None


def test_icd_codes_letter_plus_digits():
    text = "Primary Diagnosis: Z96.641 - hip joint\nSecondary: I10 hypertension\nAlso I10 again"
    assert extract_icd_codes(text) == ["Z96.641", "I10"]
    assert extract_icd_codes("no codes, just words") == []


@pytest.mark.parametrize(
    ("member_id", "payer"),
    [
        ("1EG4TE5MK73", "Medicare"),
        ("H120456789", "Humana"),
        ("AE7O91234X", "Aetna"),
        ("123456789", "UnitedHealthcare"),
        ("12345678AB", "State Medicaid"),
        ("NOT-A-KNOWN-FORMAT", None),
    ],
)
def test_member_id_payer_formats(member_id, payer):
    assert match_member_id_payer(member_id) == payer


def test_member_id_extracted_from_labeled_line():
    member_id, payer = extract_member_id("Payer: Medicare\nMember ID: 1EG4TE5MK73\n")
    assert member_id == "1EG4TE5MK73"
    assert payer == "Medicare"


def test_member_id_kept_when_no_payer_format_matches():
    member_id, payer = extract_member_id("Member ID: XQ7712345Z9999\n")
    # ID is kept; format mismatch is Layer 5 validation's problem
    assert member_id == "XQ7712345Z9999"
    assert payer is None


def test_npi_is_exactly_ten_digits():
    assert extract_npi("NPI: 1932384123\nPhone: 555-020-3301") == "1932384123"
    assert extract_npi("NPI: 12345") is None
    assert extract_npi("Phone: 5550203301") is None  # unlabeled digits ignored


def test_extract_fields_combines_all_rules():
    text = (
        "Name: Eleanor Marsh\n"
        "Primary Diagnosis: Z96.641\n"
        "NPI: 1932384123\n"
        "Member ID: H120456789\n"
    )
    fields = extract_fields(text)
    assert fields.patient_name == "Eleanor Marsh"
    assert fields.icd_codes == ["Z96.641"]
    assert fields.npi == "1932384123"
    assert fields.member_id == "H120456789"
    assert fields.member_id_payer == "Humana"
    assert fields.extraction_path == EXTRACTION_PATH_RULES


def test_docling_parses_text_layer_of_sample_pdf():
    pages = parse_text_layer(SAMPLE_CLEAN_PDF)
    assert len(pages) == 3
    assert "FAX COVER SHEET" in pages[0]
    assert "Eleanor Marsh" in pages[1]
    assert "1932384123" in pages[2]


def test_docling_plus_rules_end_to_end_on_sample_pdf():
    per_page = extract_document_fields(SAMPLE_CLEAN_PDF)
    assert len(per_page) == 3
    demographics = per_page[1]
    assert demographics.patient_name == "Eleanor Marsh"
    assert demographics.icd_codes == ["Z96.641", "I10"]
    orders = per_page[2]
    assert orders.npi == "1932384123"
    assert orders.member_id == "1EG4TE5MK73"
    assert orders.member_id_payer == "Medicare"
