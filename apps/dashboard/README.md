# IntakeAI — Intake Dashboard (Task 4)

React + TypeScript + Vite dashboard for the intake pipeline. Shows every
processed referral, its eligibility decision/status, gaps, follow-up action, and
the orchestrator trace. Data comes from the dashboard API
(`local/backend/api/app.py`), which persists processed referrals to PostgreSQL
`intake_records`.

## Architecture

```
apps/dashboard (this)  ──/api proxy──►  local/backend/api/app.py (:8010)
        React UI                          FastAPI: runs orchestrator, reads/writes intake_records
                                                │
                                          PostgreSQL intake_records
```

The UI never touches the DB directly (per apps/CLAUDE.md) — only the API. The
`/api` path is proxied to the backend by Vite (`vite.config.ts`), so there's no
CORS and no hardcoded API URL. Override the target with `VITE_API_TARGET`.

## Run it (full stack)

The dashboard shows data only when the backend + PostgreSQL are up (the chosen
store). With Docker down it renders but surfaces an "API unreachable" state.

```bash
# 1. databases (from repo root)
cd local && docker compose up -d
./scripts/seed_databases.sh                     # Phase 1 reference/roster data

# 2. dashboard API
source .venv/bin/activate && export PYTHONPATH="$PWD"
python -m backend.api.seed_referrals            # optional: 4 demo referrals
uvicorn backend.api.app:app --reload --port 8010

# 3. dashboard UI (separate terminal)
cd ../apps/dashboard
npm install
npm run dev                                     # http://localhost:5173
```

## What it displays

| Section | Source | Status |
|---|---|---|
| Referral list (status, decision, source, gaps, time) | orchestrator + intake_records | live |
| Eligibility decision + reasons | RealEligibilityClient (team's deterministic core) | live |
| Gaps / missing documents | eligibility.missing_documents | live |
| Follow-up action (type, intent, schedule) | Follow-up Agent | live |
| Pipeline trace | orchestrator | live |
| Extraction confidence scores | Document Pipeline (Task 2) | placeholder |
| Call transcript | Voice Agent (Task 1) | placeholder |
| Caregiver match details | Eligibility (availability only for now) | placeholder |

Placeholders are clearly labeled in the UI — no fake/empty data hiding missing
state (per apps/CLAUDE.md).

## Scripts

- `npm run dev` — dev server (HMR)
- `npm run build` — type-check + production build
- `npm run type-check` — `tsc --noEmit`
- `npm run lint` — oxlint

## Files

- `src/api.ts` — typed client + response types for the dashboard API
- `src/App.tsx` — the dashboard (list, detail panel, new-referral modal)
- `src/App.css` / `src/index.css` — styling + design tokens (light/dark aware)
- `vite.config.ts` — `/api` proxy to the backend
