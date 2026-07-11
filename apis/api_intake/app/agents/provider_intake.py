"""Provider-mode structured intake (feature 45).

Deterministic extraction of the provider-mode clinical fields — patient name,
date of birth, diagnosis (ICD-10 code or spoken description), insurance, zip —
plus the tokenization boundary for the mid-call eligibility loop:
`build_eligibility_request` accepts ONLY structured, non-identifying fields
(zip, insurance plan, service type, diagnosis code). Patient name and DOB are
identifiers (see app.safety.llm_gateway.IDENTIFIER_PLACEHOLDERS) and never
reach the Eligibility Agent.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

from app.agents.eligibility_agent import EligibilityRequest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_ICD10_PATH = _REPO_ROOT / "data" / "reference" / "icd10_top30_home_health.json"
_DIAGNOSIS_MAP_PATH = (
    _REPO_ROOT / "data" / "reference" / "diagnosis_service_certification_mapping.json"
)

# ICD-10 codes: letter (no U per WHO reserve), two digits, optional decimals.
_ICD10_CODE_PATTERN = re.compile(r"\b([A-TV-Z]\d{2}(?:\.\d{1,4})?)\b")

# Spoken dates: numeric (03/12/1950, 1950-03-12) or month-name (March 12 1950).
_DOB_NUMERIC_PATTERN = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{1,2}-\d{1,2}-\d{4})\b"
)
_DOB_MONTH_NAME_PATTERN = re.compile(
    r"\b((?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})\b",
    re.IGNORECASE,
)

# "patient's name is Jane Doe", "referral for John Smith", "the patient is X".
_NAME_PATTERN = re.compile(
    r"(?:patient(?:'s)?\s+name\s+is|name\s+is|referral\s+for|"
    r"the\s+patient\s+is|for\s+patient)\s+"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})"
)

# Minimum fraction of a diagnosis description's significant tokens that must
# appear in the utterance for a spoken-description match.
_DIAGNOSIS_TOKEN_MATCH_THRESHOLD = 0.5
_DIAGNOSIS_STOPWORDS = frozenset(
    {"of", "the", "with", "without", "and", "or", "unspecified", "other", "type"}
)

# Structured provider-mode question order (feature 45 step 1).
PROVIDER_FIELD_QUESTIONS: tuple[tuple[str, str], ...] = (
    ("patient_name", "What is the patient's full name?"),
    ("patient_dob", "What is the patient's date of birth?"),
    ("diagnosis_code", "What is the primary diagnosis — the ICD-10 code if you have it?"),
    ("insurance_plan", "What insurance plan does the patient have?"),
    ("patient_zip", "What is the patient's zip code?"),
)


@lru_cache
def _icd10_codes() -> tuple[dict, ...]:
    return tuple(json.loads(_ICD10_PATH.read_text())["codes"])


@lru_cache
def _diagnosis_services() -> dict[str, tuple[str, ...]]:
    mappings = json.loads(_DIAGNOSIS_MAP_PATH.read_text())["diagnosis_mappings"]
    return {
        mapping["icd10"].upper(): tuple(mapping["required_services"])
        for mapping in mappings
    }


def service_for_diagnosis(diagnosis_code: str) -> str | None:
    """Primary service type a diagnosis demands (deterministic reference map)."""
    services = _diagnosis_services().get(diagnosis_code.upper(), ())
    return services[0] if services else None


def extract_patient_name(utterance: str) -> str | None:
    match = _NAME_PATTERN.search(utterance)
    return match.group(1) if match else None


def extract_dob(utterance: str) -> str | None:
    match = _DOB_NUMERIC_PATTERN.search(utterance) or _DOB_MONTH_NAME_PATTERN.search(
        utterance
    )
    return match.group(1) if match else None


def extract_diagnosis(utterance: str) -> str | None:
    """ICD-10 code mentioned literally, or a spoken description resolved
    against the reference ICD-10 subset (deterministic token matching)."""
    code_match = _ICD10_CODE_PATTERN.search(utterance)
    if code_match:
        candidate = code_match.group(1).upper()
        for entry in _icd10_codes():
            if entry["code"].upper() == candidate:
                return entry["code"]
        return candidate
    words = set(re.findall(r"[a-z0-9]+", utterance.lower()))
    best_code: str | None = None
    best_score = 0.0
    for entry in _icd10_codes():
        tokens = [
            token
            for token in re.findall(r"[a-z0-9]+", entry["description"].lower())
            if token not in _DIAGNOSIS_STOPWORDS
        ]
        if not tokens:
            continue
        score = sum(token in words for token in tokens) / len(tokens)
        if score > best_score:
            best_score = score
            best_code = entry["code"]
    if best_score >= _DIAGNOSIS_TOKEN_MATCH_THRESHOLD:
        return best_code
    return None


def build_eligibility_request(
    *,
    patient_zip: str | None,
    insurance_plan: str | None,
    service_type: str | None,
    diagnosis_code: str | None,
) -> EligibilityRequest:
    """The tokenization boundary of the mid-call eligibility loop.

    Keyword-only structured fields; there is no parameter for patient name,
    DOB, phone, or any other identifier — they cannot flow to the
    Eligibility Agent through this call site.
    """
    if service_type is None and diagnosis_code is not None:
        service_type = service_for_diagnosis(diagnosis_code)
    kwargs: dict[str, str | None] = {
        "patient_zip": patient_zip,
        "insurance_plan": insurance_plan,
        "service_type": service_type,
    }
    # The diagnosis code field is being added by a parallel eligibility-agent
    # track; pass it through only when the model already supports it.
    if "diagnosis_code" in EligibilityRequest.model_fields:
        kwargs["diagnosis_code"] = diagnosis_code
    return EligibilityRequest(**kwargs)
