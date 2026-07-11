"""Neo4j knowledge-graph seed loader.

Loads the canonical datasets (data/reference + data/synthetic — see
data/README.md) into the graph shape from PROJECT.md:

  (Diagnosis)-[:REQUIRES]->(ServiceType)
  (Diagnosis)-[:REQUIRES_CERTIFICATION]->(CertificationType)
  (ServiceType)-[:NEEDS_ROLE]->(role property list on ServiceType)
  (Caregiver)-[:HAS_CERTIFICATION {expiry_date}]->(CertificationType)
  (Caregiver)-[:SERVES_AREA]->(ServiceArea)
  (InsurancePlan)-[:UNDER_PAYER]->(Payer)
  (InsurancePlan)-[:COVERS]->(ServiceType)

The eligibility traversal this enables (PROJECT.md Feature 3):
diagnosis -> service -> certification -> caregiver -> area.

Usage (uses NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD env vars, matching
.env.example; run from the repo root):

    python infra/neo4j/load_seed.py
"""

import json
import os
import sys
from pathlib import Path

from neo4j import GraphDatabase

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = REPO_ROOT / "data" / "reference"
SYNTHETIC_DIR = REPO_ROOT / "data" / "synthetic"


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _require_synthetic(document: dict, path: Path) -> None:
    """Guarantee 1 (must-have.md): only synthetic/reference data enters the system."""
    marker_keys = ("_synthetic_data_notice", "_note")
    if not any(key in document for key in marker_keys):
        raise SystemExit(f"Refusing to load {path}: no synthetic/reference data marker found.")


def load_graph(session) -> dict[str, int]:
    icd10 = _load(REFERENCE_DIR / "icd10_top30_home_health.json")
    mapping_doc = _load(REFERENCE_DIR / "diagnosis_service_certification_mapping.json")
    payer_doc = _load(REFERENCE_DIR / "payer_coverage_rules.json")
    roster_doc = _load(SYNTHETIC_DIR / "caregiver_roster.json")
    agency_doc = _load(REFERENCE_DIR / "agency_configuration.json")
    _require_synthetic(roster_doc, SYNTHETIC_DIR / "caregiver_roster.json")

    session.run("MATCH (n) DETACH DELETE n")

    # Service types (with the caregiver roles that can deliver them).
    session.run(
        """
        UNWIND $services AS svc
        MERGE (s:ServiceType {id: svc.id})
        SET s.label = svc.label, s.roles = svc.base_role
        """,
        services=mapping_doc["service_types"],
    )

    # Diagnoses from the ICD-10 subset (fields: code, description, category).
    session.run(
        """
        UNWIND $rows AS row
        MERGE (d:Diagnosis {icd10: row.code})
        SET d.description = row.description, d.category = row.category
        """,
        rows=icd10["codes"],
    )

    # Diagnosis -> service / certification requirements.
    session.run(
        """
        UNWIND $mappings AS m
        MERGE (d:Diagnosis {icd10: m.icd10})
        WITH d, m
        UNWIND m.required_services AS svc_id
        MATCH (s:ServiceType {id: svc_id})
        MERGE (d)-[:REQUIRES]->(s)
        """,
        mappings=mapping_doc["diagnosis_mappings"],
    )
    session.run(
        """
        UNWIND $mappings AS m
        MATCH (d:Diagnosis {icd10: m.icd10})
        UNWIND m.required_certifications AS cert
        MERGE (c:CertificationType {name: cert})
        MERGE (d)-[:REQUIRES_CERTIFICATION]->(c)
        """,
        mappings=mapping_doc["diagnosis_mappings"],
    )

    # Payers and plans with coverage.
    session.run(
        """
        UNWIND $payers AS p
        MERGE (payer:Payer {name: p.payer})
        WITH payer, p
        UNWIND p.plans AS plan
        MERGE (ip:InsurancePlan {name: plan.plan})
        SET ip.plan_type = plan.plan_type,
            ip.requires_prior_auth = plan.requires_prior_auth,
            ip.requires_homebound_status = plan.requires_homebound_status,
            ip.requires_face_to_face_encounter = plan.requires_face_to_face_encounter
        MERGE (ip)-[:UNDER_PAYER]->(payer)
        WITH ip, plan
        UNWIND plan.covers AS svc_id
        MATCH (s:ServiceType {id: svc_id})
        MERGE (ip)-[:COVERS]->(s)
        """,
        payers=payer_doc["payers"],
    )

    # Service areas from the agency configuration.
    session.run(
        """
        UNWIND $zips AS zip
        MERGE (:ServiceArea {zip: zip})
        """,
        zips=agency_doc["agency"]["service_area_zips"],
    )

    # Caregivers with certifications (expiry on the relationship) and areas.
    session.run(
        """
        UNWIND $caregivers AS cg
        MERGE (c:Caregiver {id: cg.id})
        SET c.name = cg.name, c.type = cg.type, c.status = cg.status,
            c.current_patient_load = cg.current_patient_load,
            c.max_capacity = cg.max_capacity,
            c.is_synthetic = cg.is_synthetic
        WITH c, cg
        UNWIND cg.certifications AS cert
        MERGE (ct:CertificationType {name: cert})
        MERGE (c)-[h:HAS_CERTIFICATION]->(ct)
        SET h.expiry_date = cg.cert_expiry[cert]
        """,
        caregivers=roster_doc["caregivers"],
    )
    session.run(
        """
        UNWIND $caregivers AS cg
        MATCH (c:Caregiver {id: cg.id})
        UNWIND cg.service_zips AS zip
        MERGE (a:ServiceArea {zip: zip})
        MERGE (c)-[:SERVES_AREA]->(a)
        """,
        caregivers=roster_doc["caregivers"],
    )

    counts = {}
    for label in ("Diagnosis", "ServiceType", "CertificationType", "Caregiver",
                  "ServiceArea", "Payer", "InsurancePlan"):
        record = session.run(
            f"MATCH (n:{label}) RETURN count(n) AS c"
        ).single()
        counts[label] = record["c"]
    return counts


def main() -> int:
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")
    if not password:
        print("NEO4J_PASSWORD is required (see .env.example).", file=sys.stderr)
        return 1
    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver.session() as session:
        counts = load_graph(session)
    driver.close()
    print("Neo4j knowledge graph loaded:")
    for label, count in counts.items():
        print(f"  {label}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
