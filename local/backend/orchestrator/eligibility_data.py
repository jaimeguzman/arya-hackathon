"""Data-fetch layer for eligibility — the middle the team's pure
`check_eligibility()` core needs.

It answers three factual questions the deterministic core consumes:
  - which zips does the agency serve?
  - which insurance plans does it accept?
  - is a suitable caregiver available for this service + zip?
plus one the orchestrator needs for gap-chasing:
  - which documents does this plan require for this service?

Two implementations, same protocol:
  - `JsonEligibilityDataProvider` — reads local/data/*.json, fully offline.
  - `DbEligibilityDataProvider` — real Postgres + Neo4j queries.
And `FallbackDataProvider(primary, fallback)` — tries the DB, transparently
falls back to JSON when the DB is unreachable (Docker down), so the system
always answers. This is the "DB-backed, JSON fallback" design.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# Process-wide DB availability memo so we probe once and warn once, not per
# referral. `None` = untried. Call reset_db_availability() in tests if needed.
_DB_AVAILABLE: Optional[bool] = None


def reset_db_availability() -> None:
    global _DB_AVAILABLE
    _DB_AVAILABLE = None


@runtime_checkable
class EligibilityDataProvider(Protocol):
    async def served_zips(self) -> set[str]: ...
    async def accepted_plans(self) -> set[str]: ...
    async def caregivers_available(
        self, *, service_type: Optional[str], zip_code: Optional[str]
    ) -> Optional[bool]: ...
    async def required_documents(
        self, *, plan: Optional[str], service_type: Optional[str]
    ) -> list[str]: ...


# --------------------------------------------------------------------------- #
# JSON provider — offline, deterministic, reads local/data                    #
# --------------------------------------------------------------------------- #
class JsonEligibilityDataProvider:
    def __init__(self, data_dir: Path = _DATA_DIR) -> None:
        self._dir = data_dir

    def _load(self, name: str):
        with (self._dir / name).open(encoding="utf-8") as f:
            return json.load(f)

    async def served_zips(self) -> set[str]:
        rows = self._load("service_areas.json")
        return {r["zip_code"] for r in rows if r.get("active", True)}

    async def accepted_plans(self) -> set[str]:
        data = self._load("insurance_rules.json")
        return {p["name"] for p in data["plans"] if p.get("accepted", True)}

    def _service_cert_map(self) -> dict[str, set[str]]:
        """service_type -> set of certifications that satisfy it (union across mappings)."""
        data = self._load("diagnosis_service_map.json")
        result: dict[str, set[str]] = {}
        for mapping in data.get("mappings", []):
            for service, cfg in mapping.get("service_certification_map", {}).items():
                result.setdefault(service, set()).update(cfg.get("certs", []))
        return result

    async def caregivers_available(
        self, *, service_type: Optional[str], zip_code: Optional[str]
    ) -> Optional[bool]:
        # Unknown inputs -> unknown availability (core turns this into NEEDS_MORE_INFO).
        if not service_type or not zip_code:
            return None
        required_certs = self._service_cert_map().get(service_type)
        if not required_certs:
            return None  # service type we can't map -> let a human decide
        today = date.today()
        for c in self._load("caregiver_roster.json"):
            if c.get("status") != "active":
                continue
            if zip_code not in c.get("serviceAreas", []):
                continue
            if c.get("currentPatientLoad", 0) >= c.get("maxPatientCapacity", 8):
                continue
            for cert in c.get("certifications", []):
                if cert["certificationName"] not in required_certs:
                    continue
                exp = cert.get("expiryDate")
                if exp is None or date.fromisoformat(exp) >= today:
                    return True
        return False

    async def required_documents(
        self, *, plan: Optional[str], service_type: Optional[str]
    ) -> list[str]:
        if not plan:
            return []
        data = self._load("insurance_rules.json")
        for p in data["plans"]:
            if p["name"] != plan:
                continue
            coverage = p.get("coverage", [])
            if service_type:
                for cov in coverage:
                    if cov["serviceType"] == service_type:
                        return list(cov.get("requiredDocs") or [])
            # no service match: union of all required docs for the plan
            docs: list[str] = []
            for cov in coverage:
                for d in cov.get("requiredDocs") or []:
                    if d not in docs:
                        docs.append(d)
            return docs
        return []


# --------------------------------------------------------------------------- #
# DB provider — real Postgres + Neo4j                                          #
# --------------------------------------------------------------------------- #
class DbEligibilityDataProvider:
    """Queries the live databases via the Phase 1 clients in
    backend.models.database. Assumes init_all_dbs() has run (the FallbackData
    provider ensures init + catches failures)."""

    async def served_zips(self) -> set[str]:
        from sqlalchemy import text

        from backend.models.database import get_sessionmaker

        async with get_sessionmaker()() as session:
            rows = await session.execute(
                text("SELECT zip_code FROM service_areas WHERE active = TRUE")
            )
            return {r[0] for r in rows}

    async def accepted_plans(self) -> set[str]:
        from sqlalchemy import text

        from backend.models.database import get_sessionmaker

        async with get_sessionmaker()() as session:
            rows = await session.execute(
                text("SELECT plan_name FROM insurance_contracts WHERE accepted = TRUE")
            )
            return {r[0] for r in rows}

    async def _required_certs(self, service_type: str) -> set[str]:
        from backend.models.database import get_neo4j

        driver = get_neo4j()
        async with driver.session() as session:
            result = await session.run(
                """
                MATCH (s:ServiceType {name: $name})-[:NEEDS_CERTIFICATION]->(c:CertificationType)
                RETURN collect(c.name) AS certs
                """,
                name=service_type,
            )
            record = await result.single()
            return set(record["certs"]) if record and record["certs"] else set()

    async def caregivers_available(
        self, *, service_type: Optional[str], zip_code: Optional[str]
    ) -> Optional[bool]:
        if not service_type or not zip_code:
            return None
        required_certs = await self._required_certs(service_type)
        if not required_certs:
            return None
        from sqlalchemy import text

        from backend.models.database import get_sessionmaker

        async with get_sessionmaker()() as session:
            row = await session.execute(
                text(
                    """
                    SELECT 1
                    FROM caregivers cg
                    JOIN caregiver_service_areas sa ON sa.caregiver_id = cg.id
                    JOIN caregiver_certifications ct ON ct.caregiver_id = cg.id
                    WHERE cg.status = 'active'
                      AND cg.current_patient_load < cg.max_patient_capacity
                      AND sa.zip_code = :zip
                      AND ct.certification_name = ANY(:certs)
                      AND (ct.expiry_date IS NULL OR ct.expiry_date >= CURRENT_DATE)
                    LIMIT 1
                    """
                ),
                {"zip": zip_code, "certs": list(required_certs)},
            )
            return row.first() is not None

    async def required_documents(
        self, *, plan: Optional[str], service_type: Optional[str]
    ) -> list[str]:
        if not plan:
            return []
        from backend.models.database import get_neo4j

        driver = get_neo4j()
        async with driver.session() as session:
            if service_type:
                result = await session.run(
                    """
                    MATCH (i:InsurancePlan {name: $plan})-[cov:COVERS]->(s:ServiceType {name: $service})
                    RETURN cov.requiredDocs AS docs
                    """,
                    plan=plan,
                    service=service_type,
                )
                record = await result.single()
                if record and record["docs"]:
                    return list(record["docs"])
            result = await session.run(
                """
                MATCH (i:InsurancePlan {name: $plan})-[cov:COVERS]->(:ServiceType)
                UNWIND cov.requiredDocs AS d
                RETURN collect(DISTINCT d) AS docs
                """,
                plan=plan,
            )
            record = await result.single()
            return list(record["docs"]) if record and record["docs"] else []


# --------------------------------------------------------------------------- #
# Fallback wrapper — DB first, JSON on failure                                #
# --------------------------------------------------------------------------- #
class FallbackDataProvider:
    """Try the DB provider; on any error (Docker down, connection refused),
    transparently use the JSON provider. Logs the first fallback only."""

    def __init__(
        self,
        primary: Optional[EligibilityDataProvider] = None,
        fallback: Optional[EligibilityDataProvider] = None,
    ) -> None:
        self._primary = primary or DbEligibilityDataProvider()
        self._fallback = fallback or JsonEligibilityDataProvider()

    async def _ensure_db(self) -> bool:
        """Probe the DB once per process; remember whether it's usable."""
        global _DB_AVAILABLE
        if _DB_AVAILABLE is not None:
            return _DB_AVAILABLE
        try:
            from backend.models.database import get_sessionmaker, init_all_dbs

            try:
                get_sessionmaker()
            except RuntimeError:
                await init_all_dbs()
            from sqlalchemy import text

            async with get_sessionmaker()() as session:
                await session.execute(text("SELECT 1"))
            _DB_AVAILABLE = True
            logger.info("Eligibility using live database")
        except Exception as exc:  # noqa: BLE001 — any failure -> JSON
            _DB_AVAILABLE = False
            logger.warning("Eligibility DB unavailable, using JSON fallback: %s", exc)
        return _DB_AVAILABLE

    async def _provider(self) -> EligibilityDataProvider:
        return self._primary if await self._ensure_db() else self._fallback

    async def served_zips(self) -> set[str]:
        return await (await self._provider()).served_zips()

    async def accepted_plans(self) -> set[str]:
        return await (await self._provider()).accepted_plans()

    async def caregivers_available(
        self, *, service_type: Optional[str], zip_code: Optional[str]
    ) -> Optional[bool]:
        return await (await self._provider()).caregivers_available(
            service_type=service_type, zip_code=zip_code
        )

    async def required_documents(
        self, *, plan: Optional[str], service_type: Optional[str]
    ) -> list[str]:
        return await (await self._provider()).required_documents(
            plan=plan, service_type=service_type
        )
