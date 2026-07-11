# Architecture — IntakeAI

This file is the detailed technical architecture reference: diagrams plus numbered step-by-step walkthroughs. It does not override anything — [`PROJECT.md`](PROJECT.md) remains the product and architecture source of truth, [`must-have.md`](must-have.md) remains the safety authority. This file exists to make both easier to build against by turning prose into diagrams a new developer can point at.

If this file and `PROJECT.md` ever disagree, `PROJECT.md` wins — update this file to match, not the other way around.

---

## 1. System overview

```mermaid
flowchart TD
    A["Discharge planner / family / patient"] -->|calls| B["Twilio ConversationRelay"]
    F["Fax / PDF referral"] -->|upload| C["Document upload endpoint"]
    B --> D["Intake Agent Orchestrator (LangGraph)"]
    C --> D
    D --> D1["Voice Agent"]
    D --> D2["Document Pipeline"]
    D --> D3["Eligibility Agent"]
    D --> D4["Follow-up Agent"]
    D1 --> RED[("Redis")]
    D2 --> RED
    D2 --> PG[("PostgreSQL")]
    D3 --> PG
    D3 --> NEO[("Neo4j")]
    D4 --> PG
    D4 --> RED
    D3 --> O1["Accept / decline"]
    D4 --> O2["SMS / email"]
    D4 --> O3["Outbound call via Twilio"]
    D --> O4["Dashboard"]
    PG -.->|referral-source history| D1
```

Steps:

1. A referral enters through one of two channels: a live call/SMS via Twilio, or a fax/PDF upload.
2. Both channels hand off to the Intake Agent Orchestrator (LangGraph state machine) — the only component that makes decisions.
3. The orchestrator delegates to exactly one of four sub-agents depending on what's needed: Voice Agent (talk), Document Pipeline (**read and analyze every fax/PDF here** — this is where all document checking/extraction/validation happens, via the 7-layer pipeline detailed in §4), Eligibility Agent (decide), Follow-up Agent (chase gaps).
4. Sub-agents read/write the data layer (PostgreSQL, Neo4j, Redis) but never decide anything themselves except the Eligibility Agent, whose decision is deterministic code, not an LLM call.
5. Outcomes are one of: accept/decline recorded in PostgreSQL, an SMS/email sent, an outbound call placed back through Twilio, or a dashboard update.
6. PostgreSQL's referral-source history feeds back into the Voice Agent on the next call from the same source — this is caller personalization (Feature 5 in `PROJECT.md`), shown as the dashed feedback line.

