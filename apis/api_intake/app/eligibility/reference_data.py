"""Loader for the agency/payer reference data the eligibility checks use.

The data directory is configured via the REFERENCE_DATA_DIR environment
variable (Settings.reference_data_dir). There is no built-in fallback: an
unset or invalid path raises, so a misconfigured deploy fails loudly instead
of silently answering eligibility questions from nothing.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

AGENCY_CONFIG_FILE = "agency_configuration.json"
PAYER_RULES_FILE = "payer_coverage_rules.json"


@dataclass(frozen=True)
class PlanContract:
    payer: str
    plan: str
    covers: frozenset[str]
    requires_prior_auth: bool


@dataclass(frozen=True)
class ReferenceData:
    service_area_zips: frozenset[str]
    accepted_payers: frozenset[str]
    plans: tuple[PlanContract, ...]


def _load_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Required reference data file missing: {path}")
    with path.open() as fh:
        return json.load(fh)


def load_reference_data(data_dir: str | Path) -> ReferenceData:
    base = Path(data_dir)
    agency = _load_json(base / AGENCY_CONFIG_FILE)["agency"]
    payer_doc = _load_json(base / PAYER_RULES_FILE)

    plans: list[PlanContract] = []
    for payer_entry in payer_doc["payers"]:
        for plan in payer_entry["plans"]:
            plans.append(
                PlanContract(
                    payer=payer_entry["payer"],
                    plan=plan["plan"],
                    covers=frozenset(plan["covers"]),
                    requires_prior_auth=plan["requires_prior_auth"],
                )
            )

    return ReferenceData(
        service_area_zips=frozenset(agency["service_area_zips"]),
        accepted_payers=frozenset(agency["accepted_payers"]),
        plans=tuple(plans),
    )


@lru_cache
def get_reference_data() -> ReferenceData:
    settings = get_settings()
    if not settings.reference_data_dir:
        raise RuntimeError(
            "REFERENCE_DATA_DIR is not set — eligibility checks cannot run "
            "without the agency/payer reference data."
        )
    return load_reference_data(settings.reference_data_dir)
