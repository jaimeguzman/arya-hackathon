# BACKLOG — Production Readiness Checklist

Derived from [`WORKFLOW.md`](../WORKFLOW.md) (both entry paths, decision engine, follow-up, dashboard) and cross-checked against the actual repo state (`feature_list.json` — 22/115 features passing as of 2026-07-11, session 11 — plus the committed code in `apis/`, `apps/`, `ai-agents/`, `infra/`).

Legend: `[x]` = implemented AND verified (tests passing) in the canonical tree (`apis/` + `ai-agents/` + `apps/` + `infra/`). Work that exists only in the autonomous agent's `local/` sandbox is NOT checked here — it collapses into the canonical tree at merge time per [`MERGE_DAY_RECONCILIATION.md`](MERGE_DAY_RECONCILIATION.md).

## 1. Platform / scaffolding

- [x] FastAPI backend skeleton: app factory, env settings, `/health` endpoint
- [x] React dashboard scaffold (Vite + TypeScript) with dev/build/lint/type-check scripts
- [x] Marketing landing page (Next.js)
- [ ] `infra/docker-compose.yml` with Postgres, Neo4j, Redis up and verified (blocked: Docker daemon unavailable in the agent's environment; `infra/neo4j/` and `infra/postgres/` exist but are uncommitted)
- [ ] PostgreSQL schema migrations applied and seeded in the canonical tree
- [ ] Neo4j knowledge graph seeded (diagnosis → service → certification → caregiver → area)
- [ ] Redis wired for call-session state in a deployed environment (currently in-process fallback)
- [ ] ElevenLabs account, agent, phone number, and webhook provisioning (Twilio → ElevenLabs migration, [`ELEVENLABS_MIGRATION.md`](ELEVENLABS_MIGRATION.md) Task 3)

## 2. Safety guarantees (must-have.md Part 1 — all six, as code)

- [x] #1 Fake data only — `is_synthetic` enforced on every DB write + boot-abort on non-allowlisted DB URL
- [x] #2 Tokenize → LLM → rehydrate wrapper; single LLM entry point (raw PII never reaches the LLM)
- [x] #3 `check_eligibility()` is deterministic code, never LLM-decided
- [x] #4 Consent gather is the first node of every call flow
- [x] #5 Banned-phrase filter via `SafeResponse` before TTS
- [x] #6 No silent call drop — every failure degrades to spoken human handoff
- [x] CI safety suite gates the build (`make safety`)

## 3. Path A — Voice Agent

> Migration in progress: Twilio → ElevenLabs Agents ([`ELEVENLABS_MIGRATION.md`](ELEVENLABS_MIGRATION.md)). Checked voice items below were verified on the ConversationRelay path; each must be re-verified on the ElevenLabs path before the demo (Task 1).

- [x] Twilio ConversationRelay WebSocket handler (`/twilio/conversation-relay`) — to be replaced by `apis/api_elevenlabs/`
- [ ] ElevenLabs webhook / Custom LLM call path with HMAC signature validation, all 6 safety gates re-verified
- [x] Consent gather: AI + recording disclosure, yes/no branch, persisted consent flag
- [x] Caller-type detection routing to Provider / Family / Patient modes
- [x] Ambiguous / low-confidence caller-type handling
- [x] Mid-call mode switch when caller type becomes clearer
- [x] Provider mode: clinical structured intake (name → DOB → diagnosis → insurance → zip) with real-time mid-call eligibility decision
- [ ] Family mode: compassionate plain-language flow, preliminary check only, coordinator-follows-up closing (in progress — `family_intake.py` exists, not yet verified/passing)
- [ ] Patient mode: slower pacing, explains physician-order requirement, handles confusion
- [ ] Outbound mode: single-mission calls (chase document, verify detail, schedule visit) re-entering the same safety-gated flow
- [ ] Call transcript capture persisted per call
- [ ] Live end-to-end call verified on a real ElevenLabs number ("hello to done" demo requirement)

## 4. Path B — Document Pipeline (7 layers)

- [ ] Layer 1 — PDF ingestion + preprocessing (deskew, denoise, scan vs digital detection)
- [ ] Layer 2 — Page classification (order / insurance card / discharge summary / junk)
- [ ] Layer 3 — Extraction routing (rules for clean digital, vision for degraded scans)
- [ ] Layer 4 — Extraction into structured JSON
- [ ] Layer 5 — Agentic review loop: Validation → Correction → Cross-Reference agents
- [ ] Layer 6 — Completeness check producing a gap list
- [ ] Layer 7 — Confidence scoring: auto-populate high, flag medium, withhold low for voice verification
- [ ] All 3 sample fax PDFs process end-to-end; REF-1003's OCR ambiguities (NPI "1245O78823", dosage "200mg") flagged, never silently auto-populated
- [ ] Pipeline output feeds the same `POST /eligibility-check` as Path A

## 5. Eligibility decision engine

- [x] `EligibilityResult` model: exactly ACCEPT / DECLINE / NEEDS_MORE_INFO with reasons
- [x] Service area check against agency zip list
- [x] Insurance check against payer/plan contracts (fuzzy plan match)
- [x] Coverage rules: plan covers service type + prior-auth requirements
- [x] Decision bias: DECLINE only on black-and-white facts, otherwise NEEDS_MORE_INFO
- [x] Write isolation: only the Eligibility Agent writes eligibility decisions
- [x] `POST /eligibility-check` endpoint returns status with reasons
- [ ] Caregiver availability / certification check via Neo4j traversal (blocked on Docker/Neo4j; `knowledge_graph.py` uncommitted work in flight)
- [ ] Sub-3-second decision verified against the 4 sample referral scenarios with live databases

## 6. Orchestrator + Follow-up Agent

- [ ] Orchestrator state machine in the canonical tree: received → processing → eligibility → decision → follow-up (done in `local/` sandbox only; migrates at merge day)
- [ ] Follow-up Agent in `services/`: confirmation via ElevenLabs outbound call after every intake (SMS replaced per migration decision)
- [ ] Outbound retry logic: voicemail/no-answer → retry in 2 hours
- [ ] Escalation to human coordinator after 3 failed contact attempts (never retries forever)
- [ ] ElevenLabs outbound-call client behind the notification contract

## 7. Dashboard

> **Team decision 2026-07-11 (option A):** `local/frontend` (the teammate's React dashboard) is the demo dashboard, served on :5174 against her backend on :8001. `apps/dashboard` is retired — its API contract (`local/backend/api/app.py`, `/referrals` on :8010) was removed by her final-workflow refactor and no backend serves it; decide at merge day whether to adapt or delete it. Known one-line fix pending on her side: `local/frontend/src/api/client.js:64` hardcodes `http://localhost:8000` for the health check in dev, so the "API" pill shows offline when her backend runs on :8001.

- [ ] Referral list with live status per referral
- [ ] Per-field confidence scores displayed
- [ ] Full call transcript view
- [ ] Gap list per referral
- [ ] Caregiver match shown with reasoning
- [ ] Dashboard reads from real endpoints (not mocks)

## 8. Production readiness / compliance gates

- [ ] Merge-day reconciliation executed (`local/` ↔ canonical tree, single seed-data source) per [`MERGE_DAY_RECONCILIATION.md`](MERGE_DAY_RECONCILIATION.md)
- [ ] `WORKFLOW.md` progress tables re-synced to reality (currently stale: Voice Agent listed "not started" while modes 40–45 are passing)
- [ ] Full demo rehearsal against `must-have.md` Part 1 checklist before any test/demo call
- [ ] Feature set checked against PROJECT.md Compliance Checklist + Judging Criteria
- [ ] Twilio → ElevenLabs migration completed and Twilio code path decommissioned (`docs/TWILIO_DECOMMISSION.md`; sponsor-prize eligibility knowingly forgone per team decision 2026-07-11)
- [ ] Load/reliability sanity check: webhook error handling, timeouts, no unhandled 500s on the call path