Full component detail: [`PROJECT.md` — System Architecture](PROJECT.md#system-architecture).

---

## 2. Component responsibilities

| Component | Responsibility | Never does |
|---|---|---|
| **Orchestrator (LangGraph)** | Owns workflow state; routes to sub-agents; makes the final admit/decline call; tracks referral lifecycle | Talk to callers directly; read documents directly; query databases directly |
| **Voice Agent** | Talks and listens via Twilio; extracts structured data from what the caller says; reports to the orchestrator | Decide eligibility; promise admission; give medical advice |
| **Document Pipeline** | Runs the 7-layer extraction (see §4) on every fax/PDF; produces structured JSON with confidence scores and a gap list | Decide eligibility; contact the caller |
| **Eligibility Agent** | Deterministically traverses PostgreSQL + Neo4j to return `ACCEPT` / `DECLINE` / `NEEDS_MORE_INFO` with reasons | Use an LLM to decide; guess when data is missing (returns `NEEDS_MORE_INFO` instead) |
| **Follow-up Agent** | Sends SMS/email, schedules outbound calls and retries, tracks gap-closure status | Decide eligibility; skip the safety-gated call flow on outbound calls |

---

## 3. Safety-gated call flow (non-negotiable)

This is the corrected, complete version of the call path — every box here is required by [`must-have.md`](must-have.md) Part 1.

```mermaid
sequenceDiagram
    participant Caller
    participant Twilio as Twilio ConversationRelay
    participant Consent as Consent Gather
    participant Voice as Voice Agent
    participant Tok as Tokenize / Rehydrate
    participant Gemini as Gemini Flash
    participant Elig as check_eligibility()
    participant Filter as Banned-Phrase Filter
    participant Fallback as Failure Handoff

    Caller->>Twilio: Call connects
    Twilio->>Consent: Route to first node
    Consent->>Caller: "This call may be recorded and uses AI. Is that okay?"
    Caller-->>Consent: Yes / No
    alt No
        Consent->>Twilio: Transfer to human or end call
    else Yes
        Consent->>Voice: consent_given = true
        loop Each conversation turn
            Caller->>Voice: Speaks (referral details)
            alt Turn succeeds
                Voice->>Tok: Raw transcript with identifiers
                Tok->>Gemini: Tokenized text only, no raw PII
                Tok->>Elig: Structured fields (zip, payer, service type)
                Elig-->>Tok: ACCEPT / DECLINE / NEEDS_MORE_INFO (deterministic, not LLM)
                Gemini-->>Tok: Draft response (still tokenized)
                Tok->>Filter: Rehydrated response
                Filter-->>Voice: Approved response or safe fallback
                Voice->>Twilio: Speak response
                Twilio->>Caller: TTS output
            else Exception, timeout, or repeated confusion (must-have.md #6)
                Voice->>Fallback: Trigger failure handoff
                Fallback->>Twilio: "Let me connect you with a coordinator"
                Twilio->>Caller: Handoff message, then transfer or scheduled callback
            end
        end
    end
```

Steps:

1. Twilio ConversationRelay answers and opens the WebSocket — STT starts streaming.
2. **Consent Gather runs first, before anything else.** A "no" routes to human transfer or a graceful end — never to continued data collection.
3. The Voice Agent talks and extracts data. It does not decide anything.
4. Every raw transcript passes through the **Tokenize wrapper** before it can reach Gemini Flash — identifiers become placeholders (`{{PATIENT_NAME}}`, `{{DOB}}`, etc.).
5. Eligibility runs as **deterministic code**, in parallel with Gemini Flash's reasoning, not inside it — it never asks the LLM to judge eligibility.
6. Gemini Flash's draft response is **rehydrated** with real values only inside the backend, then passed through the **banned-phrase filter** before it can reach TTS — this applies to every mode (provider, family, outbound), not only eligibility responses.
7. Twilio speaks the approved response; the loop repeats for the next turn.

Outbound calls (Feature 4) re-enter this exact same flow via Voice Agent Outbound mode — there is no separate, unguarded outbound path.

8. **Failure handling (no silent drop):** if anything mid-call raises an exception, times out, or the caller isn't understood after repeated attempts, that turn routes to the same handoff mechanism as a consent "no" — a spoken fallback ("Let me connect you with a coordinator") followed by a human transfer or a scheduled callback. No call path is allowed to end in silence. This is a distinct guarantee from consent (opt-out vs. failure), but both terminate at the same handoff code path. Full spec: [`must-have.md`](must-have.md) Part 1, guarantee #6.

Full spec, code-level implementation, and the pre-demo checklist: [`must-have.md`](must-have.md) Part 1.

---

## 4. Document pipeline (7 layers)

```mermaid
flowchart LR
    L1["Layer 1<br/>Ingestion & preprocessing"] --> L2["Layer 2<br/>Page classification"]
    L2 --> L3{"Layer 3<br/>OCR strategy router"}
    L3 -->|Clean digital PDF| L3B["Path B<br/>Docling + rules"]
    L3 -->|Messy scanned image| L3C["Path C<br/>Gemini vision"]
    L3B --> L4["Layer 4<br/>Raw JSON extraction"]
    L3C --> L4
    L4 --> L5a["Layer 5a<br/>Validation Agent"]
    L5a --> L5b["Layer 5b<br/>Correction Agent"]
    L5b --> L5c["Layer 5c<br/>Cross-Reference Agent"]
    L5c --> L6["Layer 6<br/>Completeness check & gaps"]
    L6 --> L7{"Layer 7<br/>Confidence scoring"}
    L7 -->|High| OUT1["Auto-populate"]
    L7 -->|Medium| OUT2["Auto-populate + flag for review"]
    L7 -->|Low| OUT3["Withhold; add to gap list for Voice Agent"]
```

Steps:

1. **Layer 1** — deskew, denoise, contrast-enhance each page; detect scanned-image vs. digital-text pages.
2. **Layer 2** — classify each page (physician order, F2F note, discharge summary, med list, insurance card, junk cover sheet, etc.).
3. **Layer 3** — route by cleanliness: Path B (Docling + regex/keyword rules) for clean digital PDFs, Path C (Gemini Flash vision) for messy scans and handwriting.
4. **Layer 4** — both paths converge into a standardized raw JSON per page.
5. **Layer 5** — three agents run in sequence: Validation (format/range/lookup checks) → Correction (reasons about failures, assigns a confidence to each fix) → Cross-Reference (checks consistency of the same fact across pages, e.g. patient name on two documents).
6. **Layer 6** — diffs extracted data against the completeness checklist; every gap becomes a specific follow-up task.
7. **Layer 7** — every field gets a confidence score that decides its fate: high auto-populates, medium auto-populates but is flagged, low is withheld and added to the Voice Agent's gap-verification list.

Full detail per layer, including example correction scenarios: [`PROJECT.md` — Document Pipeline](PROJECT.md#document-pipeline-7-layers--agentic-review-loop).

---

## 5. Data layer: who queries whom

```mermaid
flowchart TD
    subgraph Agents["Sub-agents"]
        VA["Voice Agent"]
        DP["Document Pipeline"]
        EA["Eligibility Agent"]
        FA["Follow-up Agent"]
    end
    subgraph DataLayer["Data layer"]
        PG[("PostgreSQL<br/>operational + reference + pgvector")]
        NEO[("Neo4j<br/>knowledge graph")]
        RED[("Redis<br/>pipeline + call state, cache")]
    end
    VA --> RED
    DP --> RED
    DP --> PG
    EA --> PG
    EA --> NEO
    EA --> RED
    FA --> PG
    FA --> RED
```

Steps / rules this enforces:

1. **Eligibility Agent is the only heavy Neo4j consumer** — it traverses the diagnosis → service type → certification → caregiver → service area path, plus the insurance → payer → coverage rule path. It also hits PostgreSQL for the caregiver roster and service-area/insurance-contract lookups.
2. **Redis is shared, not owned by one agent** — Voice Agent uses it for live call state, Document Pipeline uses it for pipeline-layer state, Eligibility Agent uses it to cache repeated zip+insurance checks, Follow-up Agent uses it for retry scheduling.
3. **Document Pipeline touches PostgreSQL** for reference/lookup tables (ICD-10 codes, medication dosage ranges) during Layer 5 validation, and for pgvector fuzzy matching (insurance plan names, med name variants, physician names) — pgvector is a PostgreSQL extension, not a separate store.
4. **Follow-up Agent writes to PostgreSQL** (event log, intake status) and to Redis (retry timers).
5. **No agent writes eligibility or acceptance decisions except the Eligibility Agent** — this is what keeps "can two agents accept the same patient" impossible.

Why 4 stores instead of 1, full schema-shaped rationale: [`PROJECT.md` — Database Architecture](PROJECT.md#database-architecture).

### Neo4j graph model (core traversal subset)

The full graph has 13 node types and 14 relationship types (see `PROJECT.md`). The subset that the eligibility check actually walks on every call:

```mermaid
flowchart LR
    Patient -->|HAS_DIAGNOSIS| Diagnosis
    Patient -->|HAS_INSURANCE| InsurancePlan["Insurance Plan"]
    InsurancePlan -->|UNDER_PAYER| Payer
    InsurancePlan -->|COVERS| ServiceType["Service Type"]
    Diagnosis -->|REQUIRES| ServiceType
    ServiceType -->|NEEDS_CERTIFICATION| CertType["Certification Type"]
    Caregiver -->|HAS_CERTIFICATION| CertType
    Caregiver -->|SERVES_AREA| ServiceArea["Service Area"]
```

This is the "6-hop path" referenced in `PROJECT.md`: diagnosis → required service → required certification → a caregiver holding that certification → serving the patient's area, cross-checked against the insurance plan's coverage of that service type.

---

## 6. End-to-end request lifecycles

### Flow 1 — Discharge planner calls the agency

```mermaid
sequenceDiagram
    participant Planner
    participant Twilio
    participant Voice as Voice Agent (provider mode)
    participant Orch as Orchestrator
    participant Elig as Eligibility Agent
    participant DB as PostgreSQL + Neo4j
    participant Follow as Follow-up Agent

    Planner->>Twilio: Calls agency number
    Twilio->>Voice: Routes call, provider mode
    Voice->>Planner: Greeting + consent gather
    Planner->>Voice: Referral details (age, diagnosis, insurance, zip)
    Voice->>Orch: Extracted fields
    Orch->>Elig: Check eligibility
    Elig->>DB: Query service area, insurance, caregiver roster
    DB-->>Elig: Match results
    Elig-->>Orch: ACCEPT, missing F2F note
    Orch-->>Voice: Response instructions
    Voice->>Planner: "We can accept... send the F2F documentation"
    Planner->>Twilio: Call ends
    Orch->>Follow: Trigger follow-up
    Follow->>Planner: SMS confirmation with referral ID
    Follow->>DB: Create intake record, status PENDING_DOCUMENTS
```

### Flow 2 — Fax referral arrives

```mermaid
sequenceDiagram
    participant Fax as Fax / PDF
    participant Pipe as Document Pipeline
    participant Orch as Orchestrator
    participant Elig as Eligibility Agent
    participant Voice as Voice Agent (outbound mode)
    participant Provider
    participant Follow as Follow-up Agent

    Fax->>Pipe: Referral packet arrives
    Pipe->>Pipe: Layer 1 - ingest & preprocess (deskew, denoise, detect scan vs. digital text)
    Pipe->>Pipe: Layer 2 - classify each page (physician order, F2F note, insurance card, junk, etc.)
    Pipe->>Pipe: Layer 3 - route: clean digital -> rules (Docling), messy scan -> Gemini vision
    Pipe->>Pipe: Layer 4 - extract into standardized raw JSON
    Pipe->>Pipe: Layer 5 - Validation -> Correction -> Cross-Reference agents check every field
    Pipe->>Pipe: Layer 6 - completeness check, build gap list
    Pipe->>Pipe: Layer 7 - confidence scoring (high/medium/low) decides auto-populate vs. withhold
    Pipe->>Orch: Structured data + gap list (this is where "document checking/analysis" happens - full detail in §4)
    Orch->>Elig: Check eligibility
    Elig-->>Orch: ACCEPT, missing F2F note + low-confidence insurance ID
    Orch->>Voice: Trigger outbound call
    Voice->>Provider: Verify insurance ID, request F2F note
    Orch->>Follow: Trigger SMS/email
    Follow->>Provider: Document upload link
```

### Flow 3 — Family member calls

```mermaid
sequenceDiagram
    participant Daughter
    participant Twilio
    participant Voice as Voice Agent (family mode)
    participant Orch as Orchestrator
    participant Elig as Eligibility Agent (preliminary)
    participant Follow as Follow-up Agent

    Daughter->>Twilio: Calls at midnight
    Twilio->>Voice: Routes call, family mode
    Voice->>Daughter: Compassionate greeting + consent gather
    Daughter->>Voice: What she knows (condition, hospital, zip)
    Voice->>Orch: Partial data
    Orch->>Elig: Preliminary eligibility check
    Elig-->>Orch: Likely yes (zip, insurance type, condition all plausible)
    Orch-->>Voice: Response instructions
    Voice->>Daughter: "We should be able to help — a coordinator follows up tomorrow"
    Orch->>Follow: Create intake record, status NEW
    Follow->>Daughter: SMS confirmation
```

Full prose walkthroughs (with exact spoken lines): [`PROJECT.md` — Intake Workflow](PROJECT.md#intake-workflow--end-to-end).

---

## 7. Deployment topology (hackathon build)

```mermaid
flowchart TD
    subgraph Local["Docker Compose (dev / demo laptop)"]
        API["FastAPI backend"]
        PG[("PostgreSQL + pgvector")]
        NEO[("Neo4j")]
        RED[("Redis")]
        WEB["React dashboard"]
    end
    NGROK["ngrok tunnel"] --> API
    TWILIO["Twilio"] --> NGROK
    API --> GEMINI["Gemini Flash API"]
    WEB --> API
    API --> PG
    API --> NEO
    API --> RED
```

Everything runs locally via Docker Compose except Twilio and the Gemini API, which are external services reached through an ngrok tunnel (Twilio needs a public webhook URL to reach the local FastAPI WebSocket server). Account setup for each external dependency: [`PROJECT.md` — Accounts & Credentials Setup](PROJECT.md#accounts--credentials-setup).

---

## 8. Module layout (actual — kept in sync with reality)

Two parallel trees exist, governed by CLAUDE.md "Workspace Boundaries": the **canonical integration tree** below, and `local/` (the autonomous coder agent's workspace, reconciled at merge time per [`MERGE_DAY_RECONCILIATION.md`](MERGE_DAY_RECONCILIATION.md)).

```
apis/api_intake/            ← canonical backend (one folder per API)
  app/
    routes/                  ← Person 1 (health, /eligibility-check, Twilio webhook + ConversationRelay WS)
    safety/                  ← shared, non-negotiable (must-have.md guarantees 1-6 as code)
    agents/                  ← Person 3 (eligibility_agent facade, knowledge_graph traversal, mode_router)
    eligibility/             ← Person 3 (checks, decision engine, reference_data, live_sources PG, status_writer)
  tests/                     ← full suite incl. make safety gate + 4-scenario acceptance test
ai-agents/
  voice-agent/               ← Person 1 (provider/family/outbound mode system prompts)
infra/
  neo4j/load_seed.py         ← Person 3 (knowledge-graph seed loader from data/)
  postgres/seed_demo_data.py ← Person 3 (intakeai_demo seeder from data/)
apps/dashboard/              ← Person 3 (React dashboard, Vite + TS)
data/                        ← canonical seed source (see data/README.md)
local/                       ← autonomous agent workspace (orchestrator, follow-up, guardrails; DO NOT TOUCH — merges per MERGE_DAY_RECONCILIATION.md)
```

Follow-up + orchestrator live in `local/backend/` until merge day; their canonical seam is the `EligibilityClient` protocol ↔ `POST /eligibility-check` contract.

---

## 9. Where to look for more detail

| Question | Look in |
|---|---|
| Why does this product exist, who's the customer | `PROJECT.md` — The Problem, The Solution |
| What must never break, safety checklist | `must-have.md` Part 1 |
| Which features are must-have vs. nice-to-have | `must-have.md` Part 2 |
| Exact database schema fields | `PROJECT.md` — Data Model |
| Hackathon rules, judging criteria, compliance checklist | `PROJECT.md` — Official Challenge Brief |
| Accounts and credentials needed | `PROJECT.md` — Accounts & Credentials Setup |
| Hour-by-hour build plan and phase ownership | `PROJECT.md` — Hackathon Build Plan |
| Team collaboration protocol, task templates | `CLAUDE.md` |
