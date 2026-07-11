# Workflow — IntakeAI End to End (Voice + Fax)

Plain-English, step-by-step walkthrough of how a referral moves through the system, covering both entry channels (phone call and fax/PDF) and every situation the system needs to handle. This is a companion to the other docs, not a new source of truth:

- [`PROJECT.md`](PROJECT.md) remains the product/architecture source of truth.
- [`must-have.md`](must-have.md) remains the safety authority (the 6 non-negotiable guarantees referenced throughout this file).
- [`architecture.md`](architecture.md) has the technical diagrams (mermaid flowcharts/sequence diagrams) this file narrates in prose.

If this file and any of the above ever disagree, `PROJECT.md` > `must-have.md` > `architecture.md` win, in that order — update this file to match, not the other way around.

---

## Progress Report & Parallel Work Plan (snapshot: 2026-07-11)

This section is a point-in-time status snapshot, not an evergreen part of the workflow narration below — update or replace it as work lands, don't let it drift into fiction. Status is checked against this file's own architecture (Orchestrator, Voice Agent, Document Pipeline, Eligibility Agent, Follow-up Agent), not any external phase numbering.

### What's done

| Component | Status | Evidence |
|---|---|---|
| **Data layer** (PostgreSQL schema, Neo4j constraints, Redis, seed data, loader script, DB connection utils) | ✅ Done | `local/` — docker-compose, `postgres_init.sql` (12 tables), `neo4j_seed.cypher`, `sample_data.py` loader, `database.py` (SQLAlchemy async + Neo4j + Redis clients), `config.py`. Verified per git log ("phase-1: verify all databases connected and seeded") |
| **Orchestrator (LangGraph)** (Task 4) | ✅ Done | `local/backend/orchestrator/` — `graph.py` (`intake_received → check_eligibility → decide → followup_{accept,decline,needs_info} → END`), `state.py`, `eligibility.py`, `demo.py`. Runs with no DB/Twilio (JSON fallback). |
| **Eligibility ↔ Orchestrator connection** (Task 3 + Task 4) | ✅ Done | The team's deterministic `check_eligibility()` core (vendored to `local/backend/orchestrator/eligibility_core.py` from `develop:apis/api_intake/app/safety/eligibility.py`) is now driven by a real data-fetch layer (`eligibility_data.py` — Postgres+Neo4j queries with JSON fallback) via `RealEligibilityClient`, injected as the graph's default. 25 orchestrator+followup tests green offline. |
| **Follow-up Agent** (Task 4) | ✅ Done (against stubs) | `local/backend/followup/` — `agent.py` (decision→action + bounded retry/escalation, must-have.md #6), `notifications.py` (Twilio contract + stub). |
| **Dashboard API** (Task 4) | ✅ Done | `local/backend/api/` — FastAPI (`app.py`) runs a referral through the orchestrator and persists to PostgreSQL `intake_records` (`referral_store.py`, additive `followup`/`trace` columns via idempotent migration); `GET/POST /referrals`, `/referrals/{id}`, `/health`. Needs Docker up for live data. |
| **Dashboard UI** (Task 4) | ✅ Done | `apps/dashboard/` — React+TS+Vite. Referral list, detail panel (eligibility reasons, gaps, follow-up, trace, facts), new-referral modal with presets. Builds/type-checks/lints clean; renders with graceful loading/empty/error states. Live data pending Docker. Extraction-confidence + transcript sections are labeled placeholders (Tasks 2 & 1). |

### What's pending

| Component | Status |
|---|---|
| FastAPI backend skeleton (health check, WebSocket stub) | ⏳ Partial — a FastAPI app with `/health` + referral endpoints exists (`local/backend/api/app.py`, dashboard API). The Twilio WebSocket endpoint (Voice Agent) is still Task 1's, not built. |
| Eligibility Agent | ✅ Connected — see "Eligibility ↔ Orchestrator connection" above. Deterministic decision core + Postgres/Neo4j data-fetch layer (`eligibility_data.py`) with JSON fallback. Real DB path needs Docker up to verify live; JSON path verified offline. A `POST /eligibility-check` HTTP endpoint is still not exposed (orchestrator calls it in-process). |
| Document Pipeline (7 layers) | ❌ Not started — test fixtures exist (`data/synthetic/referral_faxes/`, 3 real fax PDFs), no extraction/validation/correction code |
| Voice Agent (Twilio ConversationRelay, consent gather, tokenize/rehydrate, banned-phrase filter, provider/family/outbound modes) | ❌ Not started |
| Twilio wiring for Follow-up Agent | ⏳ Contract defined by Task 4 (`local/backend/followup/notifications.py` — `NotificationClient`); real Twilio client not built. Drop-in via `FollowUpAgent(notifier=...)`. |
| Guardrail enforcement code (the 6 `must-have.md` safety guarantees as actual code) | ⏳ Partial — #3 (deterministic decision, no LLM) and #6 (bounded retries/escalation) enforced in the orchestrator/follow-up code; the call-path guarantees (#1,#2,#4,#5) still live only in `must-have.md` |
| Dashboard (React) | ✅ Done — see "Dashboard UI" / "Dashboard API" above. Live data needs Docker (Postgres) up. |
| Twilio account/number provisioning | ⚠️ Unknown — `.env.example` has empty Twilio fields, can't verify from the repo; confirm with the team |

### Two conflicts to resolve first (flagged, not silently resolved)

1. **Duplicate seed data, only one copy is real.** [`data/`](data/) (reference/synthetic JSON + fax PDFs) and [`local/data/`](local/data/) (7 JSON files, different names/shape) both exist. **Only `local/data/` is actually loaded into the running databases** — `data/` is currently unused by any code. Reconcile into one source before the Eligibility Agent is built against it.
2. **Folder structure mismatch.** [`architecture.md`](architecture.md#8-proposed-module-layout-not-yet-built--for-file-ownership-planning) §8 proposes code under `apis/`, `ai-agents/`, `infra/`, `apps/`, `services/`. The actual merged code lives under a separate `local/backend/` tree instead. Pick one before more code lands in two places.

### Four parallel tasks

```
Task 1 — Voice Agent

Developer: Person 1
Goal: Build the Twilio ConversationRelay voice handling for all 3 call modes with every safety gate from must-have.md wired in.
Files Owned:
- ai-agents/ (provider/family/outbound prompts + conversation flow specs)
- apis/app/routes/voice.py, apis/app/main.py (FastAPI skeleton + WebSocket endpoint — coordinate with Task 4 on shared main.py structure)
Classes/Functions Owned:
- Consent-gather node, tokenize()/rehydrate() wrapper, filter_response()/speak(), handle_turn() failure-handoff wrapper (must-have.md #6)
Dependencies:
- Task 3's reconciled eligibility-check contract (can build against a mocked response shape in the meantime — don't block)
Implementation Steps:
1. FastAPI skeleton + health check + WebSocket stub for Twilio
2. Consent gather as literal entry point (must-have.md #4)
3. Provider mode, family mode, outbound mode conversation flows
4. Tokenize/rehydrate wrapper (must-have.md #2) + banned-phrase filter (must-have.md #5)
5. Failure-handoff wrapper — every turn caught, never a silent drop (must-have.md #6)
6. Call transcript capture
Documentation To Update: ai-agents/README.md, WORKFLOW.md if the real flow diverges from what's documented
Expected Completion Criteria: A live or /voice/test call completes provider, family, and outbound scenarios end-to-end without the LLM ever seeing raw PII, without any un-filtered response reaching TTS, and without a call ever silently dropping.
```

```
Task 2 — Document Pipeline

Developer: Person 2
Goal: Build the 7-layer extraction pipeline and prove it against the 3 real fax PDFs already in data/synthetic/referral_faxes/.
Files Owned:
- apis/app/routes/documents.py
- Document pipeline module (layers 1-7: ingest, classify, OCR-route, extract, validate/correct/cross-reference, gap-check, confidence-score)
Classes/Functions Owned:
- Validation Agent, Correction Agent, Cross-Reference Agent, confidence scoring
Dependencies:
- Task 3's reconciled reference data (ICD-10 codes, med dosage ranges) for validation lookups
Implementation Steps:
1. PDF ingestion + preprocessing
2. Page classification
3. Dual-path extraction (rules for clean PDFs, vision for REF-1003's degraded scan)
4. Agentic review loop (Validation → Correction → Cross-Reference)
5. Completeness check + gap list
6. Confidence scoring and routing
Documentation To Update: WORKFLOW.md if extraction behavior diverges from the documented 7 layers
Expected Completion Criteria: All 3 sample fax PDFs process end-to-end; REF-1003's intentional OCR ambiguities (NPI "1245O78823", dosage "200mg") get correctly flagged, not silently auto-populated.
```

```
Task 3 — Eligibility Agent + Data Reconciliation (BLOCKING — do first)

Developer: Person 3
Goal: Resolve the two conflicts found above, then build check_eligibility() as deterministic code per must-have.md #3.
Files Owned:
- Reconciliation: decide data/ vs local/data/ as the single source, migrate/delete the loser, update the loader if needed
- Reconciliation: decide local/backend/ vs apis/+infra/ as the real code location, migrate if needed
- Eligibility service + POST /eligibility-check endpoint
Classes/Functions Owned:
- check_eligibility(zip, payer, plan, service_type), generate_agent_response() gate
Dependencies:
- None — this unblocks everyone else, should start immediately
Implementation Steps:
1. Reconcile data/ vs local/data/ (pick one, document the decision in data/README.md)
2. Reconcile folder structure (pick one, update architecture.md §8 to match reality)
3. Neo4j traversal: diagnosis → service → certification → caregiver → area
4. PostgreSQL queries: service area, insurance contract, caregiver availability
5. Accept/decline/needs-more-info logic (bias toward needs-more-info on ambiguity)
6. Unit test: clear-yes, clear-no, ambiguous case (must-have.md #3 CI requirement)
Documentation To Update: data/README.md, architecture.md §8, PROJECT.md build plan
Expected Completion Criteria: check_eligibility() returns correct ACCEPT/DECLINE/NEEDS_MORE_INFO for the 4 sample referral scenarios, in under 3 seconds, and the repo has exactly one seed-data source and one code-location convention.
```

```
Task 4 — Orchestrator + Follow-up Agent + Dashboard scaffold

Developer: Person 4
Goal: LangGraph state machine tying everything together, plus outbound follow-up logic and a minimal dashboard shell.
Files Owned:
- apis/app/agents/orchestrator.py (LangGraph state machine)
- services/ (Follow-up Agent: SMS, retry scheduling, escalation)
- apps/dashboard/ (React shell — can start as static/mock until Tasks 1-3 have real endpoints)
Classes/Functions Owned:
- Orchestrator routing logic, Follow-up Agent (retry-in-2-hours, escalate-after-3-attempts)
Dependencies:
- Task 3's /eligibility-check endpoint contract (agree on the shape early, build against a stub if not ready)
Implementation Steps:
1. LangGraph state machine: received → processing → eligibility → decision → follow-up
2. Wire routing: document pipeline output triggers eligibility, eligibility triggers voice/follow-up actions
3. Follow-up Agent: SMS via Twilio, retry logic, 3-attempt escalation
4. Dashboard shell: referral list, status, confidence scores, gap list (polling a mock endpoint is fine initially)
Documentation To Update: WORKFLOW.md if orchestration logic diverges from the 3 documented flows
Expected Completion Criteria: A referral fed into the orchestrator (from either mock voice or mock fax data) reaches a final status with the correct follow-up action triggered, and the dashboard shows it.
```

Task 3 should start first since it unblocks the data-source question everyone else depends on — but Tasks 1, 2, and 4 can all start immediately against mocked/stubbed contracts without waiting.

---

## The one-sentence architecture

One "brain" (the Orchestrator) never talks to anyone or reads anything directly — it routes work to four specialists (Voice Agent, Document Pipeline, Eligibility Agent, Follow-up Agent) and makes the final call using deterministic code, never the AI's opinion.

## Two ways a referral enters the system

```
Path A: Someone calls  ──────────────────────────────┐
                                                      ├──> Orchestrator ──> Eligibility Agent ──> Decision ──> Follow-up
Path B: A fax/PDF arrives ──> Document Pipeline ──────┘
```

Both paths end up at the exact same decision engine. The only difference is *how the data gets collected*.

---

## PATH A — Someone calls (patient, family, or provider)

**Step 1 — Call connects.** Twilio answers, 24/7. Nobody is ever sent to voicemail.

**Step 2 — Consent gather (always first, no exceptions).**
> "This call may be recorded and is handled by an AI system. Is that okay?"
- **No** → transferred to a human, or ends gracefully. Nothing else runs.
- **Yes** → consent logged, conversation proceeds.

**Step 3 — Voice Agent detects who's calling and switches mode:**

| Caller | Mode | Behavior |
|---|---|---|
| Discharge planner / physician | **Provider mode** | Clinical, efficient, structured questions (diagnosis, insurance, zip, urgency) |
| Family member | **Family mode** | Compassionate, plain language, no jargon, gentle pacing |
| Patient themselves | **Patient mode** | Slower pace, explains a physician order is needed for skilled care, handles confusion patiently |
| Outbound call *from* the agency (chasing a gap) | **Outbound mode** | Has one specific mission: get a missing document, verify a detail, or schedule a visit |

**Step 4 — The conversation, turn by turn, every single turn passes through 4 safety gates:**

1. Caller speaks → Voice Agent extracts structured data (name, DOB, diagnosis, zip, insurance...)
2. **Tokenize**: raw transcript → identifiers replaced with placeholders (`{{PATIENT_NAME}}`) *before* it ever reaches the LLM
3. **Deterministic eligibility check** runs in parallel on the structured fields (zip, payer, service type — not names): `check_eligibility()` returns exactly one of **ACCEPT / DECLINE / NEEDS_MORE_INFO** with reasons. This is plain code — the LLM never decides this.
4. LLM drafts a response (still tokenized) → **rehydrated** with real values inside the backend → passed through the **banned-phrase filter** (blocks "guaranteed," "100%," "confirmed appointment") → only then can it reach text-to-speech

**Step 5 — If anything goes wrong mid-call** (an error, a timeout, or the agent can't understand the caller after repeated tries) → same handoff as a consent "no": *"Let me connect you with a coordinator"* + human transfer or scheduled callback. **No call ever ends in silence** (`must-have.md` guarantee #6).

**Step 6 — Voice Agent speaks the approved response.** Always framed provisionally, never a hard promise — a human coordinator is always named as the final confirmer.

**Step 7 — Call ends → Follow-up Agent takes over automatically:**
- Creates/updates the intake record with a status
- Sends an SMS/email confirmation
- If something's missing → schedules a retry or triggers an **outbound call** (which re-enters this exact same safety-gated flow — there's no separate unguarded path)
- After **3 failed contact attempts**, escalates to a human coordinator — never retries forever

---

## PATH B — A fax/PDF referral arrives

This never touches a phone call. It's the Document Pipeline's job alone.

1. **Layer 1 — Preprocess**: deskew, denoise, detect if pages are scanned images or clean digital text
2. **Layer 2 — Classify each page**: physician order? Insurance card? Discharge summary? Junk cover sheet?
3. **Layer 3 — Route extraction**: clean digital → rule-based (Docling); messy scan/handwriting → AI vision (Gemini)
4. **Layer 4 — Extract into structured JSON**
5. **Layer 5 — Three-agent check**: Validation (is this ICD code real? Is this NPI valid? Is this drug dose sane?) → Correction (fixes obvious OCR errors, e.g. "M17.1I" → "M17.11") → Cross-Reference (does the patient's name match across all pages?)
6. **Layer 6 — Completeness check**: builds a gap list of what's missing
7. **Layer 7 — Confidence scoring**: high confidence auto-populates; medium auto-populates but gets flagged; low confidence is **withheld** and added to a list for the Voice Agent to verify by phone later

Once this is done, the structured, checked data goes to the **same Eligibility Agent** as a phone call would — and if anything's missing (e.g. no face-to-face documentation), the Orchestrator triggers an **outbound call** to the hospital and/or an outbound call to the patient/family, both going through Path A's exact same safety-gated flow.

Full detail per layer, including worked correction examples: [`PROJECT.md` — Document Pipeline](PROJECT.md#document-pipeline-7-layers--agentic-review-loop).

---

## The single decision engine both paths feed into

`check_eligibility()` — plain code, not AI:

```
zip served? + insurance accepted? + caregiver with right cert available?
  all yes                                     → ACCEPT
  zip or insurance fails (hard, unambiguous)   → DECLINE (fast, so the family/planner can get help elsewhere sooner)
  anything ambiguous (e.g. caregiver maybe available) → NEEDS_MORE_INFO → escalate to human, don't guess
```

This is deliberately biased toward *NEEDS_MORE_INFO over DECLINE* whenever there's ambiguity — declining only fires on two black-and-white facts, never a judgment call.

---

## Situation-handling cheat sheet

| Situation | What happens |
|---|---|
| Discharge planner calls, everything checks out | Real-time ACCEPT on the call, SMS confirmation sent, intake record created |
| Discharge planner calls, missing a document | ACCEPT + "we'll need the F2F documentation" + follow-up tracked |
| Wrong zip / insurance not accepted | Fast, honest DECLINE — so they can call another agency immediately instead of waiting |
| Family calls at midnight | Preliminary check only, compassionate tone, always ends in "a coordinator follows up," never a firm commitment |
| Patient self-refers | Explains a physician order is required, offers to help coordinate with their doctor |
| Fax has messy/garbled OCR fields | Never auto-populated — added to gap list, Voice Agent verifies it on the next call |
| Call goes to voicemail (outbound) | Retry in 2 hours |
| SMS gets no response | Follow up next morning |
| 3 failed contact attempts | Escalate to human coordinator |
| Voice Agent errors, times out, or can't understand caller | Same handoff as consent "no" — spoken fallback + human transfer, never silence |
| Caller says "no" to consent | Transfer to human or graceful end — no data collection happens |

---

## What ties it all together

A real-time **dashboard** shows every referral's status, confidence scores per field, the full call transcript, the gap list, and which caregiver was matched (and why) — so a human coordinator always has full visibility and can step in at any point, on any referral, from either channel.

---

## Where to look for more detail

| Question | Look in |
|---|---|
| Exact diagrams (mermaid flowcharts/sequence diagrams) for each flow described here | [`architecture.md`](architecture.md) |
| Why this product exists, full data model, tech stack | [`PROJECT.md`](PROJECT.md) |
| The 6 non-negotiable safety guarantees and their code-enforcement pattern | [`must-have.md`](must-have.md) Part 1 |
| Seed/reference data (ICD-10 subset, caregiver roster, payer rules, sample referrals) | [`data/README.md`](data/README.md) |
| Team collaboration protocol, file ownership rules | [`CLAUDE.md`](CLAUDE.md) |
