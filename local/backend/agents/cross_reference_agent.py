"""Cross-reference agent — multi-page consistency."""

from __future__ import annotations

from typing import Any


def cross_reference(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare key fields across pages; return inconsistency list."""
    issues: list[dict[str, Any]] = []
    by_field: dict[str, list[tuple[int, Any]]] = {}
    for p in pages:
        if p.get("classification") == "cover_sheet":
            continue
        norm = p.get("normalized") or {}
        for k, v in norm.items():
            if v in (None, "", [], {}):
                continue
            by_field.setdefault(k, []).append((p["page_number"], v))

    for field, vals in by_field.items():
        unique = []
        for _, v in vals:
            if v not in unique:
                unique.append(v)
        if len(unique) <= 1:
            continue
        # name variants: keep more complete
        if field == "patient_name":
            best = max((str(u) for u in unique), key=len)
            issues.append(
                {
                    "field": field,
                    "values": [{"page": pg, "value": v} for pg, v in vals],
                    "assessment": "same_person_name_variant",
                    "recommended_resolution": best,
                    "confidence": 0.7,
                }
            )
            continue
        issues.append(
            {
                "field": field,
                "values": [{"page": pg, "value": v} for pg, v in vals],
                "assessment": "genuine_conflict",
                "recommended_resolution": None,
                "confidence": 0.4,
            }
        )
    return issues
