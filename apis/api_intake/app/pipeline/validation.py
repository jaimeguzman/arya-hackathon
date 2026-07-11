"""Layer 5 — Validation Agent.

First agent of the agentic review loop: deterministic field validation of
the Layer 4 raw JSON against reference tables and format rules.
- ICD-10 codes against data/reference/icd10_top30_home_health.json
- NPI: Luhn check (always) + NPPES registry lookup (when online)
- Member ID against the payer-specific formats from Layer 3
- DOB reasonable, discharge date after admission date
- Zip existence against data/reference/zip_codes.json
- Medication dosage against data/reference/medication_dosage_ranges.json

Every failure is a `ValidationFailure` naming the field and the rule that
tripped, so the Correction Agent (Layer 5, next in sequence) can reason
about it. Validation is code, never LLM-decided.

Spec: app_spec.txt <document_pipeline><layer number="5">.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from app.config import get_settings
from app.pipeline.extraction_rules import match_member_id_payer

logger = logging.getLogger("intakeai.pipeline.validation")

ICD10_FILE = "icd10_top30_home_health.json"
ZIP_CODES_FILE = "zip_codes.json"
DOSAGE_RANGES_FILE = "medication_dosage_ranges.json"

# A DOB implying an age above this is treated as an extraction error.
MAX_PATIENT_AGE_YEARS = 120

# NPI check digit is computed over the number prefixed with the ISO issuer
# identifier for US health providers.
NPI_ISO_PREFIX = "80840"
NPI_LENGTH = 10

NPPES_API_URL = "https://npiregistry.cms.hhs.gov/api/?version=2.1&number={npi}"
NPPES_TIMEOUT_SECONDS = 3

_DOSAGE_MG_PATTERN = re.compile(r"^\s*(?P<mg>\d+(?:\.\d+)?)\s*mg\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class ValidationFailure:
    """One failed check: which field, which rule, and why."""

    field: str
    rule: str
    message: str


@dataclass(frozen=True)
class Medication:
    name: str
    dosage: str  # as extracted, e.g. "500mg"


@dataclass(frozen=True)
class ValidationRecord:
    """Fields the Validation Agent knows how to check. All optional —
    only the fields present on the document are validated."""

    icd_codes: tuple[str, ...] = ()
    npi: str | None = None
    member_id: str | None = None
    payer: str | None = None
    date_of_birth: date | None = None
    admission_date: date | None = None
    discharge_date: date | None = None
    patient_zip: str | None = None
    medications: tuple[Medication, ...] = ()


@dataclass(frozen=True)
class ValidationReport:
    failures: tuple[ValidationFailure, ...]
    checks_run: tuple[str, ...]
    nppes_checked: bool  # False when offline/unreachable — Luhn still enforced

    @property
    def is_valid(self) -> bool:
        return not self.failures


@dataclass(frozen=True)
class ValidationReference:
    icd10_codes: frozenset[str]
    zip_codes: frozenset[str]
    # medication name (lowercased) -> (min_mg, max_mg) per dose
    dosage_ranges: dict[str, tuple[float, float]] = field(hash=False)


def load_validation_reference(data_dir: str | Path) -> ValidationReference:
    base = Path(data_dir)

    def _load(name: str) -> dict:
        path = base / name
        if not path.is_file():
            raise FileNotFoundError(f"Required reference data file missing: {path}")
        with path.open() as fh:
            return json.load(fh)

    icd_doc = _load(ICD10_FILE)
    zip_doc = _load(ZIP_CODES_FILE)
    dosage_doc = _load(DOSAGE_RANGES_FILE)
    return ValidationReference(
        icd10_codes=frozenset(entry["code"] for entry in icd_doc["codes"]),
        zip_codes=frozenset(entry["zip"] for entry in zip_doc["zip_codes"]),
        dosage_ranges={
            entry["name"].lower(): (float(entry["min_mg"]), float(entry["max_mg"]))
            for entry in dosage_doc["medications"]
        },
    )


def get_validation_reference() -> ValidationReference:
    settings = get_settings()
    if not settings.reference_data_dir:
        raise RuntimeError(
            "REFERENCE_DATA_DIR is not set — the Validation Agent cannot run "
            "without the reference tables."
        )
    return load_validation_reference(settings.reference_data_dir)


def npi_luhn_valid(npi: str) -> bool:
    """Luhn check over the ISO-prefixed NPI (CMS check-digit algorithm)."""
    if not npi.isdigit() or len(npi) != NPI_LENGTH:
        return False
    digits = [int(ch) for ch in NPI_ISO_PREFIX + npi]
    total = 0
    for idx, digit in enumerate(reversed(digits)):
        if idx % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def nppes_registry_lookup(npi: str) -> bool | None:
    """True/False when NPPES answered, None when unreachable (offline)."""
    url = NPPES_API_URL.format(npi=npi)
    try:
        with urllib.request.urlopen(url, timeout=NPPES_TIMEOUT_SECONDS) as resp:
            payload = json.load(resp)
        return int(payload.get("result_count", 0)) > 0
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        logger.warning("NPPES registry unreachable, skipping live NPI lookup: %s", exc)
        return None


def parse_dosage_mg(dosage: str) -> float | None:
    match = _DOSAGE_MG_PATTERN.match(dosage)
    return float(match.group("mg")) if match else None


NppesLookup = Callable[[str], bool | None]


def validate_record(
    record: ValidationRecord,
    reference: ValidationReference,
    *,
    nppes_lookup: NppesLookup = nppes_registry_lookup,
    today: date | None = None,
) -> ValidationReport:
    """Run every applicable validator; collect one failure per broken rule."""
    today = today or date.today()
    failures: list[ValidationFailure] = []
    checks_run: list[str] = []
    nppes_checked = False

    for idx, code in enumerate(record.icd_codes):
        checks_run.append("icd10_table_lookup")
        if code not in reference.icd10_codes:
            failures.append(
                ValidationFailure(
                    field=f"icd_codes[{idx}]",
                    rule="icd10_table_lookup",
                    message=f"ICD-10 code {code!r} not found in the reference table",
                )
            )

    if record.npi is not None:
        checks_run.append("npi_luhn")
        if not npi_luhn_valid(record.npi):
            failures.append(
                ValidationFailure(
                    field="npi",
                    rule="npi_luhn",
                    message=f"NPI {record.npi!r} fails the Luhn check digit",
                )
            )
        else:
            result = nppes_lookup(record.npi)
            if result is None:
                logger.info("NPPES unavailable — NPI %s validated by Luhn only", record.npi)
            else:
                checks_run.append("npi_nppes_registry")
                nppes_checked = True
                if not result:
                    failures.append(
                        ValidationFailure(
                            field="npi",
                            rule="npi_nppes_registry",
                            message=f"NPI {record.npi!r} not found in the NPPES registry",
                        )
                    )

    if record.member_id is not None:
        checks_run.append("member_id_payer_format")
        matched_payer = match_member_id_payer(record.member_id)
        if matched_payer is None or (
            record.payer is not None and matched_payer != record.payer
        ):
            expected = record.payer or "any accepted payer"
            failures.append(
                ValidationFailure(
                    field="member_id",
                    rule="member_id_payer_format",
                    message=(
                        f"Member ID {record.member_id!r} does not match the "
                        f"format for {expected}"
                    ),
                )
            )

    if record.date_of_birth is not None:
        checks_run.append("dob_reasonable")
        try:
            age_limit = today.replace(year=today.year - MAX_PATIENT_AGE_YEARS)
        except ValueError:  # Feb 29 in a non-leap target year
            age_limit = today.replace(
                year=today.year - MAX_PATIENT_AGE_YEARS, day=today.day - 1
            )
        if record.date_of_birth > today:
            failures.append(
                ValidationFailure(
                    field="date_of_birth",
                    rule="dob_reasonable",
                    message=f"DOB {record.date_of_birth.isoformat()} is in the future",
                )
            )
        elif record.date_of_birth < age_limit:
            failures.append(
                ValidationFailure(
                    field="date_of_birth",
                    rule="dob_reasonable",
                    message=(
                        f"DOB {record.date_of_birth.isoformat()} implies an age "
                        f"over {MAX_PATIENT_AGE_YEARS} years"
                    ),
                )
            )

    if record.admission_date is not None and record.discharge_date is not None:
        checks_run.append("discharge_after_admission")
        if record.discharge_date < record.admission_date:
            failures.append(
                ValidationFailure(
                    field="discharge_date",
                    rule="discharge_after_admission",
                    message=(
                        f"Discharge {record.discharge_date.isoformat()} is before "
                        f"admission {record.admission_date.isoformat()}"
                    ),
                )
            )

    if record.patient_zip is not None:
        checks_run.append("zip_exists")
        if record.patient_zip not in reference.zip_codes:
            failures.append(
                ValidationFailure(
                    field="patient_zip",
                    rule="zip_exists",
                    message=(
                        f"Zip {record.patient_zip!r} not found in the zip_codes "
                        "reference table"
                    ),
                )
            )

    for idx, med in enumerate(record.medications):
        med_range = reference.dosage_ranges.get(med.name.lower())
        if med_range is None:
            continue  # unknown medication: no range to check against
        checks_run.append("dosage_within_range")
        mg = parse_dosage_mg(med.dosage)
        min_mg, max_mg = med_range
        if mg is None:
            failures.append(
                ValidationFailure(
                    field=f"medications[{idx}].dosage",
                    rule="dosage_within_range",
                    message=(
                        f"{med.name} dosage {med.dosage!r} is not a parseable "
                        "mg value"
                    ),
                )
            )
        elif not min_mg <= mg <= max_mg:
            failures.append(
                ValidationFailure(
                    field=f"medications[{idx}].dosage",
                    rule="dosage_within_range",
                    message=(
                        f"{med.name} {med.dosage} outside clinical range "
                        f"{min_mg:g}-{max_mg:g}mg — likely OCR error"
                    ),
                )
            )

    return ValidationReport(
        failures=tuple(failures),
        checks_run=tuple(checks_run),
        nppes_checked=nppes_checked,
    )
