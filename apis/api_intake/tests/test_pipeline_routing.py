"""Layer 7 — Confidence scoring and routing tests (feature #37).

Spec: app_spec.txt <document_pipeline><layer number="7">.
"""

from __future__ import annotations

import pytest

from app.pipeline.correction import (
    Correction,
    CorrectionAction,
    CorrectionConfidence,
)
from app.pipeline.routing import (
    ConfidenceTier,
    FieldEvidence,
    RoutingAction,
    route_field,
    route_fields,
)
from app.pipeline.validation import ValidationFailure


def _correction(action: CorrectionAction, confidence: CorrectionConfidence) -> Correction:
    return Correction(
        failure=ValidationFailure(
            field="icd_codes", rule="icd10_known_code", message="unknown code"
        ),
        original_value="M17.1I",
        corrected_value="M17.11" if action is CorrectionAction.AUTO_CORRECT else None,
        confidence=confidence,
        action=action,
        reasoning="test",
    )


def test_high_rules_validated_cross_confirmed_auto_populates() -> None:
    routed = route_field(
        FieldEvidence(
            field="patient_name",
            value="Margaret Chen",
            extraction_path="rules",
            validated=True,
            cross_confirmed=True,
        )
    )
    assert routed.tier is ConfidenceTier.HIGH
    assert routed.action is RoutingAction.AUTO_POPULATE


def test_medium_vision_validated_single_document_flags_for_review() -> None:
    routed = route_field(
        FieldEvidence(
            field="member_id",
            value="XYZ123456789",
            extraction_path="vision",
            validated=True,
            cross_confirmed=False,
        )
    )
    assert routed.tier is ConfidenceTier.MEDIUM
    assert routed.action is RoutingAction.AUTO_POPULATE_FLAG_REVIEW


def test_low_failed_validation_is_withheld_and_gap_listed() -> None:
    report = route_fields(
        (
            FieldEvidence(
                field="npi",
                value="1234567890",
                extraction_path="rules",
                validated=False,
            ),
        )
    )
    (routed,) = report.routed
    assert routed.tier is ConfidenceTier.LOW
    assert routed.action is RoutingAction.WITHHOLD_GAP_LIST
    (gap,) = report.gap_list
    assert gap.field == "npi"
    assert gap.original_value == "1234567890"
    assert report.intake_record() == {}


def test_low_uncertain_correction_even_if_marked_validated() -> None:
    routed = route_field(
        FieldEvidence(
            field="icd_codes",
            value="H12O456789",
            extraction_path="rules",
            validated=True,
            cross_confirmed=True,
            correction=_correction(
                CorrectionAction.HUMAN_REVIEW, CorrectionConfidence.LOW
            ),
        )
    )
    assert routed.tier is ConfidenceTier.LOW
    assert routed.action is RoutingAction.WITHHOLD_GAP_LIST
    assert "uncertain correction" in routed.reasoning


def test_auto_corrected_field_still_reaches_high() -> None:
    routed = route_field(
        FieldEvidence(
            field="icd_codes",
            value="M17.11",
            extraction_path="rules",
            validated=True,
            cross_confirmed=True,
            correction=_correction(
                CorrectionAction.AUTO_CORRECT, CorrectionConfidence.HIGH
            ),
        )
    )
    assert routed.tier is ConfidenceTier.HIGH


def test_review_flagged_correction_caps_tier_at_medium() -> None:
    routed = route_field(
        FieldEvidence(
            field="member_id",
            value="XYZ103456789",
            extraction_path="rules",
            validated=True,
            cross_confirmed=True,
            correction=_correction(
                CorrectionAction.APPLY_FLAG_REVIEW, CorrectionConfidence.MEDIUM
            ),
        )
    )
    assert routed.tier is ConfidenceTier.MEDIUM
    assert routed.action is RoutingAction.AUTO_POPULATE_FLAG_REVIEW


def test_rules_validated_but_single_document_is_medium() -> None:
    routed = route_field(
        FieldEvidence(
            field="patient_name",
            value="Margaret Chen",
            extraction_path="rules",
            validated=True,
            cross_confirmed=False,
        )
    )
    assert routed.tier is ConfidenceTier.MEDIUM


def test_intake_record_contains_high_and_medium_only() -> None:
    report = route_fields(
        (
            FieldEvidence(
                field="patient_name",
                value="Margaret Chen",
                extraction_path="rules",
                validated=True,
                cross_confirmed=True,
            ),
            FieldEvidence(
                field="member_id",
                value="XYZ123456789",
                extraction_path="vision",
                validated=True,
            ),
            FieldEvidence(
                field="npi",
                value="1234567890",
                extraction_path="rules",
                validated=False,
            ),
        )
    )
    assert report.intake_record() == {
        "patient_name": "Margaret Chen",
        "member_id": "XYZ123456789",
    }
    assert [r.evidence.field for r in report.flagged_for_review] == ["member_id"]
    assert [r.evidence.field for r in report.withheld] == ["npi"]


def test_unknown_extraction_path_raises() -> None:
    with pytest.raises(ValueError):
        route_field(
            FieldEvidence(
                field="npi",
                value="1234567890",
                extraction_path="ocr",
                validated=True,
            )
        )
