"""Layer 5 — Correction Agent.

Second agent of the agentic review loop: reasons about each
`ValidationFailure` from the Validation Agent and decides, with a
confidence tier, what to do about it:

- HIGH   -> auto-correct. A single OCR-confusion substitution yields
            exactly one value that passes the failed rule
            (e.g. ICD-10 "M17.1I" -> "M17.11").
- MEDIUM -> apply the correction but flag it for review. Format-only
            evidence, no reference table to confirm against
            (e.g. member ID "H12O456789" -> "H120456789", O -> 0).
- LOW    -> uncorrectable. Withhold the value, flag for human review
            and add it to the gap list for the Voice Agent to verify
            (e.g. "Lisinopril 200mg" out of clinical range).

Correction candidates are generated from a fixed OCR character-confusion
table and accepted only when they deterministically pass the same rule
that failed — the agent never invents data.

Spec: app_spec.txt <document_pipeline><layer number="5"> (Correction Agent).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from app.pipeline.extraction_rules import match_member_id_payer
from app.pipeline.validation import (
    ValidationFailure,
    ValidationRecord,
    ValidationReference,
    ValidationReport,
    parse_dosage_mg,
)

# Character pairs commonly confused by OCR, applied one substitution at
# a time in either direction.
OCR_CONFUSION_PAIRS: tuple[tuple[str, str], ...] = (
    ("O", "0"),
    ("I", "1"),
    ("L", "1"),
    ("S", "5"),
    ("B", "8"),
    ("Z", "2"),
    ("G", "6"),
)

_CONFUSION_MAP: dict[str, tuple[str, ...]] = {}
for _a, _b in OCR_CONFUSION_PAIRS:
    _CONFUSION_MAP.setdefault(_a, ())
    _CONFUSION_MAP.setdefault(_b, ())
    _CONFUSION_MAP[_a] += (_b,)
    _CONFUSION_MAP[_b] += (_a,)

_INDEXED_FIELD_PATTERN = re.compile(
    r"^(?P<name>\w+)\[(?P<index>\d+)\](?:\.(?P<attr>\w+))?$"
)


class CorrectionConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CorrectionAction(str, Enum):
    AUTO_CORRECT = "auto_correct"
    APPLY_FLAG_REVIEW = "apply_flag_review"
    HUMAN_REVIEW = "human_review"


@dataclass(frozen=True)
class Correction:
    """The Correction Agent's decision for one validation failure."""

    failure: ValidationFailure
    original_value: str | None
    corrected_value: str | None
    confidence: CorrectionConfidence
    action: CorrectionAction
    reasoning: str


@dataclass(frozen=True)
class GapItem:
    """A follow-up verification task for the Voice Agent."""

    field: str
    original_value: str | None
    reason: str


@dataclass(frozen=True)
class CorrectionReport:
    corrections: tuple[Correction, ...]
    gap_list: tuple[GapItem, ...]

    @property
    def auto_corrected(self) -> tuple[Correction, ...]:
        return tuple(
            c for c in self.corrections if c.action is CorrectionAction.AUTO_CORRECT
        )

    @property
    def flagged_for_review(self) -> tuple[Correction, ...]:
        return tuple(
            c
            for c in self.corrections
            if c.action
            in (CorrectionAction.APPLY_FLAG_REVIEW, CorrectionAction.HUMAN_REVIEW)
        )


def ocr_substitution_candidates(value: str) -> tuple[str, ...]:
    """Every value reachable via exactly one OCR-confusion substitution."""
    candidates: dict[str, None] = {}
    for idx, char in enumerate(value):
        for replacement in _CONFUSION_MAP.get(char.upper(), ()):
            replacement = replacement if char.isupper() or char.isdigit() else replacement.lower()
            candidate = value[:idx] + replacement + value[idx + 1 :]
            if candidate != value:
                candidates[candidate] = None
    return tuple(candidates)


def _field_value(record: ValidationRecord, field_path: str) -> str | None:
    """Resolve a ValidationFailure.field path against the record."""
    match = _INDEXED_FIELD_PATTERN.match(field_path)
    if match:
        items = getattr(record, match.group("name"), ())
        index = int(match.group("index"))
        if index >= len(items):
            return None
        item = items[index]
        attr = match.group("attr")
        return getattr(item, attr) if attr else item
    value = getattr(record, field_path, None)
    if value is None:
        return None
    return value if isinstance(value, str) else value.isoformat()


