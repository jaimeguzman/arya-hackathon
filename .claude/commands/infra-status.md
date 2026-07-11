---
description: Show the status of the local stack — databases, backend, dashboard, landing — with health checks
allowed-tools: Bash(docker:*), Bash(curl:*), Bash(lsof:*)
---

Report the current state of the local development stack (read-only — change nothing):

1. `docker ps` — postgres (5432), neo4j (7474/7687), redis (6379): running? healthy?
2. `curl -s -m 3 http://localhost:8000/health` — FastAPI backend up?
3. `lsof -iTCP:5173 -sTCP:LISTEN` + `curl -s -m 3 -o /dev/null -w "%{http_code}" http://localhost:5173` — dashboard.
4. Same for the landing page on port 3100.
5. If the backend is up, also probe the key endpoints and report their status codes:
   - `POST /eligibility-check` with a minimal valid JSON body
   - `POST /elevenlabs/custom-llm/v1/chat/completions` without a Bearer token (expected: 403 — proves auth is on)

Output a single table: service | port | state | note. End with a one-line verdict of what is testable right now and the exact command to start anything that is down (`/infra-up`).
