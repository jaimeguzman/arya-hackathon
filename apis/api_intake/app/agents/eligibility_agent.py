"""Data-backed Eligibility Agent.

Wraps the deterministic safety-layer check (`app.safety.eligibility`) with
loaders over the repo's reference/synthetic datasets:

- data/reference/agency_configuration.json  -> service area zips, payers
- data/reference/payer_coverage_rules.json  -> accepted plans + documentation rules
- data/synthetic/caregiver_roster.json      -> caregiver availability by zip/service

The decision itself remains plain deterministic code — never an LLM output
(must-have.md guarantee 3). Plan-name matching uses fuzzy matching so a
spoken "Humana Gold" resolves to "Humana Gold Plus HMO".
"""

import difflib
import json
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from app.safety.eligibility import EligibilityResult, check_eligibility

# Repo layout: apis/api_intake/app/agents/ -> repo root is 4 levels up.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_AGENCY_CONFIG_PATH = _REPO_ROOT / "data" / "reference" / "agency_configuration.json"
_PAYER_RULES_PATH = _REPO_ROOT / "data" / "reference" / "payer_coverage_rules.json"
_CAREGIVER_ROSTER_PATH = _REPO_ROOT / "data" / "synthetic" / "caregiver_roster.json"

# Minimum similarity for a spoken plan name to resolve to a known plan.
_PLAN_MATCH_CUTOFF = 0.6

# Service type -> caregiver types that can deliver it (from PROJECT.md mappings).
_SERVICE_CAREGIVER_TYPES: dict[str, set[str]] = {
    "skilled_nursing": {"RN", "LPN"},
    "physical_therapy": {"PT"},
    "occupational_therapy": {"OT"},
    "speech_therapy": {"Speech Therapist"},
    "home_health_aide": {"HHA", "CNA"},
}


class EligibilityRequest(BaseModel):
    patient_zip: str | None = None
    insurance_plan: str | None = None
    service_type: str | None = None


class EligibilityDecision(BaseModel):
    status: str
    reasons: list[str]
    matched_plan: str | None = None
    required_documentation: list[str] = []
    matched_caregivers: list[str] = []


@lru_cache
def _load_agency_config() -> dict:
    return json.loads(_AGENCY_CONFIG_PATH.read_text())["agency"]


@lru_cache
def _load_payer_plans() -> list[dict]:
    payers = json.loads(_PAYER_RULES_PATH.read_text())["payers"]
    return [plan | {"payer": payer["payer"]} for payer in payers for plan in payer["plans"]]


@lru_cache
def _load_caregivers() -> list[dict]:
    return json.loads(_CAREGIVER_ROSTER_PATH.read_text())["caregivers"]


def resolve_plan(spoken_plan: str) -> dict | None:
    """Fuzzy-match a spoken plan name against the payer rules dataset."""
    plans = _load_payer_plans()
    names = [plan["plan"] for plan in plans]
    matches = difflib.get_close_matches(spoken_plan, names, n=1, cutoff=_PLAN_MATCH_CUTOFF)
    if not matches:
        # Also try substring containment for short spoken forms ("Humana Gold").
        lowered = spoken_plan.lower()
        contained = [name for name in names if lowered in name.lower()]
        if not contained:
            return None
        matches = contained[:1]
    return next(plan for plan in plans if plan["plan"] == matches[0])


# Minimum fraction of a plan name's tokens that must appear in an utterance.
_PLAN_TOKEN_MATCH_THRESHOLD = 0.5


def find_plan_in_text(utterance: str) -> dict | None:
    """Find a known plan mentioned inside free-form speech.

    Scores each plan by the fraction of its name tokens present in the
    utterance ("has Humana Gold" -> "Humana Gold Plus HMO" at 0.5).
    Deterministic — no LLM involved.
    """
    words = set(re.findall(r"[a-z0-9]+", utterance.lower()))
    best_plan: dict | None = None
    best_score = 0.0
    for plan in _load_payer_plans():
        tokens = re.findall(r"[a-z0-9]+", plan["plan"].lower())
        score = sum(token in words for token in tokens) / len(tokens)
        if score > best_score:
            best_score = score
            best_plan = plan
    if best_score >= _PLAN_TOKEN_MATCH_THRESHOLD:
        return best_plan
    return None


def find_available_caregivers(patient_zip: str, service_type: str) -> list[dict]:
    """Active caregivers of the right type serving the zip with spare capacity."""
    wanted_types = _SERVICE_CAREGIVER_TYPES.get(service_type, set())
    return [
        caregiver
        for caregiver in _load_caregivers()
        if caregiver["status"] == "active"
        and caregiver["type"] in wanted_types
        and patient_zip in caregiver["service_zips"]
        and caregiver["current_patient_load"] < caregiver["max_capacity"]
    ]


def required_documentation(plan: dict) -> list[str]:
    docs: list[str] = []
    if plan.get("requires_face_to_face_encounter"):
        docs.append("face-to-face encounter note")
    if plan.get("requires_homebound_status"):
        docs.append("homebound status certification")
    if plan.get("requires_prior_auth"):
        docs.append("prior authorization")
    return docs


def decide(request: EligibilityRequest) -> EligibilityDecision:
    """Run the deterministic eligibility check against the agency datasets."""
    agency = _load_agency_config()
    service_area_zips = set(agency["service_area_zips"])

    matched_plan = resolve_plan(request.insurance_plan) if request.insurance_plan else None
    accepted_plans = {plan["plan"] for plan in _load_payer_plans()}

    plan_covers_service = True
    if matched_plan and request.service_type:
        plan_covers_service = request.service_type in matched_plan["covers"]

    caregivers: list[dict] = []
    caregivers_available: bool | None = None
    if request.patient_zip and request.service_type:
        caregivers = find_available_caregivers(request.patient_zip, request.service_type)
        caregivers_available = bool(caregivers)

    result: EligibilityResult = check_eligibility(
        patient_zip=request.patient_zip,
        insurance_plan=matched_plan["plan"] if matched_plan else request.insurance_plan,
        service_area_zips=service_area_zips,
        accepted_plans=accepted_plans,
        caregivers_available=caregivers_available,
    )

    reasons = list(result.reasons)
    status = result.status.value
    if matched_plan and not plan_covers_service:
        status = "DECLINE"
        reasons.append(
            f"plan '{matched_plan['plan']}' does not cover service '{request.service_type}'"
        )

    return EligibilityDecision(
        status=status,
        reasons=reasons,
        matched_plan=matched_plan["plan"] if matched_plan else None,
        required_documentation=required_documentation(matched_plan) if matched_plan else [],
        matched_caregivers=[caregiver["id"] for caregiver in caregivers],
    )
