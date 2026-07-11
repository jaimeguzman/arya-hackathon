"""Feature #28 — Layer 1 ingestion and preprocessing."""

from pathlib import Path

import fitz
import pytest
from PIL import Image

from app.pipeline.ingestion import (
    CLEANUP_STEPS,
    PAGE_TYPE_DIGITAL_TEXT,
    PAGE_TYPE_SCANNED_IMAGE,
    classify_page_text,
    cleanup_page_image,
    estimate_skew_angle,
    ingest_document,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FAX_DIR = REPO_ROOT / "data" / "synthetic" / "referral_faxes"

CLEAN_PDF = FAX_DIR / "REF-1001_complete_clean.pdf"
SCANNED_PDF = FAX_DIR / "REF-1003_messy_scanned_fax.pdf"

EXPECTED_SAMPLE_PAGE_COUNT = 3


def test_clean_pdf_pages_detected_as_digital_text():
    pages = ingest_document(CLEAN_PDF)
    assert len(pages) == EXPECTED_SAMPLE_PAGE_COUNT
    assert [p.page_number for p in pages] == [1, 2, 3]
    for page in pages:
        assert page.page_type == PAGE_TYPE_DIGITAL_TEXT
        assert page.text  # text layer preserved
        assert page.image is None
        assert page.cleanup_applied == ()


def test_scanned_pdf_pages_detected_and_cleaned():
    pages = ingest_document(SCANNED_PDF)
    assert len(pages) == EXPECTED_SAMPLE_PAGE_COUNT
    for page in pages:
        assert page.page_type == PAGE_TYPE_SCANNED_IMAGE
        assert page.text == ""
        assert page.image is not None
        assert page.image.mode == "L"  # standardized grayscale
        assert page.cleanup_applied == CLEANUP_STEPS


def test_tiff_input_is_standardized(tmp_path):
    tiff_path = tmp_path / "fax.tiff"
    Image.new("L", (200, 100), color=255).save(tiff_path)
    pages = ingest_document(tiff_path)
    assert len(pages) == 1
    assert pages[0].page_type == PAGE_TYPE_SCANNED_IMAGE
    assert pages[0].image is not None


def test_unsupported_extension_rejected(tmp_path):
    bogus = tmp_path / "fax.docx"
    bogus.write_bytes(b"not a fax")
    with pytest.raises(ValueError):
        ingest_document(bogus)


def test_missing_file_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        ingest_document(tmp_path / "absent.pdf")


def test_classify_page_text_threshold():
    assert classify_page_text("Patient: Jane Doe, DOB 01/02/1950") == (
        PAGE_TYPE_DIGITAL_TEXT
    )
    assert classify_page_text("") == PAGE_TYPE_SCANNED_IMAGE
    assert classify_page_text("  \n ok \n") == PAGE_TYPE_SCANNED_IMAGE


def _text_lines_image(rotation: float) -> Image.Image:
    """White page with dark horizontal stripes, optionally rotated (skewed)."""
    image = Image.new("L", (400, 300), color=255)
    stripe_height = 4
    for top in range(40, 260, 25):
        image.paste(0, (40, top, 360, top + stripe_height))
    if rotation:
        image = image.rotate(rotation, expand=False, fillcolor=255)
    return image


def test_deskew_detects_and_corrects_rotation():
    skewed = _text_lines_image(rotation=3.0)
    estimated = estimate_skew_angle(skewed)
    assert estimated == pytest.approx(-3.0, abs=1.0)
    cleaned = cleanup_page_image(skewed)
    # After deskew the row-profile variance should recover most of the
    # unskewed image's line structure.
    assert abs(estimate_skew_angle(cleaned)) <= 1.0


def test_mixed_document_per_page_types(tmp_path):
    """A PDF combining a digital-text page and a blank scanned page."""
    mixed = tmp_path / "mixed.pdf"
    document = fitz.open()
    text_page = document.new_page()
    text_page.insert_text(
        (72, 72),
        "Patient: John Smith\nDOB: 03/04/1948\nDiagnosis: I50.9 heart failure",
    )
    document.new_page()  # blank page -> scanned-image
    document.save(mixed)
    document.close()

    pages = ingest_document(mixed)
    assert [p.page_type for p in pages] == [
        PAGE_TYPE_DIGITAL_TEXT,
        PAGE_TYPE_SCANNED_IMAGE,
    ]
