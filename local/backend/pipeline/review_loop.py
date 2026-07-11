"""Layer 5 — agentic review loop."""

from __future__ import annotations

from typing import Any

from backend.agents.correction_agent import correct_field
from backend.agents.cross_reference_agent import cross_reference
from backend.agents.validation_agent import validate_fields
from backend.services.guardrail_service import GuardrailService


def run_review_loop(
    pages: list[dict[str, Any]],
    gemini,
    guardrails: GuardrailService | None = None,
    *,
    known_icds: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    gs = guardrails or GuardrailService()
    gaps: list[dict[str, Any]] = []
    correction_meta: dict[str, Any] = {}

    for p in pages:
        if p.get("classification") == "cover_sheet":
            continue
        fields = dict(p.get("normalized") or {})
        results = validate_fields(fields, known_icds=known_icds)
        p["validation_errors"] = [r for r in results if not r["valid"]]
        for err in p["validation_errors"]:
            fix = correct_field(
                err["field"],
                err["extracted_value"],
                err.get("error") or "",
                gemini,
                gs,
                context=p.get("raw_text") or "",
            )
            correction_meta[err["field"]] = fix
            if fix.get("accepted") and fix.get("corrected_value") is not None:
                fields[err["field"]] = fix["corrected_value"]
                if fix.get("flagged"):
                    gaps.append(
                        {
                            "field_name": err["field"],
                            "reason": "correction flagged for review",
                            "priority": "medium",
                            "suggested_action": "Human review corrected value",
                        }
                    )
            else:
                gaps.append(
                    {
                        "field_name": err["field"],
                        "reason": err.get("error") or "validation failed",
                        "priority": "high",
                        "suggested_action": "Verify on phone call",
                    }
                )
        p["normalized"] = fields

    issues = cross_reference(pages)
    for issue in issues:
        if issue.get("assessment") == "same_person_name_variant" and issue.get(
            "recommended_resolution"
        ):
            for p in pages:
                if "patient_name" in (p.get("normalized") or {}):
                    p["normalized"]["patient_name"] = issue["recommended_resolution"]
        elif issue.get("recommended_resolution") is None:
            gaps.append(
                {
                    "field_name": issue["field"],
                    "reason": "unresolved cross-page conflict",
                    "priority": "high",
                    "suggested_action": "Keep both values; human review",
                }
            )
    return pages, gaps, issues
