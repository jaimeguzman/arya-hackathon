"""Feature #29 — Layer 2 page classification into document types."""

from pathlib import Path

from PIL import Image

from app.pipeline.classification import (
    DOC_TYPE_CONSENT_FORM,
    DOC_TYPE_DISCHARGE_SUMMARY,
    DOC_TYPE_FACE_TO_FACE_NOTE,
    DOC_TYPE_FAX_COVER_SHEET,
    DOC_TYPE_INSURANCE_CARD,
    DOC_TYPE_LAB_RESULTS,
    DOC_TYPE_MEDICATION_LIST,
    DOC_TYPE_PHYSICIAN_ORDER,
    DOC_TYPE_UNKNOWN,
    DOCUMENT_TYPES,
    classify_page,
    classify_pages,
    pages_for_extraction,
)
from app.pipeline.ingestion import (
    PAGE_TYPE_DIGITAL_TEXT,
    PAGE_TYPE_SCANNED_IMAGE,
    IngestedPage,
    ingest_document,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CLEAN_PDF = REPO_ROOT / "data" / "synthetic" / "referral_faxes" / "REF-1001_complete_clean.pdf"


def _text_page(text: str, page_number: int = 1) -> IngestedPage:
    return IngestedPage(
        page_number=page_number,
        page_type=PAGE_TYPE_DIGITAL_TEXT,
        text=text,
        image=None,
        cleanup_applied=(),
    )


def test_all_spec_document_types_are_supported():
    assert set(DOCUMENT_TYPES) == {
        DOC_TYPE_PHYSICIAN_ORDER,
        DOC_TYPE_FACE_TO_FACE_NOTE,
        DOC_TYPE_DISCHARGE_SUMMARY,
        DOC_TYPE_MEDICATION_LIST,
        DOC_TYPE_INSURANCE_CARD,
        DOC_TYPE_LAB_RESULTS,
        DOC_TYPE_CONSENT_FORM,
        DOC_TYPE_FAX_COVER_SHEET,
    }


def test_each_document_type_classified_from_representative_text():
    samples = {
        DOC_TYPE_PHYSICIAN_ORDER: "PHYSICIAN ORDERS\nOrdering Physician: Dr. Kessler\nOrders Signed: Yes",
        DOC_TYPE_FACE_TO_FACE_NOTE: "FACE-TO-FACE ENCOUNTER NOTE\nEncounter date 2026-07-05",
        DOC_TYPE_DISCHARGE_SUMMARY: "DISCHARGE SUMMARY\nDischarge Date: 2026-07-03\nClinical Summary",
        DOC_TYPE_MEDICATION_LIST: "MEDICATION LIST\nCurrent Medications: Lisinopril 10mg daily",
        DOC_TYPE_INSURANCE_CARD: "INSURANCE CARD\nSubscriber: Jane Doe\nGroup Number: 4471",
        DOC_TYPE_LAB_RESULTS: "LAB RESULTS\nSpecimen: blood\nReference Range: 3.5-5.0",
        DOC_TYPE_CONSENT_FORM: "PATIENT CONSENT\nConsent to Treat signed by patient",
        DOC_TYPE_FAX_COVER_SHEET: "FAX COVER SHEET\nTo: Intake\nPages (incl. cover): 3",
    }
    for expected, text in samples.items():
        assert classify_page(_text_page(text)).doc_type == expected


def test_cover_sheet_marked_junk_and_excluded_from_extraction():
    classified = classify_pages(
        [
            _text_page("FAX COVER SHEET\nPages (incl. cover): 2", page_number=1),
            _text_page("PHYSICIAN ORDERS\nOrders Signed: Yes", page_number=2),
        ]
    )
    assert classified[0].is_junk is True
    assert classified[1].is_junk is False
    extractable = pages_for_extraction(classified)
    assert [entry.page.page_number for entry in extractable] == [2]


def test_sample_packet_expected_classifications_per_page():
    classified = classify_pages(ingest_document(CLEAN_PDF))
    assert [entry.doc_type for entry in classified] == [
        DOC_TYPE_FAX_COVER_SHEET,
        DOC_TYPE_DISCHARGE_SUMMARY,
        DOC_TYPE_PHYSICIAN_ORDER,
    ]
    assert [entry.is_junk for entry in classified] == [True, False, False]
    assert len(pages_for_extraction(classified)) == 2


def test_scanned_page_without_text_is_unknown_not_junk():
    page = IngestedPage(
        page_number=1,
        page_type=PAGE_TYPE_SCANNED_IMAGE,
        text="",
        image=Image.new("L", (10, 10), color=255),
        cleanup_applied=("deskew", "denoise", "contrast"),
    )
    classified = classify_page(page)
    assert classified.doc_type == DOC_TYPE_UNKNOWN
    assert classified.is_junk is False
    # Unknown pages still flow to extraction (vision path resolves them).
    assert pages_for_extraction([classified]) == [classified]


def test_text_with_no_keyword_hits_is_unknown():
    assert classify_page(_text_page("lorem ipsum dolor sit amet")).doc_type == (
        DOC_TYPE_UNKNOWN
    )
