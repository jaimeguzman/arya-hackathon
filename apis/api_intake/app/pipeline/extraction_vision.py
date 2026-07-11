"""Layer 3 Path C — Gemini vision extraction for messy image pages.

Scanned/handwritten pages (no usable text layer) route to the Gemini Flash
vision model, which extracts the referral fields directly from the page
image. Every call goes through the single tokenizing LLM wrapper
(`app.safety.llm_gateway.call_llm`) so the outgoing prompt is scanned for
raw identifiers before anything leaves the backend; the page image itself
is bound into the transport, keeping `call_llm` the only sanctioned entry
point. The transport is injectable, so tests and CI run fully mocked.

Spec: app_spec.txt <document_pipeline><layer number="3"> (Path C).
"""

from __future__ import annotations

import io
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from PIL import Image

from app.pipeline.extraction_rules import match_member_id_payer
from app.pipeline.ingestion import PAGE_TYPE_SCANNED_IMAGE, IngestedPage
from app.safety.llm_gateway import call_llm, make_vision_transport

EXTRACTION_PATH_VISION = "vision"

VISION_MODEL = "gemini-2.0-flash"

# The prompt names the fields the vision model must read off the page.
# It contains no patient data — identifiers only ever appear in the model's
# RESPONSE, which stays inside the backend.
VISION_EXTRACTION_PROMPT = (
    "You are reading one page of a faxed home-health referral document "
    "(possibly handwritten, angled, or smudged). Extract these fields from "
    "the page image and answer with a single JSON object, no prose:\n"
    '{"patient_name": string or null, '
    '"icd_codes": array of ICD-10 code strings, '
    '"member_id": string or null, '
    '"npi": string of exactly 10 digits or null}\n'
    "Use null (or an empty array) for anything not present on the page."
)

# Vision responses often arrive fenced: ```json ... ```
_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(?P<body>.*?)\s*```", re.DOTALL)


class VisionExtractionError(RuntimeError):
    """Raised when the vision model's response is not usable JSON."""


@dataclass
class VisionExtractedFields:
    """Fields extracted from one page by the vision path (Layer 3 Path C)."""

    patient_name: str | None = None
    icd_codes: list[str] = field(default_factory=list)
    member_id: str | None = None
    member_id_payer: str | None = None  # payer whose format the ID matched
    npi: str | None = None
    extraction_path: str = EXTRACTION_PATH_VISION


def _encode_image_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _default_vision_transport(image: Image.Image) -> Callable[[str], str]:
    """Bind the page image into a gateway transport (SDK lives in the
    safety layer's `make_vision_transport` — the single sanctioned site)."""
    return make_vision_transport(_encode_image_png(image), model=VISION_MODEL)


def parse_vision_response(raw: str) -> VisionExtractedFields:
    """Parse the vision model's JSON reply into structured fields."""
    body = raw.strip()
    fence = _JSON_FENCE_PATTERN.search(body)
    if fence:
        body = fence.group("body")
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise VisionExtractionError(
            f"Vision response is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise VisionExtractionError("Vision response JSON is not an object.")

    member_id_raw = data.get("member_id")
    member_id = str(member_id_raw).strip().upper() if member_id_raw else None
    icd_codes_raw = data.get("icd_codes") or []
    if not isinstance(icd_codes_raw, list):
        raise VisionExtractionError("Vision response 'icd_codes' is not a list.")
    patient_name_raw = data.get("patient_name")
    npi_raw = data.get("npi")
    return VisionExtractedFields(
        patient_name=str(patient_name_raw).strip() if patient_name_raw else None,
        icd_codes=[str(code).strip().upper() for code in icd_codes_raw if code],
        member_id=member_id,
        member_id_payer=match_member_id_payer(member_id) if member_id else None,
        npi=str(npi_raw).strip() if npi_raw else None,
    )


def extract_fields_from_image(
    image: Image.Image,
    transport: Callable[[str], str] | None = None,
) -> VisionExtractedFields:
    """Run one page image through the vision extractor via the safety gateway.

    `transport` is injectable for tests/CI; when omitted the real Gemini
    vision transport is used, with the image bound in.
    """
    response = call_llm(
        VISION_EXTRACTION_PROMPT,
        transport=transport or _default_vision_transport(image),
    )
    return parse_vision_response(response)


def extract_image_page_fields(
    pages: list[IngestedPage],
    transport: Callable[[str], str] | None = None,
) -> dict[int, VisionExtractedFields]:
    """Route every scanned-image page to the vision extractor.

    Returns {page_number: fields} for the image pages only; digital-text
    pages belong to the rules path (Path B) and are skipped here.
    """
    results: dict[int, VisionExtractedFields] = {}
    for page in pages:
        if page.page_type != PAGE_TYPE_SCANNED_IMAGE or page.image is None:
            continue
        results[page.page_number] = extract_fields_from_image(
            page.image, transport=transport
        )
    return results
