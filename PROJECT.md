# IntakeAI — Intelligent Patient Intake Agent for Home Health Agencies

## Hackathon

- **Event**: AI Healthcare Hack NYC
- **Host**: localhost:nyc × Arya Health (Series A, reimagining the economics of healthcare services)
- **Sponsor**: Twilio AI Startup Searchlight
- **Format**: One-day, in-person sprint — 5 hours build, live demo + judging
- **Requirement**: Must use Twilio for telephony to qualify for sponsor prizes
- **Prize**: $500/$300/$200 Twilio credits + interview with Arya Health engineering team for top 3
- **Team Size**: 4 engineers using Cursor

---

## Official Challenge Brief (Strict — Do Not Deviate)

This section is copied verbatim in substance from the hackathon organizers' brief. It is the binding rule set for what "done" means. Every planning and implementation decision must satisfy this before anything else — it overrides convenience, scope creep, or feature ideas not traceable back to it.

### About the Challenge

Healthcare Hack NYC is a one-day, in-person sprint hosted with Arya Health — a Series A startup reimagining the economics of healthcare services — at their NYC office. Main sponsor: Twilio's AI Startup Searchlight, celebrating startups building the future of voice, conversational AI, and LLM-powered agents. The goal: bring a laptop, form a team, ship a real AI agent in a single day.

### The Challenge

Build production-ready voice/text AI agents that can carry out a full conversation end-to-end, grounded in domain knowledge and personalized to each caller. **Reliability, guardrails, security, and scalability are not nice-to-haves — they are the prerequisite.**

**You must use Twilio to qualify for sponsor prizes. This is non-negotiable.**

### What to Build

A conversational agent that handles a real healthcare workflow — patient intake, scheduling, reminders, insurance verification, caregiver follow-up — from hello to done. Suggested building blocks:

- **Telephony** — must use Twilio to qualify for prizes
- **Agent Development Framework** — orchestrate and modularize the conversation logic
- **Model (TTS/STT)** — power the conversation with the best voice AI models
- **Knowledge Base** — connect to external sources and data for enriched, grounded context
- **Caller Info** — recognize and personalize the conversation to the individual caller

### Requirements — What to Build

A working voice or text conversational AI agent that carries out a full healthcare conversation end-to-end — grounded in domain knowledge and personalized to the caller.

- Must use Twilio for telephony to qualify for sponsor prizes.
- Everything must be built during the sprint and demoed live.
- Reliability, guardrails, security, and scalability are part of the bar, not extras.

### Requirements — What to Submit

On the Devpost project page:

- Project name and a one-line description
- What was built and why (the problem being solved)
- Tools and technologies used (including how Twilio was used)
- Team member names and roles
- Link to the live demo / prototype / videos

### Judging Criteria (1–5 each)

| Criterion | What it measures |
|---|---|
| **Technical Implementation** | Technical architecture and design, production readiness, security, scalability, reliability |
| **Idea Uniqueness** | How original and non-obvious the concept is, whether it actually works end-to-end, and how well it was built |
| **Team Explanation** | How clearly the team explains the problem, solution, and how it works |
| **UI/UX** | Usability and quality of the experience |

### Compliance Checklist (verify before demo/submission)

