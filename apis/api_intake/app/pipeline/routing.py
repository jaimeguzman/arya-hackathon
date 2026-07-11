"""Layer 7 — Confidence Scoring and Routing.

Composes the Layer 3-5 outputs per field into a confidence tier and a
routing decision, per app_spec.txt <document_pipeline><layer number="7">:

- HIGH   (rules + validated + confirmed across documents)
         -> auto-populate the intake record
- MEDIUM (LLM vision + validated, single document)
         -> auto-populate + flag for review
- LOW    (failed validation, uncertain correction)
         -> withhold; add to gap list for the Voice Agent

Deterministic code, no LLM. Field provenance comes from Layer 4
convergence (``extraction_path``), validation status from the Layer 5
Validation/Correction Agents, and cross-document confirmation from the
Layer 5 Cross-Reference Agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.pipeline.correction import (
    Correction,
    CorrectionAction,
    GapItem,
)

RULES_PATH = "rules"
VISION_PATH = "vision"


class ConfidenceTier(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RoutingAction(str, Enum):
    AUTO_POPULATE = "auto_populate"
    AUTO_POPULATE_FLAG_REVIEW = "auto_populate_flag_review"
    WITHHOLD_GAP_LIST = "withhold_gap_list"


_ACTION_PER_TIER: dict[ConfidenceTier, RoutingAction] = {
    ConfidenceTier.HIGH: RoutingAction.AUTO_POPULATE,
    ConfidenceTier.MEDIUM: RoutingAction.AUTO_POPULATE_FLAG_REVIEW,
    ConfidenceTier.LOW: RoutingAction.WITHHOLD_GAP_LIST,
}


@dataclass(frozen=True)
class FieldEvidence:
    """Everything Layer 7 needs to know about one extracted field.

    ``validated`` reflects the field's final validation status after the
    Correction Agent ran: a field whose failure was auto-corrected and
    re-validated is ``validated=True`` with the correction attached.
    """

    field: str
    value: str | None
    extraction_path: str  # RULES_PATH or VISION_PATH
    validated: bool
    cross_confirmed: bool = False  # confirmed across >1 document
    correction: Correction | None = None


@dataclass(frozen=True)
class RoutedField:
    evidence: FieldEvidence
    tier: ConfidenceTier
    action: RoutingAction
    reasoning: str


@dataclass(frozen=True)
class RoutingReport:
    routed: tuple[RoutedField, ...]
    gap_list: tuple[GapItem, ...]

    @property
    def populated(self) -> tuple[RoutedField, ...]:
        return tuple(
            r for r in self.routed if r.action is not RoutingAction.WITHHOLD_GAP_LIST
        )

    @property
    def flagged_for_review(self) -> tuple[RoutedField, ...]:
        return tuple(
            r
            for r in self.routed
            if r.action is RoutingAction.AUTO_POPULATE_FLAG_REVIEW
        )

    @property
    def withheld(self) -> tuple[RoutedField, ...]:
        return tuple(
            r for r in self.routed if r.action is RoutingAction.WITHHOLD_GAP_LIST
        )

    def intake_record(self) -> dict[str, str | None]:
        """The auto-populated intake record: HIGH and MEDIUM fields only.
        LOW fields are withheld entirely."""
        return {r.evidence.field: r.evidence.value for r in self.populated}


def score_field(evidence: FieldEvidence) -> tuple[ConfidenceTier, str]:
    """Assign the confidence tier for one field per the Layer 7 spec."""
    if evidence.extraction_path not in (RULES_PATH, VISION_PATH):
        raise ValueError(
            f"Unknown extraction path: {evidence.extraction_path!r}"
        )

    correction = evidence.correction
    if correction is not None and correction.action is CorrectionAction.HUMAN_REVIEW:
        return (
            ConfidenceTier.LOW,
            "uncertain correction: the Correction Agent could not confidently "
            "correct this field",
        )
    if not evidence.validated:
        return (ConfidenceTier.LOW, "failed validation")
    if (
        evidence.extraction_path == RULES_PATH
        and evidence.cross_confirmed
        and (correction is None or correction.action is CorrectionAction.AUTO_CORRECT)
    ):
        return (
            ConfidenceTier.HIGH,
            "rules extraction, validated, confirmed across documents",
        )
    if evidence.cross_confirmed:
        source = (
            "vision extraction"
            if evidence.extraction_path == VISION_PATH
            else "rules extraction with a review-flagged correction"
        )
        return (
            ConfidenceTier.MEDIUM,
            f"{source}, validated, confirmed across documents",
        )
    return (
        ConfidenceTier.MEDIUM,
        f"{evidence.extraction_path} extraction, validated, single document",
    )


def route_field(evidence: FieldEvidence) -> RoutedField:
    tier, reasoning = score_field(evidence)
    return RoutedField(
        evidence=evidence,
        tier=tier,
        action=_ACTION_PER_TIER[tier],
        reasoning=reasoning,
    )


def route_fields(fields: tuple[FieldEvidence, ...]) -> RoutingReport:
    """Route every field and turn the withheld ones into gap-list rows
    for the Voice Agent to verify."""
    routed = tuple(route_field(evidence) for evidence in fields)
    gap_list = tuple(
        GapItem(
            field=r.evidence.field,
            original_value=r.evidence.value,
            reason=r.reasoning,
        )
        for r in routed
        if r.action is RoutingAction.WITHHOLD_GAP_LIST
    )
    return RoutingReport(routed=routed, gap_list=gap_list)
