#!/usr/bin/env bash
# Phase 1 verification: wait for DBs, seed, print counts, run Cypher gate
set -euo pipefail
LOCAL_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$LOCAL_ROOT"

echo "== Waiting for docker compose health =="
docker compose up -d
for i in $(seq 1 36); do
  healthy=$(docker compose ps --format json 2>/dev/null | grep -c '"Health":"healthy"' || true)
  echo "Healthy check attempt $i"
  if [ "$healthy" -ge 3 ]; then
    break
  fi
  sleep 5
done

if [ ! -f .env ]; then
  cp .env.example .env
fi

echo "== Installing Python deps =="
python -m pip install -q -r requirements.txt

echo "== Running loader =="
export PYTHONPATH="$LOCAL_ROOT"
python -m backend.db.sample_data

echo "== Redis PING =="
docker compose exec -T redis redis-cli ping

echo "== Critical Cypher =="
docker compose exec -T neo4j cypher-shell -u neo4j -p intakeai_dev "
MATCH (d:Diagnosis {icdCode: 'Z96.641'})-[r:REQUIRES]->(s:ServiceType)
OPTIONAL MATCH (s)-[n:NEEDS_CERTIFICATION]->(c:CertificationType)
RETURN d.icdCode, s.name, r.priority, collect(c.name) AS certs;
MATCH (p:InsurancePlan {code: 'MCARE_A'})-[cov:COVERS]->(s:ServiceType)
WHERE s.name IN ['skilled_nursing', 'physical_therapy']
RETURN p.code, s.name, cov.priorAuthRequired, cov.requiredDocs;
"

echo "== PASS: Phase 1 seed verification complete =="
