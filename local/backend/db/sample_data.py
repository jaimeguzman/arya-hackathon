"""Load JSON seed data into PostgreSQL and Neo4j.

# ponytail: truncate-reload over ON CONFLICT for hackathon speed
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, time
from pathlib import Path
from typing import Any

from sqlalchemy import delete, text

from backend.config import get_settings
from backend.models.database import (
    close_all_dbs,
    get_neo4j,
    get_redis,
    get_sessionmaker,
    init_all_dbs,
)
from backend.models.tables import (
    Caregiver,
    CaregiverAvailability,
    CaregiverCertification,
    CaregiverServiceArea,
    CaregiverStatus,
    CaregiverType,
    InsuranceContract,
    ReferralSource,
    ServiceArea,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

LOCAL_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = LOCAL_ROOT / "data"
CYPHER_PATH = Path(__file__).resolve().parent / "neo4j_seed.cypher"


def _load_json(name: str) -> Any:
    """Read a JSON file from local/data."""
    path = DATA_DIR / name
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _parse_time(value: str) -> time:
    parts = value.split(":")
    return time(int(parts[0]), int(parts[1]))


async def apply_neo4j_constraints() -> None:
    """Run constraint/index Cypher statements from neo4j_seed.cypher."""
    driver = get_neo4j()
    raw = CYPHER_PATH.read_text(encoding="utf-8")
    statements = [
        s.strip()
        for s in raw.split(";")
        if s.strip() and not s.strip().startswith("--")
    ]
    async with driver.session() as session:
        for stmt in statements:
            # strip leading comment lines inside statement blocks
            lines = [ln for ln in stmt.splitlines() if not ln.strip().startswith("--")]
            clean = "\n".join(lines).strip()
            if clean:
                await session.run(clean)
    logger.info("Neo4j constraints/indexes applied (%s statements)", len(statements))


async def load_service_areas() -> int:
    """Load agency service areas into PostgreSQL."""
    rows = _load_json("service_areas.json")
    Session = get_sessionmaker()
    async with Session() as session:
        await session.execute(delete(ServiceArea))
        for row in rows:
            session.add(
                ServiceArea(
                    zip_code=row["zip_code"],
                    borough=row["borough"],
                    active=row.get("active", True),
                )
            )
        await session.commit()
    logger.info("Loaded service_areas: %s", len(rows))
    return len(rows)


async def load_insurance() -> int:
    """Load insurance contracts from insurance_rules.json plans."""
    data = _load_json("insurance_rules.json")
    plans = data["plans"]
    Session = get_sessionmaker()
    async with Session() as session:
        await session.execute(delete(InsuranceContract))
        for plan in plans:
            if "accepted" not in plan:
                raise ValueError(f"Plan {plan.get('code')} missing required 'accepted' field")
            session.add(
                InsuranceContract(
                    payer_name=plan["payerName"],
                    plan_name=plan["name"],
                    plan_type=plan["planType"],
                    accepted=bool(plan["accepted"]),
                    notes=plan.get("notes"),
                )
            )
        await session.commit()
    logger.info("Loaded insurance_contracts: %s", len(plans))
    return len(plans)


async def load_referral_sources() -> int:
    """Load referral sources into PostgreSQL."""
    rows = _load_json("referral_sources.json")
    Session = get_sessionmaker()
    async with Session() as session:
        await session.execute(delete(ReferralSource))
        for row in rows:
            session.add(
                ReferralSource(
                    facility_name=row["facility_name"],
                    facility_type=row["facility_type"],
                    contact_name=row.get("contact_name"),
                    phone=row.get("phone"),
                    fax=row.get("fax"),
                    email=row.get("email"),
                    ehr_system=row.get("ehr_system"),
                    total_referrals=row.get("totalReferrals", 0),
                    accepted_referrals=row.get("acceptedReferrals", 0),
                )
            )
        await session.commit()
    logger.info("Loaded referral_sources: %s", len(rows))
    return len(rows)


async def load_caregivers() -> tuple[int, int, int, int]:
    """Load caregivers and related child tables."""
    rows = _load_json("caregiver_roster.json")
    Session = get_sessionmaker()
    cert_count = area_count = avail_count = 0
    async with Session() as session:
        await session.execute(delete(CaregiverAvailability))
        await session.execute(delete(CaregiverServiceArea))
        await session.execute(delete(CaregiverCertification))
        await session.execute(delete(Caregiver))
        for row in rows:
            cg = Caregiver(
                name=row["name"],
                type=CaregiverType(row["type"]),
                status=CaregiverStatus(row["status"]),
                languages=row.get("languages", []),
                current_patient_load=row.get("currentPatientLoad", 0),
                max_patient_capacity=row.get("maxPatientCapacity", 8),
                phone=row.get("phone"),
                email=row.get("email"),
            )
            session.add(cg)
            await session.flush()
            for cert in row.get("certifications", []):
                session.add(
                    CaregiverCertification(
                        caregiver_id=cg.id,
                        certification_name=cert["certificationName"],
                        issued_date=_parse_date(cert.get("issuedDate")),
                        expiry_date=_parse_date(cert.get("expiryDate")),
                    )
                )
                cert_count += 1
            for zip_code in row.get("serviceAreas", []):
                session.add(
                    CaregiverServiceArea(caregiver_id=cg.id, zip_code=zip_code)
                )
                area_count += 1
            for slot in row.get("availability", []):
                session.add(
                    CaregiverAvailability(
                        caregiver_id=cg.id,
                        day_of_week=slot["dayOfWeek"],
                        start_time=_parse_time(slot["startTime"]),
                        end_time=_parse_time(slot["endTime"]),
                    )
                )
                avail_count += 1
        await session.commit()
    logger.info(
        "Loaded caregivers=%s certs=%s areas=%s availability=%s",
        len(rows),
        cert_count,
        area_count,
        avail_count,
    )
    return len(rows), cert_count, area_count, avail_count


async def load_neo4j_diagnoses() -> int:
    """MERGE Diagnosis nodes from ICD JSON."""
    rows = _load_json("icd10_home_health_top30.json")
    driver = get_neo4j()
    async with driver.session() as session:
        for row in rows:
            await session.run(
                """
                MERGE (d:Diagnosis {icdCode: $icdCode})
                SET d.name = $name, d.category = $category
                """,
                icdCode=row["icdCode"],
                name=row["name"],
                category=row["category"],
            )
    logger.info("Loaded Neo4j Diagnosis nodes: %s", len(rows))
    return len(rows)


async def load_neo4j_diagnosis_map() -> None:
    """Load ServiceType, CertificationType, REQUIRES, NEEDS_CERTIFICATION."""
    data = _load_json("diagnosis_service_map.json")
    driver = get_neo4j()
    async with driver.session() as session:
        await session.run("MATCH ()-[r:REQUIRES]->() DELETE r")
        await session.run("MATCH ()-[r:NEEDS_CERTIFICATION]->() DELETE r")

        for st in data["service_types"]:
            await session.run(
                """
                MERGE (s:ServiceType {name: $name})
                SET s.displayName = $displayName, s.description = $description
                """,
                name=st["name"],
                displayName=st["displayName"],
                description=st.get("description"),
            )
        for ct in data["certification_types"]:
            await session.run(
                """
                MERGE (c:CertificationType {name: $name})
                SET c.displayName = $displayName
                """,
                name=ct["name"],
                displayName=ct["displayName"],
            )

        # Global service->cert edges (dedupe by service)
        seen_service_certs: set[tuple[str, str]] = set()
        for mapping in data["mappings"]:
            cert_map = mapping.get("service_certification_map", {})
            for service_name, cfg in cert_map.items():
                either = bool(cfg.get("either", False))
                for cert_name in cfg.get("certs", []):
                    key = (service_name, cert_name)
                    if key in seen_service_certs:
                        continue
                    seen_service_certs.add(key)
                    await session.run(
                        """
                        MATCH (s:ServiceType {name: $service})
                        MATCH (c:CertificationType {name: $cert})
                        MERGE (s)-[r:NEEDS_CERTIFICATION]->(c)
                        SET r.either = $either
                        """,
                        service=service_name,
                        cert=cert_name,
                        either=either,
                    )

            for code in mapping.get("diagnosis_codes", []):
                for req in mapping.get("required_services", []):
                    await session.run(
                        """
                        MATCH (d:Diagnosis {icdCode: $code})
                        MATCH (s:ServiceType {name: $service})
                        MERGE (d)-[r:REQUIRES]->(s)
                        SET r.priority = $priority, r.specialization = $specialization
                        """,
                        code=code,
                        service=req["service"],
                        priority=req.get("priority", "primary"),
                        specialization=req.get("specialization"),
                    )
    logger.info("Loaded Neo4j diagnosis→service→cert mappings")


async def load_neo4j_insurance() -> None:
    """Load Payer, InsurancePlan, UNDER_PAYER, COVERS."""
    data = _load_json("insurance_rules.json")
    driver = get_neo4j()
    async with driver.session() as session:
        await session.run("MATCH ()-[r:COVERS]->() DELETE r")
        await session.run("MATCH ()-[r:UNDER_PAYER]->() DELETE r")

        for payer in data["payers"]:
            await session.run(
                """
                MERGE (p:Payer {name: $name})
                SET p.type = $type
                """,
                name=payer["name"],
                type=payer["type"],
            )

        for plan in data["plans"]:
            await session.run(
                """
                MERGE (i:InsurancePlan {code: $code})
                SET i.name = $name, i.planType = $planType
                WITH i
                MATCH (p:Payer {name: $payerName})
                MERGE (i)-[:UNDER_PAYER]->(p)
                """,
                code=plan["code"],
                name=plan["name"],
                planType=plan["planType"],
                payerName=plan["payerName"],
            )
            for cov in plan.get("coverage", []):
                await session.run(
                    """
                    MATCH (i:InsurancePlan {code: $code})
                    MATCH (s:ServiceType {name: $serviceType})
                    MERGE (i)-[r:COVERS]->(s)
                    SET r.priorAuthRequired = $priorAuthRequired,
                        r.requiredDocs = $requiredDocs,
                        r.visitLimit = $visitLimit,
                        r.episodeDays = $episodeDays,
                        r.notes = $notes
                    """,
                    code=plan["code"],
                    serviceType=cov["serviceType"],
                    priorAuthRequired=bool(cov.get("priorAuthRequired", False)),
                    requiredDocs=cov.get("requiredDocs") or [],
                    visitLimit=cov.get("visitLimit"),
                    episodeDays=cov.get("episodeDays"),
                    notes=cov.get("notes"),
                )
    logger.info("Loaded Neo4j insurance graph (%s plans)", len(data["plans"]))


async def load_neo4j_medications() -> int:
    """Load Medication nodes and bidirectional CONTRAINDICATED_WITH edges."""
    rows = _load_json("medications_reference.json")
    driver = get_neo4j()
    async with driver.session() as session:
        await session.run("MATCH ()-[r:CONTRAINDICATED_WITH]->() DELETE r")
        for med in rows:
            await session.run(
                """
                MERGE (m:Medication {genericName: $genericName})
                SET m.name = $name,
                    m.category = $category,
                    m.minDose = $minDose,
                    m.maxDose = $maxDose,
                    m.unit = $unit,
                    m.commonDoses = $commonDoses
                """,
                genericName=med["genericName"],
                name=med["name"],
                category=med["category"],
                minDose=med["minDose"],
                maxDose=med["maxDose"],
                unit=med["unit"],
                commonDoses=med.get("commonDoses") or [],
            )
        for med in rows:
            for contra in med.get("contraindications", []):
                other = contra["genericName"]
                severity = contra.get("severity", "moderate")
                reason = contra.get("reason", "")
                # bidirectional
                await session.run(
                    """
                    MATCH (a:Medication {genericName: $a})
                    MATCH (b:Medication {genericName: $b})
                    MERGE (a)-[r:CONTRAINDICATED_WITH]->(b)
                    SET r.severity = $severity, r.reason = $reason
                    """,
                    a=med["genericName"],
                    b=other,
                    severity=severity,
                    reason=reason,
                )
                await session.run(
                    """
                    MATCH (a:Medication {genericName: $a})
                    MATCH (b:Medication {genericName: $b})
                    MERGE (b)-[r:CONTRAINDICATED_WITH]->(a)
                    SET r.severity = $severity, r.reason = $reason
                    """,
                    a=med["genericName"],
                    b=other,
                    severity=severity,
                    reason=reason,
                )
    logger.info("Loaded Neo4j Medication nodes: %s", len(rows))
    return len(rows)


async def print_summary() -> None:
    """Log Postgres row counts and Neo4j node/rel counts."""
    Session = get_sessionmaker()
    async with Session() as session:
        tables = [
            "caregivers",
            "caregiver_certifications",
            "caregiver_service_areas",
            "caregiver_availability",
            "service_areas",
            "insurance_contracts",
            "referral_sources",
            "intake_records",
            "documents",
            "document_pages",
            "call_records",
            "follow_up_actions",
        ]
        for table in tables:
            result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
            count = result.scalar_one()
            logger.info("Postgres %s: %s", table, count)

    driver = get_neo4j()
    async with driver.session() as session:
        labels = [
            "Diagnosis",
            "ServiceType",
            "CertificationType",
            "Payer",
            "InsurancePlan",
            "Medication",
        ]
        for label in labels:
            result = await session.run(f"MATCH (n:{label}) RETURN count(n) AS c")
            record = await result.single()
            logger.info("Neo4j %s: %s", label, record["c"])

        for rel in [
            "REQUIRES",
            "NEEDS_CERTIFICATION",
            "UNDER_PAYER",
            "COVERS",
            "CONTRAINDICATED_WITH",
        ]:
            result = await session.run(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS c")
            record = await result.single()
            logger.info("Neo4j %s: %s", rel, record["c"])

    redis = get_redis()
    pong = await redis.ping()
    logger.info("Redis PING: %s", pong)


async def run_critical_traversal() -> bool:
    """Verify Z96.641 / MCARE_A demo graph paths."""
    driver = get_neo4j()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (d:Diagnosis {icdCode: 'Z96.641'})-[r:REQUIRES]->(s:ServiceType)
            OPTIONAL MATCH (s)-[n:NEEDS_CERTIFICATION]->(c:CertificationType)
            RETURN s.name AS service, r.priority AS priority,
                   collect(DISTINCT c.name) AS certs, collect(DISTINCT n.either) AS either_flags
            ORDER BY s.name
            """
        )
        services = {rec["service"]: rec async for rec in result}
        logger.info("Critical diagnosis traversal: %s", services)

        result2 = await session.run(
            """
            MATCH (p:InsurancePlan {code: 'MCARE_A'})-[cov:COVERS]->(s:ServiceType)
            WHERE s.name IN ['skilled_nursing', 'physical_therapy']
            RETURN s.name AS service, cov.priorAuthRequired AS priorAuth,
                   cov.requiredDocs AS docs
            ORDER BY s.name
            """
        )
        coverage = {rec["service"]: rec async for rec in result2}
        logger.info("Critical coverage traversal: %s", coverage)

    ok = (
        "skilled_nursing" in services
        and "physical_therapy" in services
        and "skilled_nursing" in coverage
        and "physical_therapy" in coverage
        and coverage["skilled_nursing"]["priorAuth"] is False
        and coverage["physical_therapy"]["priorAuth"] is False
    )
    if ok:
        docs = set(coverage["skilled_nursing"]["docs"] or [])
        required = {
            "physician_orders",
            "face_to_face_encounter",
            "homebound_certification",
        }
        ok = required.issubset(docs)
    logger.info("Critical traversal PASS=%s", ok)
    return ok


async def main() -> None:
    """Seed both databases from JSON files."""
    settings = get_settings()
    logger.info("Seeding against Postgres %s / Neo4j %s", settings.postgres_db, settings.neo4j_uri)
    await init_all_dbs()
    try:
        await apply_neo4j_constraints()
        try:
            await load_service_areas()
        except Exception:
            logger.exception("load_service_areas failed")
        try:
            await load_insurance()
        except Exception:
            logger.exception("load_insurance failed")
        try:
            await load_referral_sources()
        except Exception:
            logger.exception("load_referral_sources failed")
        try:
            await load_caregivers()
        except Exception:
            logger.exception("load_caregivers failed")
        try:
            await load_neo4j_diagnoses()
            await load_neo4j_diagnosis_map()
            await load_neo4j_insurance()
            await load_neo4j_medications()
        except Exception:
            logger.exception("Neo4j load failed")
        await print_summary()
        await run_critical_traversal()
    finally:
        await close_all_dbs()


if __name__ == "__main__":
    asyncio.run(main())
