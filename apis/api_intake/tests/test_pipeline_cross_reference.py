"""Layer 5 Cross-Reference Agent tests — one test per cross-reference rule."""

from datetime import date
from pathlib import Path

import pytest

from app.pipeline.cross_reference import (
    CrossReferenceRouting,
    CrossReferenceRule,
    CrossRefDocument,
    Diagnosis,
    cross_reference_documents,
    load_cross_reference_reference,
    normalize_patient_name,
)

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "reference"


@pytest.fixture(scope="module")
def reference():
    return load_cross_reference_reference(DATA_DIR)


def _doc(document_id="doc-1", **kwargs):
    return CrossRefDocument(document_id=document_id, **kwargs)


def _rules(report):
    return [f.rule for f in report.flags]


def test_consistent_packet_has_no_flags(reference):
    docs = [
        _doc(
            "referral",
            patient_name="Margaret Chen",
            date_of_birth=date(1942, 3, 8),
            diagnoses=(Diagnosis(text="Atrial fibrillation", icd_code="I48.91"),),
            medications=("Warfarin",),
        ),
        _doc(
            "face-to-face",
            patient_name="Chen, Margaret",
            date_of_birth=date(1942, 3, 8),
        ),
    ]
    report = cross_reference_documents(docs, reference)
    assert report.is_consistent
    assert report.checks_run  # checks actually ran, packet is simply clean


def test_patient_name_mismatch_flagged(reference):
    docs = [
        _doc("referral", patient_name="Margaret Chen"),
        _doc("orders", patient_name="Margaret Cohen"),
    ]
    report = cross_reference_documents(docs, reference)
    assert _rules(report) == [CrossReferenceRule.PATIENT_NAME_MISMATCH]
    assert report.flags[0].documents == ("referral", "orders")
    assert report.flags[0].routing is CrossReferenceRouting.VERIFICATION


def test_name_order_and_punctuation_do_not_flag(reference):
    docs = [
        _doc("referral", patient_name="Chen, Margaret"),
        _doc("orders", patient_name="MARGARET CHEN"),
    ]
    assert cross_reference_documents(docs, reference).is_consistent


def test_dob_mismatch_flagged(reference):
    docs = [
        _doc("referral", date_of_birth=date(1942, 3, 8)),
        _doc("orders", date_of_birth=date(1942, 8, 3)),
    ]
    report = cross_reference_documents(docs, reference)
    assert _rules(report) == [CrossReferenceRule.PATIENT_DOB_MISMATCH]


def test_single_document_skips_identity_checks(reference):
    docs = [_doc("referral", patient_name="Margaret Chen")]
    report = cross_reference_documents(docs, reference)
    assert report.is_consistent
    assert CrossReferenceRule.PATIENT_NAME_MISMATCH.value not in report.checks_run


def test_diagnosis_text_matching_icd_code_passes(reference):
    docs = [
        _doc(
            diagnoses=(
                Diagnosis(text="CHF exacerbation, heart failure", icd_code="I50.9"),
            )
        )
    ]
    assert cross_reference_documents(docs, reference).is_consistent


def test_diagnosis_text_icd_code_mismatch_flagged(reference):
    docs = [
        _doc(diagnoses=(Diagnosis(text="Parkinson's disease", icd_code="I50.9"),))
    ]
    report = cross_reference_documents(docs, reference)
    assert _rules(report) == [CrossReferenceRule.DIAGNOSIS_CODE_MISMATCH]
    assert "I50.9" in report.flags[0].message


def test_unknown_icd_code_left_to_validation_agent(reference):
    docs = [_doc(diagnoses=(Diagnosis(text="Something", icd_code="X99.99"),))]
    report = cross_reference_documents(docs, reference)
    assert report.is_consistent
    assert CrossReferenceRule.DIAGNOSIS_CODE_MISMATCH.value not in report.checks_run


def test_warfarin_without_anticoagulation_indication_flagged(reference):
    docs = [
        _doc(
            "referral",
            diagnoses=(Diagnosis(text="Hypertension", icd_code="I10"),),
            medications=("Warfarin",),
        )
    ]
    report = cross_reference_documents(docs, reference)
    assert _rules(report) == [CrossReferenceRule.MEDICATION_WITHOUT_INDICATION]
    flag = report.flags[0]
    assert flag.routing is CrossReferenceRouting.CLINICAL_REVIEW
    assert report.clinical_review_flags == (flag,)
    assert "Warfarin" in flag.message


def test_warfarin_indication_on_another_document_satisfies(reference):
    docs = [
        _doc("med-list", medications=("Warfarin",)),
        _doc(
            "referral",
            diagnoses=(Diagnosis(text="Atrial fibrillation", icd_code="I48.91"),),
        ),
    ]
    assert cross_reference_documents(docs, reference).is_consistent


def test_medication_without_rule_is_not_checked(reference):
    docs = [_doc(medications=("Furosemide",))]
    report = cross_reference_documents(docs, reference)
    assert report.is_consistent
    assert (
        CrossReferenceRule.MEDICATION_WITHOUT_INDICATION.value
        not in report.checks_run
    )


def test_normalize_patient_name():
    assert normalize_patient_name("Doe, John") == normalize_patient_name("John DOE")
