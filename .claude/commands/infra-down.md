---
description: Stop the local stack — backend, dashboard, landing, and (only if confirmed) the Docker databases
allowed-tools: Bash(docker:*), Bash(docker compose:*), Bash(lsof:*), Bash(kill:*), Bash(curl:*)
---

Stop the local development stack:

1. Find and stop the app processes (never `kill -9` first; use plain `kill` and re-check):
   - FastAPI/uvicorn on port 8000
   - Vite dashboard on port 5173
   - Next.js landing on port 3100
   Identify PIDs with `lsof -iTCP:<port> -sTCP:LISTEN -P -n`. Only kill processes that are clearly uvicorn/node dev servers for this repo — show the process name before killing.
2. **Databases**: ask the user before running `docker compose -f local/docker-compose.yml stop` — the autonomous coder agent may be relying on them. Use `stop` (not `down`) so volumes and seeded data are preserved. Never use `down -v`.
3. Print a final status: what was stopped, what was left running and why.

Rules:
- Never modify anything under `local/`.
- Never remove Docker volumes (seeded demo data lives there).
