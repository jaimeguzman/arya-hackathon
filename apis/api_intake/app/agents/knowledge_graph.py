"""Neo4j knowledge-graph traversal for the Eligibility Agent.

Implements the PROJECT.md Feature 3 path traversal:
diagnosis -> required service -> required certification -> caregiver -> area.

Graph is seeded by infra/neo4j/load_seed.py from the canonical datasets.
Every function degrades to None on any connection/driver failure so the
caller can fall back to the JSON reference mapping — the demo never blocks
on Neo4j being up (no silent call drop, guarantee 6 spirit).
"""

import logging
from functools import lru_cache

from app.config import get_settings

logger = logging.getLogger("intakeai.agents.knowledge_graph")

_QUERY_CAREGIVERS_FOR_DIAGNOSIS = """
MATCH (d:Diagnosis {icd10: $icd10})-[:REQUIRES]->(s:ServiceType),
      (d)-[:REQUIRES_CERTIFICATION]->(ct:CertificationType),
      (c:Caregiver)-[h:HAS_CERTIFICATION]->(ct),
      (c)-[:SERVES_AREA]->(:ServiceArea {zip: $zip})
WHERE c.status = 'active'
  AND c.type IN s.roles
  AND c.current_patient_load < c.max_capacity
  AND (h.expiry_date IS NULL OR date(h.expiry_date) >= date())
RETURN DISTINCT c.id AS caregiver_id, s.id AS service_id
"""

_QUERY_SERVICES_FOR_DIAGNOSIS = """
MATCH (d:Diagnosis {icd10: $icd10})-[:REQUIRES]->(s:ServiceType)
RETURN s.id AS service_id
"""


@lru_cache
def _driver():
    """Cached driver, or None when Neo4j is not configured/reachable."""
    settings = get_settings()
    if not settings.neo4j_uri or not settings.neo4j_password:
        return None
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        driver.verify_connectivity()
        return driver
    except Exception as exc:  # noqa: BLE001 — any failure means JSON fallback
        logger.warning("Neo4j unavailable, using JSON mapping fallback: %s", exc)
        return None


def traverse_caregivers_for_diagnosis(icd10: str, patient_zip: str) -> dict | None:
    """Graph traversal returning {'caregiver_ids': [...], 'service_ids': [...]}.

    Returns None when Neo4j is unavailable (caller falls back to JSON).
    """
    driver = _driver()
    if driver is None:
        return None
    try:
        with driver.session() as session:
            records = list(
                session.run(_QUERY_CAREGIVERS_FOR_DIAGNOSIS, icd10=icd10, zip=patient_zip)
            )
            services = list(session.run(_QUERY_SERVICES_FOR_DIAGNOSIS, icd10=icd10))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Neo4j traversal failed, using JSON fallback: %s", exc)
        return None
    return {
        "caregiver_ids": sorted({record["caregiver_id"] for record in records}),
        "service_ids": [record["service_id"] for record in services],
    }
