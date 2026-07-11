"""Layer 2 — Page classification into document types.

Classifies each ingested page into one of the referral-packet document
types so downstream extractors (Layer 3) know what they are reading.
Fax cover sheets are marked junk and excluded from extraction.

Digital-text pages are classified deterministically by keyword scoring on
their text layer. Scanned-image pages carry no text layer yet, so they are
tagged ``unknown`` here and classified by the vision path in Layer 3.

Spec: app_spec.txt <document_pipeline><layer number="2">.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.pipeline.ingestion import IngestedPage

DOC_TYPE_PHYSICIAN_ORDER = "physician_order"
DOC_TYPE_FACE_TO_FACE_NOTE = "face_to_face_note"
DOC_TYPE_DISCHARGE_SUMMARY = "discharge_summary"
DOC_TYPE_MEDICATION_LIST = "medication_list"
DOC_TYPE_INSURANCE_CARD = "insurance_card"
DOC_TYPE_LAB_RESULTS = "lab_results"
DOC_TYPE_CONSENT_FORM = "consent_form"
DOC_TYPE_FAX_COVER_SHEET = "fax_cover_sheet"
# Scanned pages have no text layer at this stage; the Layer 3 vision path
# resolves their type. Never used for a page with usable text.
DOC_TYPE_UNKNOWN = "unknown"

DOCUMENT_TYPES = (
    DOC_TYPE_PHYSICIAN_ORDER,
    DOC_TYPE_FACE_TO_FACE_NOTE,
    DOC_TYPE_DISCHARGE_SUMMARY,
    DOC_TYPE_MEDICATION_LIST,
    DOC_TYPE_INSURANCE_CARD,
    DOC_TYPE_LAB_RESULTS,
    DOC_TYPE_CONSENT_FORM,
    DOC_TYPE_FAX_COVER_SHEET,
)

JUNK_DOC_TYPES = frozenset({DOC_TYPE_FAX_COVER_SHEET})

# Keyword rules, evaluated case-insensitively against the page text.
# Each hit scores 1; the highest-scoring type wins. On a tie the type
# listed first here wins (more specific types are listed first).
_KEYWORD_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        DOC_TYPE_FAX_COVER_SHEET,
        ("fax cover sheet", "cover sheet", "pages (incl. cover)", "cover page"),
    ),
    (
        DOC_TYPE_FACE_TO_FACE_NOTE,
        ("face-to-face encounter note", "face to face encounter note", "f2f note"),
    ),
    (
        DOC_TYPE_CONSENT_FORM,
        ("consent form", "consent to treat", "patient consent", "authorization to release"),
    ),
    (
        DOC_TYPE_LAB_RESULTS,
        ("lab results", "laboratory results", "lab report", "reference range", "specimen"),
    ),
    (
        DOC_TYPE_MEDICATION_LIST,
        ("medication list", "medication reconciliation", "current medications", "active medications"),
    ),
    (
        DOC_TYPE_INSURANCE_CARD,
        ("insurance card", "member id card", "group number", "rxbin", "rxpcn", "subscriber"),
    ),
    (
        DOC_TYPE_PHYSICIAN_ORDER,
        ("physician orders", "physician order", "ordering physician", "orders signed", "plan of care orders"),
    ),
    (
        DOC_TYPE_DISCHARGE_SUMMARY,
        ("discharge summary", "discharge planning", "discharge date", "patient referral", "clinical summary"),
    ),
)


@dataclass
class ClassifiedPage:
    """One page tagged with its document type (Layer 2 output)."""

    page: IngestedPage
    doc_type: str
    is_junk: bool


def classify_page(page: IngestedPage) -> ClassifiedPage:
    """Classify a single ingested page by keyword scoring on its text."""
    text = page.text.lower()
    if not text.strip():
        return ClassifiedPage(page=page, doc_type=DOC_TYPE_UNKNOWN, is_junk=False)

    best_type = DOC_TYPE_UNKNOWN
    best_score = 0
    for doc_type, keywords in _KEYWORD_RULES:
        score = sum(1 for keyword in keywords if keyword in text)
        if score > best_score:
            best_type = doc_type
            best_score = score
    return ClassifiedPage(
        page=page,
        doc_type=best_type,
        is_junk=best_type in JUNK_DOC_TYPES,
    )


def classify_pages(pages: list[IngestedPage]) -> list[ClassifiedPage]:
    """Classify every page of an ingested document, in page order."""
    return [classify_page(page) for page in pages]


def pages_for_extraction(classified: list[ClassifiedPage]) -> list[ClassifiedPage]:
    """Pages Layer 3 should extract from — junk (cover sheets) excluded."""
    return [entry for entry in classified if not entry.is_junk]
