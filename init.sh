#!/usr/bin/env bash
# IntakeAI — local development environment bootstrap.
# Usage: ./init.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo "== IntakeAI init =="

# 1. Environment file check (never create/modify .env automatically)
if [ ! -f .env ]; then
  echo "NOTE: .env not found. Copy .env.example to .env and fill in your values:"
  echo "  cp .env.example .env"
fi

# 2. Infrastructure: PostgreSQL+pgvector, Neo4j, Redis via Docker Compose
if [ -f infra/docker-compose.yml ]; then
  echo "-- Starting databases (postgres, neo4j, redis)..."
  docker compose -f infra/docker-compose.yml up -d postgres neo4j redis || \
    docker compose -f infra/docker-compose.yml up -d
else
  echo "WARN: infra/docker-compose.yml not found yet — skipping database startup."
fi

# 3. Backend (FastAPI) dependencies
if [ -f apis/requirements.txt ] || [ -f apis/pyproject.toml ]; then
  echo "-- Installing backend dependencies..."
  python3 -m venv apis/.venv 2>/dev/null || true
  # shellcheck disable=SC1091
  source apis/.venv/bin/activate
  pip install --quiet --upgrade pip
  if [ -f apis/requirements.txt ]; then pip install --quiet -r apis/requirements.txt; fi
  if [ -f apis/pyproject.toml ]; then pip install --quiet -e apis; fi
  deactivate
else
  echo "WARN: no backend dependency manifest in apis/ yet — skipping."
fi

# 4. Database migrations and seeds
if [ -d infra/migrations ]; then
  echo "-- Apply PostgreSQL migrations with: psql \"\$DATABASE_URL\" -f infra/migrations/*.sql"
fi
if [ -d infra/neo4j ]; then
  echo "-- Load Neo4j seeds with: cypher-shell -a \"\$NEO4J_URI\" -f infra/neo4j/seed.cypher"
fi

# 5. Frontend (React dashboard) dependencies
if [ -f apps/dashboard/package.json ]; then
  echo "-- Installing dashboard dependencies..."
  (cd apps/dashboard && npm install --silent)
else
  echo "WARN: apps/dashboard not scaffolded yet — skipping."
fi

echo ""
echo "== Next steps =="
echo "  Backend API:   cd apis && source .venv/bin/activate && uvicorn app.main:app --reload  -> http://localhost:8000 (health: /health)"
echo "  Dashboard:     cd apps/dashboard && npm run dev  -> http://localhost:5173"
echo "  Neo4j browser: http://localhost:7474"
echo "  Twilio webhook: run 'ngrok http 8000' and set the voice webhook to <ngrok-url>/twilio/conversation-relay"
echo "  Safety suite:  cd apis && pytest tests/test_safety_layer.py  (must pass before any demo call)"
echo "== Done =="
