"""Layer 4 — Entity Extraction convergence.

Both Layer 3 paths (Path B rules, Path C vision) converge here into one
standardized raw-JSON structure per page. Every field carries a value plus
the ``extraction_path`` ("rules" or "vision") that produced it, so Layer 5
agents can reason about provenance per field.

Spec: app_spec.txt <document_pipeline><layer number="4">.
"""

from __future__ import annotations

from typing import Any

from app.pipeline.extraction_rules import RuleExtractedFields
from app.pipeline.extraction_vision import VisionExtractedFields

# The one schema both paths normalize to. Order defines the canonical
# raw-JSON key order per page.
CONVERGED_FIELD_NAMES: tuple[str, ...] = (
    "patient_name",
    "icd_codes",
    "member_id",
    "member_id_payer",
    "npi",
)


def normalize_page_fields(
    fields: RuleExtractedFields | VisionExtractedFields,
) -> dict[str, dict[str, Any]]:
    """Normalize one page's extracted fields into the standardized raw JSON.

    Returns ``{field_name: {"value": ..., "extraction_path": "rules"|"vision"}}``
    with exactly the keys in ``CONVERGED_FIELD_NAMES`` regardless of which
    Layer 3 path produced the input.
    """
    return {
        name: {
            "value": getattr(fields, name),
            "extraction_path": fields.extraction_path,
        }
        for name in CONVERGED_FIELD_NAMES
    }


def converge_document(
    rule_results: dict[int, RuleExtractedFields],
    vision_results: dict[int, VisionExtractedFields],
) -> dict[int, dict[str, dict[str, Any]]]:
    """Merge both paths' per-page results into one raw-JSON map per document.

    Each page was routed to exactly one path by Layer 2 classification; a
    page appearing in both inputs is a routing bug, so it raises.
    """
    overlap = rule_results.keys() & vision_results.keys()
    if overlap:
        raise ValueError(
            f"Pages routed to both extraction paths: {sorted(overlap)}"
        )
    converged = {
        page_number: normalize_page_fields(fields)
        for page_number, fields in {**rule_results, **vision_results}.items()
    }
    return dict(sorted(converged.items()))
