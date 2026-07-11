"""Canonical Eligibility Agent — the single eligibility implementation in apis/.

Consolidates the two prior implementations (this module's data-backed agent and
`app/eligibility/`'s decision engine) into one facade:

- decision logic: `app.eligibility.decision.decide_eligibility` — DECLINE only
  on black-and-white facts; any ambiguity -> NEEDS_MORE_INFO (must-have.md #3 bias)
- deterministic core spec: `app.safety.eligibility` (no LLM, ever)
- fuzzy plan matching: trigram matching inside the engine, plus
  `find_plan_in_text` for free-form speech (Twilio turns)
- datasets (single canonical source, see data/README.md):
  - data/reference/agency_configuration.json  -> service area zips, accepted payers
  - data/reference/payer_coverage_rules.json  -> plan contracts + documentation rules
  - data/reference/diagnosis_service_certification_mapping.json -> diagnosis -> services -> certs
  - data/synthetic/caregiver_roster.json      -> caregiver availability (role, zip, capacity, cert expiry)

Status writes go through `app.eligibility.status_writer` — the only sanctioned
write path for eligibility/acceptance decisions (see `apply_decision`).
"""

import difflib
import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from app.config import get_settings
from app.eligibility.decision import decide_eligibility
from app.eligibility.reference_data import ReferenceData, load_reference_data
from app.eligibility.status_writer import set_intake_status

# Decision status -> intake status written by the agent's write path.
_STATUS_TO_INTAKE_STATUS = {
    "ACCEPT": "accepted",
    "DECLINE": "declined",
    "NEEDS_MORE_INFO": "needs_more_info",
}

# Repo layout: apis/api_intake/app/agents/ -> repo root is 4 levels up.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_REFERENCE_DIR = _REPO_ROOT / "data" / "reference"
_PAYER_RULES_PATH = _DEFAULT_REFERENCE_DIR / "payer_coverage_rules.json"
_DIAGNOSIS_MAP_PATH = _DEFAULT_REFERENCE_DIR / "diagnosis_service_certification_mapping.json"
_CAREGIVER_ROSTER_PATH = _REPO_ROOT / "data" / "synthetic" / "caregiver_roster.json"

# Minimum similarity for a spoken plan name to resolve to a known plan.
_PLAN_MATCH_CUTOFF = 0.6
# Minimum fraction of a plan name's tokens that must appear in an utterance.
_PLAN_TOKEN_MATCH_THRESHOLD = 0.5


class EligibilityRequest(BaseModel):
    patient_zip: str | None = None
    payer: str | None = None
    insurance_plan: str | None = None
    service_type: str | None = None
    diagnosis_code: str | None = None


class EligibilityDecision(BaseModel):
    status: str
    reasons: list[str]
    matched_plan: str | None = None
    required_documentation: list[str] = []
    matched_caregivers: list[str] = []
    zip_ok: bool | None = None
    payer_ok: bool | None = None


@lru_cache
def _reference_data() -> ReferenceData:
    """PostgreSQL-backed when DATABASE_URL is configured, JSON otherwise."""
    settings = get_settings()
    data_dir = settings.reference_data_dir or _DEFAULT_REFERENCE_DIR
    json_data = load_reference_data(data_dir)
    if settings.database_url:
        from app.eligibility.live_sources import load_reference_from_pg

        pg_data = load_reference_from_pg(json_data.plans)
        if pg_data is not None:
            return pg_data
    return json_data


@lru_cache
def _load_payer_plans() -> list[dict]:
    payers = json.loads(_PAYER_RULES_PATH.read_text())["payers"]
    return [plan | {"payer": payer["payer"]} for payer in payers for plan in payer["plans"]]


@lru_cache
def _load_caregivers() -> tuple[dict, ...]:
    return tuple(json.loads(_CAREGIVER_ROSTER_PATH.read_text())["caregivers"])


@lru_cache
def _diagnosis_map() -> dict:
    return json.loads(_DIAGNOSIS_MAP_PATH.read_text())


@lru_cache
def _service_caregiver_types() -> dict[str, set[str]]:
    """service_type id -> caregiver base roles, from the reference dataset."""
    return {
        service["id"]: set(service["base_role"])
        for service in _diagnosis_map()["service_types"]
    }


def services_for_diagnosis(icd10: str) -> list[str]:
    """Diagnosis -> required service types (deterministic reference mapping)."""
    for mapping in _diagnosis_map()["diagnosis_mappings"]:
        if mapping["icd10"].upper() == icd10.upper():
            return list(mapping["required_services"])
    return []