def _correct_icd_code(
    value: str, reference: ValidationReference
) -> tuple[str, ...]:
    return tuple(
        c for c in ocr_substitution_candidates(value) if c in reference.icd10_codes
    )


def _correct_member_id(value: str, payer: str | None) -> tuple[str, ...]:
    matches: list[str] = []
    for candidate in ocr_substitution_candidates(value):
        matched = match_member_id_payer(candidate)
        if matched is not None and (payer is None or matched == payer):
            matches.append(candidate)
    return tuple(matches)


def _low_confidence(
    failure: ValidationFailure, original: str | None, reasoning: str
) -> Correction:
    return Correction(
        failure=failure,
        original_value=original,
        corrected_value=None,
        confidence=CorrectionConfidence.LOW,
        action=CorrectionAction.HUMAN_REVIEW,
        reasoning=reasoning,
    )


def correct_failures(
    record: ValidationRecord,
    report: ValidationReport,
    reference: ValidationReference,
) -> CorrectionReport:
    """Reason about every validation failure and tier the outcome."""
    corrections: list[Correction] = []
    gap_list: list[GapItem] = []

    for failure in report.failures:
        original = _field_value(record, failure.field)

        if failure.rule == "icd10_table_lookup" and original is not None:
            candidates = _correct_icd_code(original, reference)
            if len(candidates) == 1:
                corrections.append(
                    Correction(
                        failure=failure,
                        original_value=original,
                        corrected_value=candidates[0],
                        confidence=CorrectionConfidence.HIGH,
                        action=CorrectionAction.AUTO_CORRECT,
                        reasoning=(
                            f"Single OCR substitution {original!r} -> "
                            f"{candidates[0]!r} matches the ICD-10 reference table"
                        ),
                    )
                )
                continue
            corrections.append(
                _low_confidence(
                    failure,
                    original,
                    f"{len(candidates)} ICD-10 reference matches via OCR "
                    "substitution — cannot correct unambiguously",
                )
            )
            gap_list.append(
                GapItem(
                    field=failure.field,
                    original_value=original,
                    reason="ICD-10 code could not be corrected; verify by voice",
                )
            )
            continue

        if failure.rule == "member_id_payer_format" and original is not None:
            candidates = _correct_member_id(original, record.payer)
            if len(candidates) == 1:
                corrections.append(
                    Correction(
                        failure=failure,
                        original_value=original,
                        corrected_value=candidates[0],
                        confidence=CorrectionConfidence.MEDIUM,
                        action=CorrectionAction.APPLY_FLAG_REVIEW,
                        reasoning=(
                            f"Single OCR substitution {original!r} -> "
                            f"{candidates[0]!r} matches the payer member-ID "
                            "format; format-only evidence, flagged for review"
                        ),
                    )
                )
                continue
            corrections.append(
                _low_confidence(
                    failure,
                    original,
                    f"{len(candidates)} payer-format matches via OCR "
                    "substitution — cannot correct unambiguously",
                )
            )
            gap_list.append(
                GapItem(
                    field=failure.field,
                    original_value=original,
                    reason="Member ID could not be corrected; verify by voice",
                )
            )
            continue

        if failure.rule == "dosage_within_range":
            reasoning = (
                f"Dosage {original!r} cannot be confidently corrected — "
                "clinical value requires human confirmation"
            )
            if original is not None and parse_dosage_mg(original) is None:
                reasoning = (
                    f"Dosage {original!r} is not a parseable mg value — "
                    "requires human confirmation"
                )
            corrections.append(_low_confidence(failure, original, reasoning))
            gap_list.append(
                GapItem(
                    field=failure.field,
                    original_value=original,
                    reason="Medication dosage failed validation; verify by voice",
                )
            )
            continue

        # All remaining rules (DOB, dates, zip, NPI, ...) have no safe
        # deterministic correction — withhold and route to a human.
        corrections.append(
            _low_confidence(
                failure,
                original,
                f"No deterministic correction strategy for rule "
                f"{failure.rule!r} — withheld for human review",
            )
        )
        gap_list.append(
            GapItem(
                field=failure.field,
                original_value=original,
                reason=f"Failed {failure.rule}; verify by voice",
            )
        )

    return CorrectionReport(corrections=tuple(corrections), gap_list=tuple(gap_list))