- [ ] Telephony runs through Twilio (voice and/or SMS) — no Twilio, no prize eligibility
- [ ] The demoed flow is a full conversation end-to-end ("hello to done"), not a fragment
- [ ] Guardrails are visibly enforced (no medical advice, no premature admission confirmation, escalation on low confidence) — see [Feature 6: Guardrails & Compliance](#feature-6-guardrails--compliance)
- [ ] Security posture is explainable on demand (PHI handling, encrypted storage, auth) — see [Database Architecture](#database-architecture)
- [ ] Scalability story is explainable on demand (concurrent calls, modular agents) — see [Judging Criteria Alignment](#judging-criteria-alignment)
- [ ] Caller personalization is demonstrable — see [Feature 5: Caller Personalization](#feature-5-caller-personalization)
- [ ] Knowledge grounding is demonstrable (ICD-10/Neo4j, not free-floating LLM guesses) — see [Neo4j — Knowledge Graph](#neo4j--knowledge-graph)
- [ ] Everything shown was built during the sprint (pre-work is data/scaffolding only, per [Hackathon Build Plan](#hackathon-build-plan))
- [ ] Devpost submission has: project name + one-liner, problem/solution writeup, tools used (incl. Twilio usage), team roles, live demo link

---

## The Problem

### Who is the customer?

Home health agencies — companies that employ caregivers (nurses, physical therapists, home health aides) and send them to patients' homes to deliver care after hospital discharge, surgery recovery, or for chronic condition management. Examples: TheKey, Team Select, Thrive Skilled Pediatric Care. These agencies are Arya Health's customers.

### What is Arya Health?

Arya Health is a software company (not a care provider). They sell AI-powered digital agents to home health agencies that automate administrative work. Their current product lineup has 5 agents — all caregiver-facing:

- **Staffing Agent** — scheduling, shift coverage, callout management
- **Compliance Agent** — license/certification tracking and follow-up
- **Onboarding Agent** — recruiting and applicant engagement
- **Payroll Agent** — rate calculations, overtime, retroactive pay
- **Engagement Agent** — performance management and retention

All 5 agents manage the supply side (caregivers). None of them handle the demand side (patients coming in). The Intake Agent — handling new patient referrals — is Arya's publicly stated next product, announced during their Series A in late 2025, but has not shipped publicly as of July 2026.

### What is the intake problem?

When a patient needs home health care, a referral enters the agency through one of these channels:

1. **Hospital discharge planner sends a fax** — dominant channel. A 35-100+ page PDF referral packet containing patient demographics, diagnosis, physician orders, medications, insurance info, discharge notes. Arrives at any hour. Currently sits in a queue until a human reviews it manually.
2. **Hospital discharge planner calls the agency** — they want an immediate yes/no. "Can you take this patient?" If the agency doesn't pick up or takes too long, they call the next agency.
3. **Family member calls** — a worried daughter or spouse. "My mom just had a stroke and she's coming home, I don't know what to do." They don't have clinical details. They need guidance and reassurance.
4. **Physician's office sends a referral** — via fax or phone call with physician orders.
5. **Skilled nursing facility (SNF) refers a patient** — patient stepping down from rehab to home care.
6. **Patient self-refers** — rare for skilled care (needs physician order), more common for personal care/companion care.

### Why is this a problem? (Evidence-based)

- Referral conversion rates have declined 13% since 2018, dropping from 77% to 64% by Q2 2025. Agencies lose more than a third of the patients referred to them.
- Home health agencies collectively lose an estimated $200-500 million annually to referral leakage.
- Most loss happens in the first 70 minutes after a referral arrives while the coordinator manually reviews documents and checks systems.
- It takes 70 minutes for intake coordinators to thoroughly review an average referral packet.
- Median time from referral entry to start of care exceeds 69 hours, with 13+ hours spent inside intake processes alone.
- Hospital discharge planners work with 3-5 agencies simultaneously and go with whoever responds first.
- Agencies miss roughly 20% of referrals arriving outside business hours.
- 30% of referrals are rejected due to service offering mismatches that could have been caught instantly.
- One-third of home health episodes have delayed start-of-care visits.
- Incomplete documentation accounts for over 51% of improper payments in home health.

### Why speed matters

Medicare's quality metric requires timely initiation of care — best practice is first visit within 48 hours of referral. If the agency is slow, the patient either goes to a competitor or goes without care. Every hour of delay during intake is a patient the agency might lose. The discharge planner is making 3-5 calls simultaneously — whoever responds first wins the patient.

---

## The Solution

### What we're building

IntakeAI is an intelligent patient intake agent that ensures a home health agency never misses a patient because nobody picked up the phone, and never loses a patient because they were too slow to respond.

It handles the entire intake workflow from referral received to patient admitted — across voice calls, fax processing, SMS, and email — with real-time eligibility checking, domain-grounded knowledge, and caller personalization.

### In plain English

The phone rings at 7 PM — our AI agent picks up. It has a real conversation with the discharge planner, collects all the patient details, instantly checks the database to see if we serve that area, accept that insurance, and have the right caregiver available — and gives an answer right there on the call. "Yes, we can take her. We have a nurse available. Send us the face-to-face documentation and we'll have someone there by tomorrow afternoon." Three minutes. Done.

A fax comes in — our system reads it automatically, pulls out all the important information, catches errors, flags what's missing, checks if we can take this patient, and if we can, immediately calls the hospital to collect the missing paperwork and calls the family to schedule the first visit. What used to take days now takes hours.

A worried daughter calls at midnight — our agent picks up, talks to her compassionately, collects what she knows about her mom's situation, tells her whether we can likely help, and assures her a coordinator will follow up first thing in the morning.

---

## System Architecture

### Core Principle

The Intake Agent is the orchestrator — the brain. It doesn't make calls, it doesn't read documents, it doesn't query databases directly. It coordinates specialized sub-agents that each do one thing well.

The Voice Agent is one component inside the Intake Agent. It's the mouth and ears — how the Intake Agent talks to the outside world via phone. The Voice Agent doesn't think for itself. The Intake Agent feeds it everything: what to ask, what to say, when to pause and check eligibility.

### Agent Architecture

```
┌──────────────────────────────────────────────────────┐
│              INTAKE AGENT (LangGraph)                 │
│                 The Orchestrator                      │
│                                                       │
│  Manages workflow state, routes tasks to sub-agents,  │
│  makes admit/decline decisions, tracks referral       │
│  lifecycle from received → processed → decided        │
│                                                       │
│  ┌─────────────────┐    ┌──────────────────────────┐  │
│  │  Document        │    │  Eligibility              │  │
│  │  Pipeline        │    │  Agent                    │  │
│  │                  │    │                           │  │
│  │  7-layer         │    │  Takes extracted patient  │  │
│  │  extraction      │    │  data, traverses          │  │
│  │  with agentic    │    │  PostgreSQL + Neo4j,      │  │
│  │  validation &    │    │  returns:                 │  │
│  │  correction      │    │  ACCEPT / DECLINE /       │  │
│  │  loop            │    │  NEEDS_MORE_INFO          │  │
│  │                  │    │  with specific reasons    │  │
│  └─────────────────┘    └──────────────────────────┘  │
│                                                       │
│  ┌─────────────────┐    ┌──────────────────────────┐  │
│  │  Voice           │    │  Follow-up                │  │
│  │  Agent           │    │  Agent                    │  │
│  │                  │    │                           │  │
│  │  Handles phone   │    │  SMS confirmations,       │  │
│  │  calls via       │    │  email follow-ups,        │  │
│  │  Twilio. Listens,│    │  document request links,  │  │
│  │  speaks, extracts│    │  retry logic (if call     │  │
│  │  data. Does NOT  │    │  went to voicemail,       │  │
│  │  make decisions. │    │  retry in 2 hours),       │  │
│  │  Reports to      │    │  callback scheduling      │  │
│  │  orchestrator,   │    │                           │  │
│  │  follows its     │    │                           │  │
│  │  instructions.   │    │                           │  │
│  └─────────────────┘    └──────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

### Voice Agent — Two Layers of Control

The Voice Agent receives instructions from the Intake Agent at two levels:

#### Layer 1: Static — Conversation Flow (system prompt)

Before any call starts, the Intake Agent assigns a system prompt based on the scenario:

- **Provider mode** — discharge planner or physician calling. Clinical language, efficient, structured. Collects: patient name, DOB, diagnosis, insurance, physician, care type, discharge date, urgency. Doesn't give medical advice. Doesn't confirm admission without checking with the orchestrator first.
- **Family mode** — family member calling. Compassionate, simple language, no medical jargon. Collects what they know. Sets expectations that a coordinator will follow up. Doesn't promise coverage or availability.
- **Outbound mode** — agent making a call to follow up on a fax referral. Has a specific mission: collect a missing document, verify information, or confirm with patient/family. Knows exactly what gaps to fill.

#### Layer 2: Dynamic — Real-time Decisions Mid-Call

During a call, the Voice Agent extracts data from what the caller says and passes it to the Intake Agent orchestrator. The orchestrator sends it to the Eligibility Agent for real-time database/graph checks. The result comes back with specific instructions for what the Voice Agent should say next.

Example flow during a live call:

1. Discharge planner says: "Medicare Part A, skilled nursing, post-hip replacement, zip 11201"
2. Voice Agent extracts: zip=11201, insurance=Medicare Part A, service=skilled nursing, diagnosis=hip replacement
3. Voice Agent passes to Intake Agent orchestrator
4. Orchestrator sends to Eligibility Agent
5. Eligibility Agent queries PostgreSQL (do we serve 11201? → yes) → queries Neo4j (hip replacement → ICD M17.11 → requires RN with orthopedic cert) → queries caregiver roster (3 available RNs with that cert in that zip) → checks Medicare coverage (covered, no prior auth, but needs F2F documentation and homebound certification)
6. Eligibility Agent returns: ACCEPT — missing face-to-face encounter note
7. Orchestrator tells Voice Agent: "Tell them we can accept, we have availability within 48 hours, ask for the face-to-face documentation"
8. Voice Agent speaks: "We can accept this referral. We have a nurse available in that area. We'll need the face-to-face encounter documentation — can you send that to our fax?"

This entire loop must complete in 2-3 seconds. If longer, the Voice Agent uses natural filler: "Let me check our availability for that area... one moment."

---

## Document Pipeline (7 Layers + Agentic Review Loop)

Medical referral packets are messy — handwritten physician notes, inconsistent formats across hospitals, mixed document types in one PDF, critical data where a single wrong digit means a denied claim. The pipeline uses a dual-path extraction approach with an agentic validation-correction loop on every document.

### Layer 1: Ingestion & Preprocessing

Fax arrives as PDF/TIFF → convert to standardized format → page-level image cleanup (deskew, denoise, contrast enhancement) → detect if pages are scanned images vs digital text. Medical faxes are notoriously bad quality — smudged, rotated, half-cut pages.

### Layer 2: Page Classification

Classify each page in the packet — is this a physician order? Face-to-face encounter note? Discharge summary? Medication list? Insurance card? Lab results? Consent form? Fax cover sheet (junk)? This matters because downstream extractors need to know which document type they're processing. A medication list is extracted differently from an insurance card.

### Layer 3: OCR Strategy Router (Dual-Path Extraction)

- **Path B: Rule-based extraction** for clean digital PDFs. Hospital referrals from larger health systems sometimes come as structured digital PDFs. Use Docling to parse text layers, then regex and keyword matching to pull fields. Patient name follows "Patient:" or "Name:". ICD codes follow a known pattern (letter + digits). Insurance member IDs follow payer-specific formats. NPI numbers are always 10 digits. Deterministic, fast, reliable.
- **Path C: LLM vision extraction** for messy image PDFs. Handwritten physician notes, scanned insurance cards at an angle, smudged medication lists. Gemini Flash vision extracts fields directly from the image. The LLM is the primary extractor here because rules can't handle the variation.

### Layer 4: Entity Extraction → Raw JSON

Both paths produce a standardized raw JSON output per page with all extracted fields.

### Layer 5: Agentic Review Loop

This runs on EVERY document regardless of extraction path. Three agents operate in sequence:

**Validation Agent** — checks every extracted field:
- Is this a valid ICD-10 code? (lookup against ICD-10 code table)
- Is this NPI number real? (Luhn algorithm check digit validation)
- Does this insurance member ID match the payer's known format?
- Is the date of birth reasonable? (not 150 years old, not future)
- Does discharge date come after admission date?
- Is the zip code a real US zip code?
- Does the medication dosage fall within known clinical ranges? (Metformin 500-2000mg normal, 50000mg is OCR error)

**Correction Agent** — takes validation failures and reasons about them:
- ICD code "M17.1I" invalid → looks at original image → "I" was actually "1" → corrects to "M17.11" → confidence: high, auto-correct
- Insurance ID "H12O456789" → "O" probably a "0" based on surrounding digits → corrects to "H120456789" → confidence: medium, flag for review
- "Lisinopril 200mg" → standard dosing is 2.5-40mg → could be 20mg or 2.0mg → can't confidently correct → confidence: low, flag for human review, add to gap list for Voice Agent to verify on call

**Cross-Reference Agent** — checks consistency across pages in the same packet:
- Patient name on discharge summary says "Johnson, Maria" but insurance card says "Maria L. Johnson-Smith" → checks DOB across both to confirm same person
- Discharge summary says "Type 2 Diabetes" but ICD code on physician order says "E11.9" → validates E11.9 IS Type 2 Diabetes → consistent
- Medication list shows Warfarin but diagnosis doesn't include any condition requiring anticoagulation → flag mismatch for clinical review

### Layer 6: Completeness Check & Gap Identification

Check extracted data against requirements checklist:
- Patient demographics complete?
- Physician orders present and signed?
- Face-to-face encounter documentation present?
- Insurance information complete?
- Diagnosis and ICD codes present?
- Homebound status documented?
- Medication list present?

Each missing item becomes a specific follow-up task for the Voice Agent.

### Layer 7: Confidence Scoring & Routing

Every extracted field gets a confidence score based on extraction method, validation results, and cross-document confirmation:

- **HIGH confidence** — extracted by rules + passed validation + confirmed across documents → auto-populate into intake record
- **MEDIUM confidence** — extracted by LLM vision + passed validation but only appeared on one document → auto-populate but flag for review
- **LOW confidence** — failed validation + correction uncertain → don't populate, add to gap list for Voice Agent to verify on call

---

## Features

### Feature 1: 24/7 Inbound Call Handling

The agency's Twilio phone number is always answered by the AI agent — nights, weekends, holidays. No more voicemails, no more missed referrals. The agent detects the caller type (provider vs family vs patient) and adapts the conversation flow accordingly.

**Provider call handling:**
- Structured clinical intake conversation
- Real-time eligibility checking during the call
- Immediate accept/decline/need-more-info response
- Specific ask for missing documents
- SMS/email confirmation sent to the provider after the call

**Family call handling:**
- Compassionate, guided conversation in plain language
- Captures what the family knows (patient name, condition, what happened, insurance if available)
- Explains the process and what to expect
- Sets realistic expectations
- Schedules coordinator follow-up
- Never promises coverage or availability

**Patient self-referral handling:**
- Patient-appropriate pace and language
- Handles confused or elderly callers
- Explains that a physician order is needed for skilled care
- Offers to help coordinate with their doctor
- Captures contact information for follow-up

### Feature 2: Intelligent Fax Processing

Fax referral packets are automatically processed through the 7-layer extraction pipeline. The system reads the document, extracts structured data, validates it, catches errors, corrects what it can, and flags what it can't. Within minutes of a fax arriving, the system knows: who is this patient, what do they need, can we serve them, and what's missing.

### Feature 3: Real-Time Eligibility Engine

Every referral — whether from a call or a fax — is checked against the agency's actual capabilities in real-time:

- **Service area check** — do we serve this zip code?
- **Insurance check** — do we accept this payer and plan?
- **Clinical matching** — does the patient's diagnosis map to a service type we offer, and does it require certifications we have?
- **Caregiver availability** — do we have a caregiver with the right certifications, in the right area, available within the required timeframe?
- **Coverage rules** — does this insurance require prior authorization? What documentation is needed?

The result is one of three outcomes:

- **ACCEPT** — we can take this patient, here's the matched caregiver, here's what documentation we still need
- **DECLINE** — we can't serve this patient (wrong area, wrong insurance, no caregiver available), respond fast so the referral source can place the patient elsewhere
- **NEEDS_MORE_INFO** — we might be able to accept but need specific missing information before deciding

### Feature 4: Automated Outbound Follow-up

When the document pipeline or eligibility engine identifies gaps, the Intake Agent automatically triggers outbound actions:

**Outbound voice call to referring provider:**
- "We received the referral for Mrs. Johnson. We can accept but we're missing the face-to-face encounter documentation. Can you send that to our fax?"
- If no answer, leave a structured voicemail and send SMS follow-up

**Outbound voice call to patient/family:**
- "Hi Mrs. Johnson, I'm calling from ABC Home Health. Your doctor has referred you for home nursing visits. I'd like to confirm a few details and get your first visit scheduled."
- Confirm address, schedule preference, emergency contact

**SMS/email confirmations:**
- Confirmation to the referring provider with referral status
- Document request links for missing paperwork
- Appointment confirmation to patient/family

**Retry logic:**
- If call goes to voicemail, schedule retry in 2 hours
- If SMS gets no response, follow up next morning
- Escalate to human coordinator after 3 failed contact attempts

### Feature 5: Caller Personalization

The system recognizes returning callers and personalizes the experience:

- A discharge planner who calls regularly gets a streamlined experience — "Hi Sarah, calling from Mount Sinai? Go ahead with the referral details."
- The system remembers referral source history — how many referrals they've sent, acceptance rate, preferred communication method
- Previous interactions inform the conversation — if a family member called yesterday about their mom, and the coordinator is following up today, the agent has the full context

### Feature 6: Guardrails & Compliance

**Clinical guardrails:**
- Never gives medical advice
- Never confirms a caregiver assignment before eligibility is verified
- Flags clinically suspicious data (medication dosages outside normal ranges, conflicting diagnoses)
- Enforces HIPAA-appropriate conversation boundaries

**Operational guardrails:**
- Never promises admission before the Eligibility Agent confirms
- Always informs callers that a human coordinator will review the decision
- Escalates to a human when confidence is low or the situation is complex
- Maintains audit trail of every decision and the data that informed it

**Data guardrails:**
- Confidence scoring ensures low-confidence data is never auto-populated
- Cross-document validation catches inconsistencies before they enter the system
- All extracted data is traceable back to the source document and page

### Feature 7: Intake Dashboard

A real-time dashboard showing:

- All active referrals and their pipeline status (new → processing → eligible → accepted/declined)
- Extracted data per referral with confidence scores (green/yellow/red)
- Gap list — what's missing and what actions have been taken to fill each gap
- Call transcripts for every voice interaction
- Caregiver match results showing which caregivers were considered and why each was selected or ruled out
- Referral source analytics — which hospitals send the most referrals, acceptance rates, average response times
- Time-to-decision metrics — how fast are we responding to each referral

---

## Data Model

### Patient Data
- Name, date of birth, gender
- Address (street, city, state, zip code)
- Phone number
- Emergency contact (name, phone, relationship)
- Primary language spoken

### Clinical Data
- Primary diagnosis with ICD-10 code
- Secondary diagnoses with ICD-10 codes
- Surgical procedures performed
- Medications (name, dosage, frequency)
- Allergies
- Functional limitations (mobility, self-care ability)
- Homebound status (yes/no, reason — required for Medicare)
- Hospital admission date
- Hospital discharge date

### Physician Data
- Ordering physician name
- Physician NPI number
- Physician phone and fax
- Physician specialty
- Face-to-face encounter date
- Signed physician orders (care type ordered, visit frequency, duration)

### Insurance Data
- Payer name (Medicare, Medicaid, Humana, Aetna, UnitedHealthcare, etc.)
- Plan type (Part A, Part B, Medicare Advantage, PPO, HMO)
- Member ID
- Group number
- Policy effective date
- Prior authorization required (yes/no)
- Authorization number (if already obtained)

### Referral Source Data
- Referring facility name (hospital, SNF, physician office)
- Referring facility type
- Discharge planner or social worker name
- Their phone, fax, email
- EHR system they use
- Referral date and time

### Care Request Data
- Service types needed (skilled nursing, PT, OT, speech therapy, HHA)
- Visit frequency requested (3x/week, daily, etc.)
- Duration of care (30 days, 60 days, ongoing)
- Urgency level (routine, urgent, start of care within 24 hours)
- Special instructions from physician

### Agency Configuration Data
- Service areas (list of zip codes served)
- Insurance contracts (which payers and plans accepted)
- Service types offered
- Operating hours
- Agency fax number, phone number

### Caregiver Roster Data
- Name
- Caregiver type (RN, LPN, CNA, PT, OT, Speech Therapist, HHA)
- Certifications held (wound care, IV therapy, pediatric, cardiac, orthopedic, diabetes education, etc.)
- Certification expiry dates
- Service zip codes (where willing to work)
- Availability schedule (days, hours)
- Languages spoken
- Current patient load
- Max patient capacity
- Status (active, on leave, suspended)

### Knowledge & Reference Data
- ICD-10 code table (code, description, hierarchy) — ~70,000 codes, subset of top 30 home health diagnoses for hackathon
- SNOMED CT to ICD-10 mappings — from National Library of Medicine
- Diagnosis → service type mappings (hip replacement → skilled nursing + PT)
- Service type → certification requirement mappings (skilled nursing → RN or LPN)
- Payer coverage rules (Medicare Part A → covers skilled nursing, requires homebound status, requires F2F encounter, no prior auth)
- RxNorm medication reference (drug names, standard dosage ranges, interactions)
- NPI registry (for physician validation — free CMS API)

### Pipeline & Operational Data
- Intake record status (new, processing, pending_documents, eligible, accepted, declined)
- Extracted fields per document with confidence scores (high/medium/low)
- Gap list (what's missing, what actions taken to fill, current status)
- Call transcripts (full text from Twilio Conversational Intelligence)
- Follow-up actions (SMS sent, call attempted, voicemail left, document received, callback scheduled)
- Timestamps for every event (referral received, extraction complete, eligibility checked, first call made, patient admitted)

---

## Database Architecture

### Why 4 databases?

Each data type has different access patterns. Using one database for everything would mean compromising on performance for at least one critical path.

### PostgreSQL — Operational Data

All structured, relational, transactional data:
- Intake records with status tracking
- Extracted field data with confidence scores (stored as JSONB)
- Caregiver roster
- Service area configuration
- Insurance contracts
- Referral source directory
- Follow-up event logs
- Call transcripts
- Audit trails
- Reference/lookup tables (ICD-10 codes, zip codes, medication ranges)

**Why PostgreSQL**: ACID transactions (critical for intake status updates — can't have two agents accepting the same patient), complex multi-constraint queries for caregiver matching (cert + zip + availability + load), JSONB for flexible document extraction output.

### Neo4j — Knowledge Graph

Relationship-rich data that requires traversal:

**13 Node Types:**
Patient, Diagnosis (ICD-10), Payer, Insurance Plan, Coverage Rule, Service Type (skilled nursing, PT, OT, speech, HHA), Certification Type, Caregiver, Service Area (zip codes), Physician, Referral Source (hospital, SNF, physician office), Medication, Document (extracted pages from referral packet)

**14 Relationship Types:**
- Patient → HAS_DIAGNOSIS → Diagnosis
- Patient → HAS_INSURANCE → Insurance Plan
- Insurance Plan → UNDER_PAYER → Payer
- Insurance Plan → COVERS → Service Type (with conditions like visit limits, homebound requirement)
- Insurance Plan → REQUIRES_AUTH → Service Type (with rules)
- Diagnosis → REQUIRES → Service Type
- Service Type → NEEDS_CERTIFICATION → Certification Type
- Caregiver → HAS_CERTIFICATION → Certification Type (with expiry date)
- Caregiver → SERVES_AREA → Service Area
- Physician → ORDERED_CARE → Patient
- Referral Source → SENT_REFERRAL → Patient
- Medication → PRESCRIBED_FOR → Diagnosis
- Medication → CONTRAINDICATED_WITH → Medication
- Document → MENTIONS → Patient / Physician / Diagnosis

**Why Neo4j**: The eligibility check is a path traversal — "does a valid path exist from this patient's diagnosis through required service types through required certifications to an available caregiver in their area with valid insurance coverage?" That's 6 hops. In SQL that's a monster query with 5-6 joins. In Cypher it's a clean traversal. The diagnosis → certification → caregiver matching, insurance hierarchy (payer → plan → state → service → rule), and ICD-10 code hierarchy are all naturally graph-shaped.

**Data sources for the graph:**
- ICD-10 hierarchy — publicly available from CMS, loaded as nodes with parent-child relationships
- SNOMED CT to ICD-10 mappings — from National Library of Medicine crosswalk
- RxNorm drug data — from NLM, for medication validation and interaction checking
- NPI registry — free CMS API for physician validation
- CMS Medicare home health rules — well-defined enough to manually encode as graph relationships
- Insurance coverage rules — simulated but realistic for hackathon (4-5 payers, 2-3 plans each)
- Diagnosis → service → certification mappings — hand-built for top 30 home health diagnoses

### Redis — Pipeline State & Caching

Ephemeral, high-frequency read/write data:
- Document pipeline state (which layer is each page on, what's been extracted so far, validation status)
- Real-time call state (what data has been collected during an active call, what questions remain)
- Eligibility check result caching (same zip + insurance combo checked 5 minutes ago, reuse result)
- Follow-up retry scheduling (call back this number in 2 hours)
- Rate limiting for Twilio calls

**Why Redis**: Pipeline state changes rapidly as a document moves through 7 layers. PostgreSQL can handle this but Redis is faster for this read-heavy, write-heavy, short-lived pattern. Also natural for caching and scheduling.

### pgvector (PostgreSQL extension) — Fuzzy Matching

- Insurance plan name matching (fax says "Humana Gold" but database has "Humana Gold Plus HMO")
- Medication name variation matching (brand names vs generics, abbreviations)
- Physician name matching across documents
- Future: RAG over payer policy documents for edge-case insurance questions

**Why pgvector over a separate vector DB**: It's a PostgreSQL extension, not a separate database. Same connection, same transactions. For the hackathon scope, PostgreSQL's built-in pg_trgm (trigram similarity) may be sufficient — pgvector is a nice-to-have.

---

## Tech Stack

- **Backend**: FastAPI (Python)
- **Agent Orchestration**: LangGraph
- **LLM**: Gemini Flash (entity extraction, agentic review, conversation reasoning)
- **Telephony**: Twilio ConversationRelay (voice), Twilio Programmable SMS
- **Speech**: Twilio-integrated STT/TTS (or Deepgram/ElevenLabs via ConversationRelay)
- **OCR/Document Parsing**: Docling (text-layer PDFs) + Gemini Flash vision (image PDFs)
- **Databases**: PostgreSQL, Neo4j, Redis, pgvector
- **Frontend Dashboard**: React (simple status dashboard for demo)
- **Infrastructure**: Docker Compose (PostgreSQL, Neo4j, Redis, FastAPI, React dev server)

---

## Intake Workflow — End to End

### Flow 1: Discharge Planner Calls the Agency

```
Phone rings
    → Twilio routes to WebSocket server
    → Voice Agent picks up in PROVIDER MODE
    → "Thank you for calling ABC Home Health, how can I help you?"
    → Planner: "I have a discharge referral — 72-year-old female, hip replacement..."
    → Voice Agent extracts data in real-time (name, DOB, diagnosis, insurance, zip)
    → Passes to Intake Agent orchestrator
    → Orchestrator sends to Eligibility Agent
    → Eligibility Agent traverses Neo4j + PostgreSQL
        → Service area? YES
        → Insurance accepted? YES (Medicare Part A)
        → Diagnosis → service mapping? Hip replacement → skilled nursing + PT
        → Certification requirements? RN with ortho cert + licensed PT
        → Available caregivers? 3 RNs, 2 PTs in that zip
        → Coverage rules? No prior auth, needs F2F doc + homebound cert
    → Returns: ACCEPT, missing F2F encounter note
    → Orchestrator tells Voice Agent what to say
    → Voice Agent: "We can accept this referral, we have availability within 48 hours.
       We'll need the face-to-face encounter documentation — can you send that?"
    → Call ends
    → Orchestrator triggers Follow-up Agent
        → SMS confirmation to planner with referral ID
        → Intake record created in PostgreSQL with status PENDING_DOCUMENTS
        → Gap: F2F encounter note — follow up in 4 hours if not received
```

### Flow 2: Fax Referral Arrives

```
Fax arrives as PDF
    → Document Pipeline Layer 1: preprocesses (deskew, denoise)
    → Layer 2: classifies each page (discharge summary, physician order, insurance card, etc.)
    → Layer 3: routes each page to appropriate extraction path (rules or vision LLM)
    → Layer 4: extracts entities into raw JSON
    → Layer 5: agentic review loop
        → Validation Agent checks all fields
        → Correction Agent fixes what it can with confidence scores
        → Cross-Reference Agent checks consistency across pages
    → Layer 6: completeness check — identifies gaps
    → Layer 7: confidence scoring — routes fields to auto-populate / flag / gap list
    → Structured data passes to Intake Agent orchestrator
    → Orchestrator sends to Eligibility Agent
    → Eligibility check runs (same as Flow 1)
    → Result: ACCEPT but missing F2F note + low-confidence insurance member ID
    → Orchestrator triggers actions:
        → Voice Agent makes OUTBOUND CALL to referring provider
            → "We received the referral for Mrs. Johnson. We can accept.
               Could you verify the insurance member ID? We have H120456789.
               Also we need the face-to-face encounter note."
        → Voice Agent makes OUTBOUND CALL to patient/family
            → "Hi, I'm calling from ABC Home Health. Your doctor has referred you
               for home nursing visits. I'd like to confirm your address and
               schedule your first visit."
        → SMS/email sent with document upload link
        → Intake record tracks all gaps and follow-up status
```

### Flow 3: Family Member Calls

```
Phone rings at midnight
    → Twilio routes to WebSocket server
    → Voice Agent picks up in FAMILY MODE
    → "Thank you for calling ABC Home Health. I'm here to help. What's going on?"
    → Daughter: "My mom just had a stroke, she's in the hospital, they said she'll
       need home care when she comes home, I don't know where to start"
    → Voice Agent uses compassionate tone, simple language
    → Asks gentle questions: mom's name, which hospital, approximate zip code,
       what kind of help she thinks she'll need, does she have insurance info handy
    → Captures what's available (may be incomplete — that's okay)
    → Passes to Intake Agent orchestrator
    → Orchestrator does a PRELIMINARY eligibility check
        → Can we serve that zip code? YES
        → Do we generally accept that insurance type? YES
        → Can we handle stroke recovery care? YES
    → Orchestrator tells Voice Agent what to say
    → Voice Agent: "Based on what you've told me, we should be able to help.
       A care coordinator will call you tomorrow morning to discuss the details.
       Could you have your mom's insurance card and her doctor's contact
       information ready? Is there a best time to reach you?"
    → Call ends
    → Orchestrator creates intake record with status NEW
    → Flags for human coordinator follow-up by 9 AM
    → SMS to daughter: "Thank you for calling ABC Home Health. A coordinator
       will contact you tomorrow morning. If you have questions before then,
       call us anytime."
```

---

## Hackathon Build Plan

### Pre-work (Before Hackathon Day)

All data prep and architecture decisions — zero application code:

- PROJECT.md (this document)
- .cursorrules with stack decisions, conventions, file structure
- PHASE_N_SPEC.md for each phase
- PostgreSQL migration SQL ready
- Neo4j Cypher seed scripts ready (ICD-10 subset, diagnosis-certification mappings, insurance rules)
- Sample referral PDFs (3-4 with varying completeness and quality)
- Caregiver roster data as JSON (20-30 caregivers)
- Insurance rules data as JSON (4-5 payers, 2-3 plans each)
- Twilio account created, phone number provisioned
- Docker Compose file ready

### Phase 1: Foundation (All 4 people, Hour 1)

- Person 1: FastAPI skeleton with health checks, WebSocket endpoint for Twilio
- Person 2: Document pipeline scaffolding (file upload endpoint, processing queue)
- Person 3: PostgreSQL schema migration + Neo4j seed data loading
- Person 4: Twilio account configuration, ConversationRelay setup, Redis setup

### Phase 2: Knowledge & Eligibility Engine (Person 3, Hours 2-3)

- Eligibility Agent implementation
- Neo4j traversal queries (diagnosis → service → certification → caregiver matching)
- PostgreSQL queries (service area, insurance contract, caregiver availability)
- Accept / decline / needs-more-info decision logic
- API endpoint: `POST /eligibility-check` → returns decision with reasons

### Phase 3: Document Pipeline (Person 2, Hours 2-3)

- PDF ingestion and preprocessing
- Page classification (LLM-based)
- Entity extraction (rules for clean PDFs, Gemini vision for messy ones)
- Validation Agent (format checks, code lookups, range checks)
- Correction Agent (re-examine source, reason about errors, confidence scoring)
- Cross-Reference Agent (consistency checks across pages)
- Completeness check and gap identification
- API endpoint: `POST /process-document` → returns structured JSON with gaps

### Phase 4: Voice Agent (Person 1, Hours 2-3)

- Twilio ConversationRelay WebSocket handler
- Provider mode conversation flow
- Family mode conversation flow
- Outbound mode conversation flow
- Real-time data extraction from caller speech
- Integration with Eligibility Agent for mid-call checks
- Call transcript capture

### Phase 5: Orchestrator (Person 4, Hours 2-3)

- LangGraph state machine defining the full intake workflow
- State: referral received → document processing → eligibility check → decision → follow-up
- Routing logic: document pipeline output triggers eligibility, eligibility triggers voice actions
- Follow-up Agent: SMS via Twilio, email, retry scheduling
- Merge logic: combine data from document pipeline + voice conversations into unified intake record

### Phase 6: Dashboard & Demo (All 4 people, Hours 4-5)

- Person 3: React dashboard — intake pipeline view, extracted data with confidence scores, gap tracker
- Person 4: Wire all components together, end-to-end integration testing
- Person 1: Live call testing, edge case handling, demo script prep
- Person 2: Connect document pipeline to orchestrator, test with sample PDFs
- All: Final 30 minutes — rehearse demo, prepare scripted scenarios, test edge cases

### Demo Script

1. **Live inbound call from discharge planner** — judge calls the Twilio number, gives referral details, gets a real-time answer on the spot
2. **Fax processing** — upload a sample referral PDF, show it processing through 7 layers on the dashboard, watch confidence scores populate, see gaps identified
3. **Outbound follow-up** — system automatically calls a number to collect missing documentation
4. **Family call** — judge calls as a worried family member, gets a compassionate intake experience
5. **Dashboard** — show the full pipeline: all referrals, their status, extracted data, confidence scores, gap lists, call transcripts, caregiver matches

---

## Judging Criteria Alignment

- **Reliability** — The agentic validation-correction loop ensures data accuracy. Confidence scoring prevents bad data from entering the system. Retry logic handles failed calls and missed follow-ups.
- **Guardrails** — Voice Agent never gives medical advice, never confirms admission without eligibility verification, flags clinically suspicious data, escalates to humans when uncertain, maintains HIPAA-appropriate conversation boundaries.
- **Security** — All patient data stored in encrypted databases. Call transcripts handled per HIPAA requirements. No PHI exposed in logs or dashboard without authentication. Twilio provides HIPAA-eligible telephony infrastructure.
- **Scalability** — Modular agent architecture means each component scales independently. Document pipeline can process multiple faxes in parallel. Voice Agent can handle concurrent calls via Twilio's infrastructure. Redis caching prevents redundant eligibility checks.
- **Domain Knowledge** — Real ICD-10 codes, real SNOMED CT mappings, real NPI validation, real Medicare coverage rules. Not an LLM guessing — a knowledge graph grounded in actual clinical and insurance data.
- **Caller Personalization** — System recognizes caller type and adapts conversation flow. Remembers referral source history. Maintains context across follow-up interactions.

---

## Why This Matters to Arya Health

This is literally their next product. Arya has 5 agents managing the caregiver lifecycle (supply side) but nothing handling the patient intake lifecycle (demand side). The Intake Agent was announced as their top priority during their Series A in late 2025 but has not shipped publicly. Building a working prototype that demonstrates the full workflow — inbound calls, fax processing, real-time eligibility checking, outbound follow-up — shows the Arya engineering team that we understand their domain, their architecture, and their product roadmap.
