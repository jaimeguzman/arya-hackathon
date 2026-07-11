"""Layer 3 Path B — rule-based extraction for digital-text PDFs.

Docling parses the PDF text layer, then deterministic regex/keyword rules
extract the referral fields the intake record needs:
- patient name (after "Patient:" / "Name:" labels),
- ICD codes (letter + digits, optional dotted extension),
- insurance member IDs matched against payer-specific formats,
- physician NPI (always 10 digits).

Deterministic, fast, reliable — no LLM involved on this path.

Spec: app_spec.txt <document_pipeline><layer number="3"> (Path B).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

EXTRACTION_PATH_RULES = "rules"

# Patient name appears after a "Patient:" or "Name:" label at line start.
_PATIENT_NAME_PATTERN = re.compile(
    r"^\s*(?:Patient|Name)\s*:\s*(?P<name>[^\n]+?)\s*$", re.MULTILINE
)

# ICD-10 code: one letter (not U, reserved) + two digits + optional dotted
# alphanumeric extension, e.g. I10, Z96.641, M17.11.
_ICD_CODE_PATTERN = re.compile(r"\b[A-TV-Z]\d{2}(?:\.[A-Z0-9]{1,4})?\b")

# NPI is always exactly 10 digits; prefer the labeled form to avoid
# grabbing phone numbers or member IDs.
_NPI_LABELED_PATTERN = re.compile(r"\bNPI\s*:?\s*(?P<npi>\d{10})\b")

# Member ID labeled line, validated afterwards against payer formats.
_MEMBER_ID_LABELED_PATTERN = re.compile(
    r"\bMember\s*ID\s*:?\s*(?P<member_id>[A-Z0-9-]{6,15})\b", re.IGNORECASE
)

# Payer-specific member ID formats (payers from data/reference/
# payer_coverage_rules.json). Order matters: most specific first.
PAYER_MEMBER_ID_FORMATS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Medicare MBI: 11 chars, e.g. 1EG4TE5MK73
    # digit(1-9), letter, alnum, digit, letter, alnum, digit, 2 letters, 2 digits
    (
        "Medicare",
        re.compile(
            r"^[1-9][A-HJ-NP-TV-Z][A-HJ-NP-TV-Z0-9]\d"
            r"[A-HJ-NP-TV-Z][A-HJ-NP-TV-Z0-9]\d[A-HJ-NP-TV-Z]{2}\d{2}$"
        ),
    ),
    # Humana: 'H' followed by 9 digits, e.g. H120456789
    ("Humana", re.compile(r"^H\d{9}$")),
    # Aetna: 'A' + 9 alphanumerics (10 total), e.g. AE7O91234X
    ("Aetna", re.compile(r"^A[A-Z0-9]{9}$")),
    # UnitedHealthcare: 9 digits
    ("UnitedHealthcare", re.compile(r"^\d{9}$")),
    # State Medicaid: 8 digits + 2 letters (state CIN style)
    ("State Medicaid", re.compile(r"^\d{8}[A-Z]{2}$")),
)


@dataclass
class RuleExtractedFields:
    """Fields extracted from one page by the rules path (Layer 3 Path B)."""

    patient_name: str | None = None
    icd_codes: list[str] = field(default_factory=list)
    member_id: str | None = None
    member_id_payer: str | None = None  # payer whose format the ID matched
    npi: str | None = None
    extraction_path: str = EXTRACTION_PATH_RULES


def match_member_id_payer(candidate: str) -> str | None:
    """Return the payer whose member ID format the candidate matches."""
    normalized = candidate.strip().upper()
    for payer, pattern in PAYER_MEMBER_ID_FORMATS:
        if pattern.match(normalized):
            return payer
    return None


def extract_patient_name(text: str) -> str | None:
    """Patient name from the first 'Patient:'/'Name:' labeled line."""
    match = _PATIENT_NAME_PATTERN.search(text)
    return match.group("name") if match else None


def extract_icd_codes(text: str) -> list[str]:
    """All ICD-pattern codes in the text, in order, deduplicated."""
    seen: dict[str, None] = {}
    for code in _ICD_CODE_PATTERN.findall(text):
        seen.setdefault(code)
    return list(seen)


def extract_npi(text: str) -> str | None:
    """NPI from a labeled 'NPI:' line (always exactly 10 digits)."""
    match = _NPI_LABELED_PATTERN.search(text)
    return match.group("npi") if match else None


def extract_member_id(text: str) -> tuple[str | None, str | None]:
    """(member_id, matched_payer) from a labeled 'Member ID:' line.

    The ID is kept even when it matches no known payer format — Layer 5
    validation flags format mismatches; extraction only reports them.
    """
    match = _MEMBER_ID_LABELED_PATTERN.search(text)
    if not match:
        return None, None
    member_id = match.group("member_id").upper()
    return member_id, match_member_id_payer(member_id)


def extract_fields(text: str) -> RuleExtractedFields:
    """Run every rule over one page's text layer."""
    member_id, member_id_payer = extract_member_id(text)
    return RuleExtractedFields(
        patient_name=extract_patient_name(text),
        icd_codes=extract_icd_codes(text),
        member_id=member_id,
        member_id_payer=member_id_payer,
        npi=extract_npi(text),
    )


def parse_text_layer(path: str | Path) -> list[str]:
    """Parse a digital PDF's text layer per page using Docling.

    Uses Docling's parse backend directly (no ML pipeline, no model
    downloads) — appropriate for Path B's clean digital-text PDFs.
    """
    # Imported lazily: docling pulls in heavy optional dependencies that
    # the rest of the pipeline does not need at import time.
    from docling.backend.docling_parse_backend import (
        DoclingParseDocumentBackend,
    )
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.document import InputDocument

    source = Path(path)
    in_doc = InputDocument(
        path_or_stream=source,
        format=InputFormat.PDF,
        backend=DoclingParseDocumentBackend,
    )
    backend = DoclingParseDocumentBackend(in_doc, source)
    try:
        pages: list[str] = []
        for index in range(backend.page_count()):
            page = backend.load_page(index)
            try:
                cells = page.get_text_cells()
                pages.append("\n".join(cell.text for cell in cells))
            finally:
                page.unload()
        return pages
    finally:
        backend.unload()


def extract_document_fields(path: str | Path) -> list[RuleExtractedFields]:
    """Docling-parse a digital PDF and rule-extract fields per page."""
    return [extract_fields(page_text) for page_text in parse_text_layer(path)]
