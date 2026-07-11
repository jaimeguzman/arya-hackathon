"""PostgreSQL-backed reference data for the eligibility checks.

Implements the Task-3 requirement "PostgreSQL queries: service area, insurance
contract, caregiver availability" against the intakeai_demo schema seeded by
infra/postgres/seed_demo_data.py, composing a `ReferenceData` the decision
engine consumes unchanged.

Coverage details (covers / prior-auth / documentation flags) are not modeled
in the insurance_contracts table, so they come from the canonical JSON plans
and are filtered down to the (payer, plan) pairs the database says are
accepted — the DB is the authority on WHO is contracted, the JSON rules on
WHAT the contract covers.

Every function returns None on any connection failure so the caller falls
back to the pure-JSON path: the demo never blocks on Postgres being up.
"""

import logging

from app.config import get_settings
from app.eligibility.reference_data import PlanContract, ReferenceData

logger = logging.getLogger("intakeai.eligibility.live_sources")

_QUERY_ZIPS = "SELECT zip_code FROM service_areas WHERE active = TRUE"
_QUERY_CONTRACTS = (
    "SELECT payer_name, plan_name FROM insurance_contracts WHERE accepted = TRUE"
)
_QUERY_CAREGIVER_AVAILABLE = """
SELECT 1
FROM caregivers cg
JOIN caregiver_service_areas sa ON sa.caregiver_id = cg.id
WHERE cg.status = 'active'
  AND cg.current_patient_load < cg.max_patient_capacity
  AND sa.zip_code = %(zip)s
  AND cg.type::text = ANY(%(roles)s)
LIMIT 1
"""


def _connect():
    settings = get_settings()
    if not settings.database_url:
        return None
    try:
        import psycopg

        return psycopg.connect(settings.database_url, connect_timeout=2)
    except Exception as exc:  # noqa: BLE001 — any failure means JSON fallback
        logger.warning("Postgres unavailable, using JSON fallback: %s", exc)
        return None


def load_reference_from_pg(json_plans: tuple[PlanContract, ...]) -> ReferenceData | None:
    """ReferenceData with zips + contracted plans from PostgreSQL.

    Returns None when the database is not configured or unreachable.
    """
    conn = _connect()
    if conn is None:
        return None
    try:
        with conn, conn.cursor() as cur:
            cur.execute(_QUERY_ZIPS)
            zips = frozenset(row[0] for row in cur.fetchall())
            cur.execute(_QUERY_CONTRACTS)
            contracted = {(row[0], row[1]) for row in cur.fetchall()}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Postgres reference query failed, using JSON fallback: %s", exc)
        return None
    plans = tuple(
        plan for plan in json_plans if (plan.payer, plan.plan) in contracted
    )
    return ReferenceData(
        service_area_zips=zips,
        accepted_payers=frozenset(payer for payer, _ in contracted),
        plans=plans,
    )


def caregivers_available_pg(patient_zip: str, roles: set[str]) -> bool | None:
    """Availability existence check against the live roster tables.

    Returns None when the database is not configured or unreachable.
    """
    conn = _connect()
    if conn is None:
        return None
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                _QUERY_CAREGIVER_AVAILABLE,
                {"zip": patient_zip, "roles": sorted(roles)},
            )
            return cur.fetchone() is not None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Postgres caregiver query failed, using JSON fallback: %s", exc)
        return None
