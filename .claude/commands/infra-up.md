---
description: Bring up the full local stack — databases (Docker), FastAPI backend, dashboard, and landing page
allowed-tools: Bash(docker:*), Bash(docker compose:*), Bash(curl:*), Bash(lsof:*), Bash(npm:*), Bash(../.venv/bin/*), Bash(cd:*)
---

Bring up the entire local development stack, in this order. Skip anything already running (check first, never start a duplicate).

1. **Databases (Docker Compose)** — the only compose file lives in the autonomous agent's workspace; using it read-only is allowed (never edit anything under `local/`):
   - `docker compose -f local/docker-compose.yml up -d`
   - Wait until `docker ps` reports postgres (5432), neo4j (7474/7687), and redis (6379) as `healthy`.
2. **FastAPI backend** (`apis/api_intake`, port 8000):
   - Check `lsof -iTCP:8000 -sTCP:LISTEN` first; if free, run in background from `apis/api_intake`:
     `../.venv/bin/uvicorn app.main:app --port 8000`
   - Verify with `curl -s http://localhost:8000/health` returning 200.
3. **Teammate's backend** (`local/backend`, port 8001 — run without altering her code):
   - Venv: `.temp/local-venv` (create with Python 3.13 if missing — system 3.9 crashes on her `UUID | None` syntax; install her deps manually because `local/requirements.txt` has an unsatisfiable duplicate langgraph pin — use `langgraph>=0.2,<0.4`).
   - From `local/`: `.temp/local-venv/bin/uvicorn backend.main:app --port 8001` in background. Verify `curl http://localhost:8001/api/intake` returns 200.
4. **Demo dashboard** (`local/frontend`, port 5174 — team decision: this replaced the retired `apps/dashboard`):
   - `npm install` inside `local/frontend` if `node_modules/` missing (only allowed write under `local/`).
   - Run with the EXTERNAL config so her code stays untouched: from `local/frontend`, `npm run dev -- --config <repo>/.temp/vite-local-frontend.config.mjs`. If that file is missing (`.temp/` is ephemeral), recreate it: default export with `plugins: [react()]` (react imported by absolute path from `local/frontend/node_modules/@vitejs/plugin-react/dist/index.js`), `server.port: 5174`, and proxy `/api` and `/voice` → `http://localhost:8001`.
   - Known cosmetic issue: the "API" health pill shows offline (her `client.js:64` hardcodes :8000 in dev) — data still flows via the proxy.
5. **Landing** (`apps/landing`, Next.js, port 3100): same pattern — only if not already listening.

Finish by printing a status table: service, port, state, and the URLs to open (API docs `http://localhost:8000/docs`, Neo4j browser `http://localhost:7474`, dashboard `http://localhost:5173`, landing `http://localhost:3100`).

Rules:
- Never modify, stage, or delete anything under `local/` — its compose file is consumed read-only.
- Never touch `.env` files; configuration comes from the environment / `.env.example` reference.
- If a service fails to start, report the actual error output — do not retry blindly more than once.
