"""Layer 5 Validation Agent tests — one passing record, one failure per validator."""

from datetime import date
from pathlib import Path

import pytest

from app.pipeline.validation import (
    Medication,
    ValidationRecord,
    load_validation_reference,
    npi_luhn_valid,
    parse_dosage_mg,
    validate_record,
)

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "reference"
TODAY = date(2026, 7, 11)


def _luhn_check_digit(nine_digits: str) -> str:
    digits = [int(ch) for ch in "80840" + nine_digits]
    total = 0
    for idx, digit in enumerate(reversed(digits + [0])):
        if idx % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return str((10 - total % 10) % 10)


VALID_NPI = "123456789" + _luhn_check_digit("123456789")
INVALID_NPI = VALID_NPI[:-1] + str((int(VALID_NPI[-1]) + 1) % 10)


@pytest.fixture(scope="module")
def reference():
    return load_validation_reference(DATA_DIR)


def nppes_offline(_npi):
    return None


def make_record(**overrides):
    base = dict(
        icd_codes=("I10", "M17.11"),
        npi=VALID_NPI,
        member_id="H120456789",
        payer="Humana",
        date_of_birth=date(1950, 3, 2),
        admission_date=date(2026, 6, 20),
        discharge_date=date(2026, 7, 1),
        patient_zip="11215",
        medications=(Medication(name="Lisinopril", dosage="20mg"),),
    )
    base.update(overrides)
    return ValidationRecord(**base)


def test_reference_tables_load(reference):
    assert "I10" in reference.icd10_codes
    assert "11215" in reference.zip_codes
    assert reference.dosage_ranges["metformin"] == (500.0, 2000.0)


def test_fully_valid_record_passes(reference):
    report = validate_record(
        make_record(), reference, nppes_lookup=nppes_offline, today=TODAY
    )
    assert report.is_valid, report.failures
    assert not report.nppes_checked  # offline: Luhn-only path


def test_invalid_icd10_names_field_and_rule(reference):
    report = validate_record(
        make_record(icd_codes=("I10", "M17.1I")),
        reference,
        nppes_lookup=nppes_offline,
        today=TODAY,
    )
    (failure,) = report.failures
    assert failure.field == "icd_codes[1]"
    assert failure.rule == "icd10_table_lookup"
    assert "M17.1I" in failure.message


def test_npi_luhn_helper():
    assert npi_luhn_valid(VALID_NPI)
    assert not npi_luhn_valid(INVALID_NPI)
    assert not npi_luhn_valid("12345")
    assert not npi_luhn_valid("12345678AB")


def test_npi_luhn_failure_flagged_even_when_nppes_unreachable(reference):
    report = validate_record(
        make_record(npi=INVALID_NPI),
        reference,
        nppes_lookup=nppes_offline,
        today=TODAY,
    )
    (failure,) = report.failures
    assert failure.rule == "npi_luhn"
    assert not report.nppes_checked


def test_npi_nppes_not_found_flagged_when_online(reference):
    report = validate_record(
        make_record(),
        reference,
        nppes_lookup=lambda _npi: False,
        today=TODAY,
    )
    (failure,) = report.failures
    assert failure.rule == "npi_nppes_registry"
    assert report.nppes_checked


def test_npi_nppes_found_passes_when_online(reference):
    report = validate_record(
        make_record(), reference, nppes_lookup=lambda _npi: True, today=TODAY
    )
    assert report.is_valid
    assert report.nppes_checked


def test_member_id_wrong_payer_format_flagged(reference):
    report = validate_record(
        make_record(member_id="H12O456789"),  # letter O corrupts Humana format
        reference,
        nppes_lookup=nppes_offline,
        today=TODAY,
    )
    (failure,) = report.failures
    assert failure.field == "member_id"
    assert failure.rule == "member_id_payer_format"
    assert "Humana" in failure.message


def test_dob_in_future_rejected(reference):
    report = validate_record(
        make_record(date_of_birth=date(2027, 1, 1)),
        reference,
        nppes_lookup=nppes_offline,
        today=TODAY,
    )
    (failure,) = report.failures
    assert failure.rule == "dob_reasonable"
    assert "future" in failure.message


def test_dob_older_than_120_years_rejected(reference):
    report = validate_record(
        make_record(date_of_birth=date(1900, 1, 1)),
        reference,
        nppes_lookup=nppes_offline,
        today=TODAY,
    )
    (failure,) = report.failures
    assert failure.rule == "dob_reasonable"
    assert "120" in failure.message


def test_discharge_before_admission_flagged(reference):
    report = validate_record(
        make_record(
            admission_date=date(2026, 7, 1), discharge_date=date(2026, 6, 20)
        ),
        reference,
        nppes_lookup=nppes_offline,
        today=TODAY,
    )
    (failure,) = report.failures
    assert failure.field == "discharge_date"
    assert failure.rule == "discharge_after_admission"


def test_nonexistent_zip_flagged(reference):
    report = validate_record(
        make_record(patient_zip="00000"),
        reference,
        nppes_lookup=nppes_offline,
        today=TODAY,
    )
    (failure,) = report.failures
    assert failure.field == "patient_zip"
    assert failure.rule == "zip_exists"


def test_metformin_50000mg_flagged_as_ocr_error(reference):
    report = validate_record(
        make_record(medications=(Medication(name="Metformin", dosage="50000mg"),)),
        reference,
        nppes_lookup=nppes_offline,
        today=TODAY,
    )
    (failure,) = report.failures
    assert failure.field == "medications[0].dosage"
    assert failure.rule == "dosage_within_range"
    assert "OCR" in failure.message


def test_unknown_medication_is_not_range_checked(reference):
    report = validate_record(
        make_record(medications=(Medication(name="Placebozine", dosage="9999mg"),)),
        reference,
        nppes_lookup=nppes_offline,
        today=TODAY,
    )
    assert report.is_valid


def test_unparseable_dosage_for_known_medication_flagged(reference):
    report = validate_record(
        make_record(medications=(Medication(name="Lisinopril", dosage="2Omg"),)),
        reference,
        nppes_lookup=nppes_offline,
        today=TODAY,
    )
    (failure,) = report.failures
    assert failure.rule == "dosage_within_range"
    assert "parseable" in failure.message


def test_parse_dosage_mg():
    assert parse_dosage_mg("500mg") == 500.0
    assert parse_dosage_mg("2.5 mg") == 2.5
    assert parse_dosage_mg("two pills") is None
