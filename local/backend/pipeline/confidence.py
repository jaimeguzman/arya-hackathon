"""Layer 7 — confidence scoring + GuardrailService routing."""

from __future__ import annotations

from typing import Any

from backend.services.guardrail_service import GuardrailService

BASE_RULES = 0.85
BASE_VISION = 0.65


def score_fields(
    pages: list[dict[str, Any]],
    *,
    correction_meta: dict[str, Any] | None = None,
    cross_issues: list[dict[str, Any]] | None = None,
    guardrails: GuardrailService | None = None,
) -> tuple[dict[str, Any], dict[str, float], dict[str, str]]:
    gs = guardrails or GuardrailService()
    correction_meta = correction_meta or {}
    cross_issues = cross_issues or []

    # merge fields preferring longer / first non-empty
    merged: dict[str, Any] = {}
    path_for: dict[str, str] = {}
    page_hits: dict[str, int] = {}

    for p in pages:
        if p.get("classification") == "cover_sheet":
            continue
        path = p.get("extraction_path") or "vision"
        for k, v in (p.get("normalized") or {}).items():
            if v in (None, "", []):
                continue
            page_hits[k] = page_hits.get(k, 0) + 1
            if k not in merged:
                merged[k] = v
                path_for[k] = path
            elif isinstance(v, str) and isinstance(merged[k], str) and len(v) > len(merged[k]):
                merged[k] = v

    confirmed = {i["field"] for i in cross_issues if i.get("assessment") == "same_person_name_variant"}
    conflicts = {
        i["field"]
        for i in cross_issues
        if i.get("assessment") == "genuine_conflict" and i.get("recommended_resolution")
    }

    scores: dict[str, float] = {}
    routing: dict[str, str] = {}
    for field, value in merged.items():
        score = BASE_RULES if path_for.get(field) == "rules" else BASE_VISION
        meta = correction_meta.get(field) or {}
        if meta.get("accepted"):
            if meta.get("flagged") or meta.get("band") == "FLAG":
                score -= 0.25
            else:
                score -= 0.1
            if int(meta.get("attempts") or 1) >= 2:
                score -= 0.1
        if page_hits.get(field, 0) >= 2 or field in confirmed:
            score += 0.1
        if field in conflicts:
            score -= 0.1
        score = max(0.0, min(1.0, score))
        scores[field] = round(score, 4)
        routing[field] = gs.check_confidence(field, score)

    # drop REJECT from merged for intake auto-write (still keep in scores)
    return merged, scores, routing
