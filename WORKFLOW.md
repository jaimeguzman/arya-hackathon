# Workflow — IntakeAI End to End (Voice + Fax)

Plain-English, step-by-step walkthrough of how a referral moves through the system, covering both entry channels (phone call and fax/PDF) and every situation the system needs to handle. This is a companion to the other docs, not a new source of truth:

- [`PROJECT.md`](PROJECT.md) remains the product/architecture source of truth.
- [`must-have.md`](must-have.md) remains the safety authority (the 6 non-negotiable guarantees referenced throughout this file).
- [`architecture.md`](architecture.md) has the technical diagrams (mermaid flowcharts/sequence diagrams) this file narrates in prose.

If this file and any of the above ever disagree, `PROJECT.md` > `must-have.md` > `architecture.md` win, in that order — update this file to match, not the other way around.

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