def certifications_for_diagnosis(icd10: str) -> set[str]:
    """Diagnosis -> caregiver certifications it demands (reference mapping)."""
    for mapping in _diagnosis_map()["diagnosis_mappings"]:
        if mapping["icd10"].upper() == icd10.upper():
            return set(mapping["required_certifications"])
    return set()


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


def _certification_valid(caregiver: dict, certification: str, today: date) -> bool:
    expiry = (caregiver.get("cert_expiry") or {}).get(certification)
    return expiry is None or date.fromisoformat(expiry) >= today


def find_available_caregivers(
    patient_zip: str,
    service_type: str,
    required_certifications: set[str] | None = None,
) -> list[dict]:
    """Active caregivers of the right role serving the zip with spare capacity.

    When the diagnosis demands specific certifications, the caregiver must hold
    at least one of them, unexpired.
    """
    wanted_types = _service_caregiver_types().get(service_type, set())
    today = date.today()
    matched = []
    for caregiver in _load_caregivers():
        if caregiver["status"] != "active":
            continue
        if caregiver["type"] not in wanted_types:
            continue
        if patient_zip not in caregiver["service_zips"]:
            continue
        if caregiver["current_patient_load"] >= caregiver["max_capacity"]:
            continue
        if required_certifications:
            held = set(caregiver.get("certifications", []))
            valid = {
                cert
                for cert in held & required_certifications
                if _certification_valid(caregiver, cert, today)
            }
            if not valid:
                continue
        matched.append(caregiver)
    return matched


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
    """Run the consolidated deterministic eligibility decision."""
    data = _reference_data()

    # Resolve payer/plan: explicit fields first, then fuzzy speech matching.
    matched_plan = None
    if request.insurance_plan:
        matched_plan = resolve_plan(request.insurance_plan) or find_plan_in_text(
            request.insurance_plan
        )
    payer = request.payer or (matched_plan["payer"] if matched_plan else None)
    plan_name = matched_plan["plan"] if matched_plan else request.insurance_plan

    # Diagnosis path: Neo4j traversal first (diagnosis -> service -> cert ->
    # caregiver -> area), JSON reference mapping as the offline fallback.
    service_type = request.service_type
    matched_caregiver_ids: list[str] | None = None
    if request.diagnosis_code and request.patient_zip:
        from app.agents.knowledge_graph import traverse_caregivers_for_diagnosis

        graph = traverse_caregivers_for_diagnosis(
            request.diagnosis_code, request.patient_zip
        )
        if graph is not None:
            matched_caregiver_ids = graph["caregiver_ids"]
            if not service_type and graph["service_ids"]:
                service_type = graph["service_ids"][0]
    if not service_type and request.diagnosis_code:
        services = services_for_diagnosis(request.diagnosis_code)
        service_type = services[0] if services else None

    required_certs = (
        certifications_for_diagnosis(request.diagnosis_code)
        if request.diagnosis_code
        else None
    )
    caregivers: list[dict] = []
    caregivers_available: bool | None = None
    if matched_caregiver_ids is not None:
        caregivers_available = bool(matched_caregiver_ids)
    elif request.patient_zip and service_type:
        caregivers = find_available_caregivers(
            request.patient_zip, service_type, required_certs
        )
        caregivers_available = bool(caregivers)

    engine = decide_eligibility(
        patient_zip=request.patient_zip,
        payer=payer,
        plan=plan_name,
        service_type=service_type,
        caregivers_available=caregivers_available,
        data=data,
    )

    docs = list(engine.documentation_needs)
    if matched_plan:
        for doc in required_documentation(matched_plan):
            if doc not in docs:
                docs.append(doc)

    zip_ok = (
        None
        if not request.patient_zip
        else request.patient_zip.strip() in data.service_area_zips
    )
    payer_ok = None if not payer else payer in data.accepted_payers

    return EligibilityDecision(
        status=engine.status.value,
        reasons=list(engine.reasons),
        matched_plan=matched_plan["plan"] if matched_plan else None,
        required_documentation=docs,
        matched_caregivers=(
            matched_caregiver_ids
            if matched_caregiver_ids is not None
            else [caregiver["id"] for caregiver in caregivers]
        ),
        zip_ok=zip_ok,
        payer_ok=payer_ok,
    )


def apply_decision(intake: dict, decision: EligibilityDecision) -> dict:
    """The ONLY sanctioned write path for eligibility/acceptance statuses.

    Translates the agent's decision into an intake status and writes it via
    the guarded status writer. Other modules calling set_intake_status()
    with a decision status directly get UnauthorizedDecisionWrite.
    """
    return set_intake_status(intake, _STATUS_TO_INTAKE_STATUS[decision.status])
