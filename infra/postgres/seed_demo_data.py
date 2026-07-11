"""PostgreSQL demo-database seeder.

Loads the canonical datasets (data/reference + data/synthetic — see
data/README.md) into the intakeai_demo schema created by
infra/init/postgres_init.sql (currently at local/backend/db/postgres_init.sql
until merge day — see docs/MERGE_DAY_RECONCILIATION.md).

Safety (must-have.md #1): refuses to run against a non-allowlisted database
name and refuses source files without a synthetic/reference marker.

Usage (uses DATABASE_URL env var, matching .env.example; run from repo root):

    python infra/postgres/seed_demo_data.py
"""

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = REPO_ROOT / "data" / "reference"
SYNTHETIC_DIR = REPO_ROOT / "data" / "synthetic"

ALLOWED_DEMO_DB_NAMES = {"intakeai_demo", "intakeai_test"}

# service_areas.borough is NOT NULL but the canonical agency configuration
# carries only zip codes; the borough is not part of any eligibility decision.
BOROUGH_NOT_IN_DATASET = "not-in-dataset"

# Canonical roster type -> caregiver_type enum value in postgres_init.sql.
CAREGIVER_TYPE_TO_ENUM = {"Speech Therapist": "ST"}


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _require_synthetic(document: dict, path: Path) -> None:
    if not any(key in document for key in ("_synthetic_data_notice", "_note")):
        raise SystemExit(f"Refusing to load {path}: no synthetic/reference marker found.")


def seed(conn) -> dict[str, int]:
    agency_doc = _load(REFERENCE_DIR / "agency_configuration.json")
    payer_doc = _load(REFERENCE_DIR / "payer_coverage_rules.json")
    roster_doc = _load(SYNTHETIC_DIR / "caregiver_roster.json")
    _require_synthetic(roster_doc, SYNTHETIC_DIR / "caregiver_roster.json")
    _require_synthetic(agency_doc, REFERENCE_DIR / "agency_configuration.json")

    with conn.cursor() as cur:
        # Idempotent: clear the seeded tables (children first).
        cur.execute(
            "TRUNCATE caregiver_certifications, caregiver_service_areas, "
            "caregiver_availability, caregivers, service_areas, "
            "insurance_contracts CASCADE"
        )

        for zip_code in agency_doc["agency"]["service_area_zips"]:
            cur.execute(
                "INSERT INTO service_areas (zip_code, borough, active) "
                "VALUES (%s, %s, TRUE)",
                (zip_code, BOROUGH_NOT_IN_DATASET),
            )

        for payer in payer_doc["payers"]:
            for plan in payer["plans"]:
                cur.execute(
                    "INSERT INTO insurance_contracts "
                    "(payer_name, plan_name, plan_type, accepted, notes) "
                    "VALUES (%s, %s, %s, TRUE, %s)",
                    (payer["payer"], plan["plan"], plan["plan_type"], plan.get("notes")),
                )

        for caregiver in roster_doc["caregivers"]:
            if caregiver.get("is_synthetic") is not True:
                raise SystemExit(
                    f"Refusing caregiver {caregiver.get('id')}: is_synthetic is not True."
                )
            cur.execute(
                "INSERT INTO caregivers "
                "(name, type, status, languages, current_patient_load, "
                " max_patient_capacity) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    caregiver["name"],
                    CAREGIVER_TYPE_TO_ENUM.get(caregiver["type"], caregiver["type"]),
                    caregiver["status"],
                    caregiver["languages"],
                    caregiver["current_patient_load"],
                    caregiver["max_capacity"],
                ),
            )
            caregiver_uuid = cur.fetchone()[0]
            for cert in caregiver.get("certifications", []):
                cur.execute(
                    "INSERT INTO caregiver_certifications "
                    "(caregiver_id, certification_name, expiry_date) "
                    "VALUES (%s, %s, %s)",
                    (
                        caregiver_uuid,
                        cert,
                        (caregiver.get("cert_expiry") or {}).get(cert),
                    ),
                )
            for zip_code in caregiver["service_zips"]:
                cur.execute(
                    "INSERT INTO caregiver_service_areas (caregiver_id, zip_code) "
                    "VALUES (%s, %s)",
                    (caregiver_uuid, zip_code),
                )

        counts = {}
        for table in ("service_areas", "insurance_contracts", "caregivers",
                      "caregiver_certifications", "caregiver_service_areas"):
            cur.execute(f"SELECT count(*) FROM {table}")  # noqa: S608 — fixed names
            counts[table] = cur.fetchone()[0]
    conn.commit()
    return counts


def main() -> int:
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        print("DATABASE_URL is required (see .env.example).", file=sys.stderr)
        return 1
    db_name = urlparse(dsn).path.lstrip("/")
    if db_name not in ALLOWED_DEMO_DB_NAMES:
        print(
            f"Refusing to seed '{db_name}': not an allowlisted demo database "
            f"({sorted(ALLOWED_DEMO_DB_NAMES)}).",
            file=sys.stderr,
        )
        return 1
    with psycopg.connect(dsn) as conn:
        counts = seed(conn)
    print("intakeai_demo seeded from canonical data/:")
    for table, count in counts.items():
        print(f"  {table}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
