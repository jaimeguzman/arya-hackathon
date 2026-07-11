"""Layer 5 — Cross-Reference Agent: consistency across pages/documents.

Third agent of the Layer 5 review loop (after Validation and Correction).
Checks that the referral packet is internally consistent:
- Same patient name and DOB across every document in the packet
- Diagnosis text agrees with the ICD-10 code next to it
  (descriptions from data/reference/icd10_top30_home_health.json)
- Medication list is consistent with the diagnoses — a medication with a
  hard indication requirement (e.g. Warfarin) with no supporting ICD code
  anywhere in the packet is flagged for clinical review
  (rules from data/reference/medication_indication_rules.json)

Every inconsistency is a `CrossReferenceFlag`; clinical flags route to
human clinical review, identity/coding flags feed the gap list. All checks
are deterministic code, never LLM-decided.

Spec: app_spec.txt <document_pipeline><layer number="5"> (Cross-Reference
Agent).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path

from app.config import get_settings

ICD10_FILE = "icd10_top30_home_health.json"
INDICATION_RULES_FILE = "medication_indication_rules.json"

# Words too generic to establish agreement between diagnosis text and an
# ICD-10 description (articles, qualifiers CMS uses on most descriptions).
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "in",
        "not",
        "of",
        "on",
        "or",
        "other",
        "primary",
        "site",
        "specified",
        "the",
        "to",
        "type",
        "unspecified",
        "with",
        "without",
    }
)

_WORD_PATTERN = re.compile(r"[a-z0-9]+")


class CrossReferenceRule(str, Enum):
    PATIENT_NAME_MISMATCH = "patient_name_mismatch"
    PATIENT_DOB_MISMATCH = "patient_dob_mismatch"
    DIAGNOSIS_CODE_MISMATCH = "diagnosis_code_mismatch"
    MEDICATION_WITHOUT_INDICATION = "medication_without_indication"


class CrossReferenceRouting(str, Enum):
    """Where a flag goes: clinical inconsistencies need a clinician's eye,
    identity/coding inconsistencies feed the gap list for verification."""

    CLINICAL_REVIEW = "clinical_review"
    VERIFICATION = "verification"


@dataclass(frozen=True)
class Diagnosis:
    """A diagnosis as extracted from one document: free text and/or code."""

    text: str | None = None
    icd_code: str | None = None


@dataclass(frozen=True)
class CrossRefDocument:
    """The cross-checkable fields of one document in the referral packet."""

    document_id: str
    patient_name: str | None = None
    date_of_birth: date | None = None
    diagnoses: tuple[Diagnosis, ...] = ()
    medications: tuple[str, ...] = ()


@dataclass(frozen=True)
class CrossReferenceFlag:
    """One inconsistency found across the packet."""

    rule: CrossReferenceRule
    routing: CrossReferenceRouting
    documents: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class CrossReferenceReport:
    flags: tuple[CrossReferenceFlag, ...]
    checks_run: tuple[str, ...]

    @property
    def is_consistent(self) -> bool:
        return not self.flags

    @property
    def clinical_review_flags(self) -> tuple[CrossReferenceFlag, ...]:
        return tuple(
            f
            for f in self.flags
            if f.routing is CrossReferenceRouting.CLINICAL_REVIEW
        )


@dataclass(frozen=True)
class IndicationRule:
    medication: str  # lowercased
    indication: str
    icd_prefixes: tuple[str, ...]


@dataclass(frozen=True)
class CrossReferenceReference:
    # ICD-10 code -> official description
    icd10_descriptions: dict[str, str] = field(hash=False)
    indication_rules: tuple[IndicationRule, ...] = ()


def load_cross_reference_reference(data_dir: str | Path) -> CrossReferenceReference:
    base = Path(data_dir)

    def _load(name: str) -> dict:
        path = base / name
        if not path.is_file():
            raise FileNotFoundError(f"Required reference data file missing: {path}")
        with path.open() as fh:
            return json.load(fh)

    icd_doc = _load(ICD10_FILE)
    rules_doc = _load(INDICATION_RULES_FILE)
    return CrossReferenceReference(
        icd10_descriptions={
            entry["code"]: entry["description"] for entry in icd_doc["codes"]
        },
        indication_rules=tuple(
            IndicationRule(
                medication=entry["name"].lower(),
                indication=entry["indication"],
                icd_prefixes=tuple(entry["icd_prefixes"]),
            )
            for entry in rules_doc["medications"]
        ),
    )


def get_cross_reference_reference() -> CrossReferenceReference:
    settings = get_settings()
    if not settings.reference_data_dir:
        raise RuntimeError(
            "REFERENCE_DATA_DIR is not set — the Cross-Reference Agent cannot "
            "run without the reference tables."
        )
    return load_cross_reference_reference(settings.reference_data_dir)


def normalize_patient_name(name: str) -> str:
    """Order-insensitive name key so 'Doe, John' matches 'John Doe'."""
    return " ".join(sorted(_WORD_PATTERN.findall(name.lower())))


def _content_words(text: str) -> frozenset[str]:
    return frozenset(_WORD_PATTERN.findall(text.lower())) - _STOPWORDS


def diagnosis_matches_description(diagnosis_text: str, description: str) -> bool:
    """Deterministic agreement check: the extracted diagnosis text must
    share at least one content word with the official ICD description."""
    return bool(_content_words(diagnosis_text) & _content_words(description))


def _check_identity(
    documents: tuple[CrossRefDocument, ...],
    flags: list[CrossReferenceFlag],
    checks_run: list[str],
) -> None:
    named = [d for d in documents if d.patient_name]
    if len(named) > 1:
        checks_run.append(CrossReferenceRule.PATIENT_NAME_MISMATCH.value)
        distinct = {normalize_patient_name(d.patient_name) for d in named}
        if len(distinct) > 1:
            flags.append(
                CrossReferenceFlag(
                    rule=CrossReferenceRule.PATIENT_NAME_MISMATCH,
                    routing=CrossReferenceRouting.VERIFICATION,
                    documents=tuple(d.document_id for d in named),
                    message="Patient name differs across documents: "
                    + "; ".join(
                        f"{d.document_id}={d.patient_name!r}" for d in named
                    ),
                )
            )

    dated = [d for d in documents if d.date_of_birth]
    if len(dated) > 1:
        checks_run.append(CrossReferenceRule.PATIENT_DOB_MISMATCH.value)
        if len({d.date_of_birth for d in dated}) > 1:
            flags.append(
                CrossReferenceFlag(
                    rule=CrossReferenceRule.PATIENT_DOB_MISMATCH,
                    routing=CrossReferenceRouting.VERIFICATION,
                    documents=tuple(d.document_id for d in dated),
                    message="Patient date of birth differs across documents: "
                    + "; ".join(
                        f"{d.document_id}={d.date_of_birth.isoformat()}"
                        for d in dated
                    ),
                )
            )


def _check_diagnosis_codes(
    documents: tuple[CrossRefDocument, ...],
    reference: CrossReferenceReference,
    flags: list[CrossReferenceFlag],
    checks_run: list[str],
) -> None:
    for doc in documents:
        for diagnosis in doc.diagnoses:
            if not (diagnosis.text and diagnosis.icd_code):
                continue
            description = reference.icd10_descriptions.get(diagnosis.icd_code)
            if description is None:
                # Unknown codes are the Validation Agent's finding, not ours.
                continue
            checks_run.append(CrossReferenceRule.DIAGNOSIS_CODE_MISMATCH.value)
            if not diagnosis_matches_description(diagnosis.text, description):
                flags.append(
                    CrossReferenceFlag(
                        rule=CrossReferenceRule.DIAGNOSIS_CODE_MISMATCH,
                        routing=CrossReferenceRouting.VERIFICATION,
                        documents=(doc.document_id,),
                        message=(
                            f"Diagnosis text {diagnosis.text!r} does not match "
                            f"ICD-10 {diagnosis.icd_code} "
                            f"({description!r})"
                        ),
                    )
                )


def _check_medication_indications(
    documents: tuple[CrossRefDocument, ...],
    reference: CrossReferenceReference,
    flags: list[CrossReferenceFlag],
    checks_run: list[str],
) -> None:
    packet_codes = tuple(
        d.icd_code
        for doc in documents
        for d in doc.diagnoses
        if d.icd_code
    )
    rules_by_name = {r.medication: r for r in reference.indication_rules}
    for doc in documents:
        for medication in doc.medications:
            rule = rules_by_name.get(medication.lower())
            if rule is None:
                continue
            checks_run.append(
                CrossReferenceRule.MEDICATION_WITHOUT_INDICATION.value
            )
            supported = any(
                code.startswith(prefix)
                for code in packet_codes
                for prefix in rule.icd_prefixes
            )
            if not supported:
                flags.append(
                    CrossReferenceFlag(
                        rule=CrossReferenceRule.MEDICATION_WITHOUT_INDICATION,
                        routing=CrossReferenceRouting.CLINICAL_REVIEW,
                        documents=(doc.document_id,),
                        message=(
                            f"{medication} listed with no {rule.indication} "
                            "indication anywhere in the packet — flag for "
                            "clinical review"
                        ),
                    )
                )


def cross_reference_documents(
    documents: tuple[CrossRefDocument, ...] | list[CrossRefDocument],
    reference: CrossReferenceReference,
) -> CrossReferenceReport:
    """Run every applicable cross-document consistency check."""
    docs = tuple(documents)
    flags: list[CrossReferenceFlag] = []
    checks_run: list[str] = []
    _check_identity(docs, flags, checks_run)
    _check_diagnosis_codes(docs, reference, flags, checks_run)
    _check_medication_indications(docs, reference, flags, checks_run)
    return CrossReferenceReport(flags=tuple(flags), checks_run=tuple(checks_run))
