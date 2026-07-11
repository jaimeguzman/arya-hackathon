"""Feature #31 — Layer 3 Path C: Gemini vision extraction for image pages."""

import json
from pathlib import Path

import pytest
from PIL import Image

from app.pipeline.extraction_vision import (
    EXTRACTION_PATH_VISION,
    VISION_EXTRACTION_PROMPT,
    VisionExtractedFields,
    VisionExtractionError,
    extract_fields_from_image,
    extract_image_page_fields,
    parse_vision_response,
)
from app.pipeline.ingestion import (
    PAGE_TYPE_DIGITAL_TEXT,
    PAGE_TYPE_SCANNED_IMAGE,
    IngestedPage,
    ingest_document,
)
from app.safety.llm_gateway import scan_for_identifiers

REPO_ROOT = Path(__file__).resolve().parents[3]
SCANNED_PDF = (
    REPO_ROOT / "data" / "synthetic" / "referral_faxes" / "REF-1003_messy_scanned_fax.pdf"
)

SAMPLE_RESPONSE = json.dumps(
    {
        "patient_name": "Eleanor Marsh",
        "icd_codes": ["Z96.641", "I10"],
        "member_id": "1EG4TE5MK73",
        "npi": "1234567893",
    }
)


def _blank_image() -> Image.Image:
    return Image.new("L", (200, 100), color=255)


def _mock_transport(response: str = SAMPLE_RESPONSE, calls: list | None = None):
    def transport(payload: str) -> str:
        if calls is not None:
            calls.append(payload)
        return response

    return transport


def test_extraction_routes_through_llm_gateway_with_clean_prompt():
    """The prompt reaches the transport via call_llm and carries no identifiers."""
    calls: list[str] = []
    extract_fields_from_image(_blank_image(), transport=_mock_transport(calls=calls))
    assert calls == [VISION_EXTRACTION_PROMPT]
    assert scan_for_identifiers(VISION_EXTRACTION_PROMPT) == []


def test_extraction_returns_per_field_values():
    fields = extract_fields_from_image(_blank_image(), transport=_mock_transport())
    assert fields == VisionExtractedFields(
        patient_name="Eleanor Marsh",
        icd_codes=["Z96.641", "I10"],
        member_id="1EG4TE5MK73",
        member_id_payer="Medicare",
        npi="1234567893",
        extraction_path=EXTRACTION_PATH_VISION,
    )


def test_fenced_json_response_is_parsed():
    fields = parse_vision_response(f"```json\n{SAMPLE_RESPONSE}\n```")
    assert fields.patient_name == "Eleanor Marsh"


def test_missing_fields_default_to_empty():
    fields = parse_vision_response(
        '{"patient_name": null, "icd_codes": [], "member_id": null, "npi": null}'
    )
    assert fields == VisionExtractedFields()


def test_non_json_response_raises():
    with pytest.raises(VisionExtractionError):
        parse_vision_response("The patient appears to be Eleanor Marsh.")


def test_only_image_pages_route_to_vision():
    pages = [
        IngestedPage(1, PAGE_TYPE_DIGITAL_TEXT, "Patient: A", None, ()),
        IngestedPage(2, PAGE_TYPE_SCANNED_IMAGE, "", _blank_image(), ()),
    ]
    results = extract_image_page_fields(pages, transport=_mock_transport())
    assert list(results) == [2]
    assert results[2].extraction_path == EXTRACTION_PATH_VISION


def test_scanned_sample_page_yields_structured_output():
    """Sample scanned fax REF-1003: image pages produce non-empty structured
    output through the (mocked) vision transport."""
    pages = ingest_document(SCANNED_PDF)
    image_pages = [p for p in pages if p.page_type == PAGE_TYPE_SCANNED_IMAGE]
    assert image_pages, "sample fax must contain scanned-image pages"
    results = extract_image_page_fields(pages, transport=_mock_transport())
    assert set(results) == {p.page_number for p in image_pages}
    for fields in results.values():
        assert fields.patient_name
        assert fields.icd_codes
