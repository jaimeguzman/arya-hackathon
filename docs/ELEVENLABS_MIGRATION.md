# Twilio → ElevenLabs Migration Plan

**Team decision (2026-07-11, confirmed by the user):** the project migrates all telephony and voice from Twilio to the **ElevenLabs Agents Platform**, knowingly forgoing Twilio sponsor-prize eligibility. Follow-up notifications move from SMS to **ElevenLabs outbound calls**. This document is the source of truth for the migration; `CLAUDE.md`'s challenge-rules section points here. The organizers' brief in `PROJECT.md` remains intact as the historical record.

**Coordination constraint (agreed):** documentation and task planning land first. **No code refactor starts until the autonomous coder agent's in-flight work is committed or paused** — `apis/api_intake/app/routes/twilio.py`, `WORKFLOW.md`, `PROJECT.md`, and `eligibility_agent.py` currently carry its uncommitted edits, and its branch is actively building voice features. The `local/` folder is out of scope for this migration entirely (workspace boundary in `CLAUDE.md`); its Twilio references get handled at merge day per [`MERGE_DAY_RECONCILIATION.md`](MERGE_DAY_RECONCILIATION.md).

## Architecture mapping

| Today (Twilio) | Target (ElevenLabs) |
|---|---|
| Twilio phone number + webhook | ElevenLabs Agents native telephony (or SIP trunk) phone number |
| ConversationRelay WebSocket (`/twilio/conversation-relay`) | ElevenLabs Agent with **Custom LLM** endpoint pointing at our FastAPI backend — every model turn still passes through our `llm_gateway` (tokenize → LLM → rehydrate) and `safe_response` filter |
| Twilio STT/TTS via ConversationRelay | ElevenLabs native STT + TTS |
| Twilio SMS (follow-up confirmations, retries) | ElevenLabs **outbound calls** with the existing Outbound mode (single-mission calls), same retry-in-2h / escalate-after-3-attempts logic |
| `apis/api_intake/app/routes/twilio.py` | `apis/api_intake/app/routes/elevenlabs.py` — **seam RESOLVED (Task 1, 2026-07-11)**: a second transport route module inside `api_intake`, not a new API folder (it is the same intake API; a separate folder would force cross-importing `CallSession` and the safety layer). Implemented: `POST /elevenlabs/custom-llm/v1/chat/completions` (Bearer-authenticated, OpenAI-compatible, JSON or single-chunk SSE) + `POST /elevenlabs/webhooks/post-call` (HMAC-validated, 403 on invalid). Required ElevenLabs agent config: first message = `CONSENT_DISCLOSURE`, Custom LLM base URL = `{PUBLIC_BASE_URL}/elevenlabs/custom-llm` with the Bearer token, "extra body" enabled (sends `conversation_id`), `end_call` system tool enabled, post-call webhook pointed at `/elevenlabs/webhooks/post-call` |

**Invariants that do NOT change (must-have.md Part 1 — all six):** consent gather first, tokenize/rehydrate boundary, deterministic `check_eligibility()`, banned-phrase filter before TTS, no silent call drop, fake data only. The migration must re-verify each guarantee on the new call path before any demo.

**Known risks:**
- ElevenLabs webhook/Custom-LLM authentication (HMAC signature validation) must replace Twilio request validation — a call path without signature checks is a regression, not a migration.
- The 22 passing features include 6 voice features (40–45) verified against ConversationRelay message shapes; each needs an ElevenLabs-equivalent test before its checkbox stays checked.
- Native telephony numbers in ElevenLabs may route via SIP; confirm inbound number availability for the demo region early (Task 3, day 1).

---

## Four parallel tasks

```
Task 1 — Voice call path migration (BLOCKING for demo)

Developer: Person 1
Goal: Replace the ConversationRelay WebSocket call path with an ElevenLabs
Agent wired to our backend, preserving all 6 safety gates and the 4 call
modes (provider / family / patient / outbound).
Files Owned:
- apis/api_elevenlabs/ (new: app/, tests/, README.md)
- ai-agents/voice-agent/ (agent config, mode prompts adapted to ElevenLabs
  prompt format)
Classes/Functions Owned:
- ElevenLabs webhook/Custom-LLM route handlers, HMAC signature validation,
  CallSession adapter (map ElevenLabs conversation events onto the existing
  mode_router / provider_intake / family_intake turn logic)
Dependencies:
- Task 3's provisioned ElevenLabs agent + credentials (build against the
  documented event shapes in the meantime — don't block)
- Autonomous agent's twilio.py edits committed (do NOT modify
  apis/api_intake/app/routes/twilio.py until then; build alongside it)
Implementation Steps:
1. Scaffold apis/api_elevenlabs (FastAPI app, health, tests) per the API
   encapsulation rule
2. Signature-validated webhook + Custom LLM endpoint routing every turn
   through llm_gateway + safe_response (guarantees #2, #5)
3. Consent gather as the literal first agent node (#4)
4. Port mode detection + provider/family/patient flows onto the new events
5. Failure handoff on every turn (#6) + transcript capture
6. Port features 40–45 tests to the ElevenLabs path
Documentation To Update: apis/README.md, ai-agents/README.md,
docs/ARCHITECTURE.md voice sections
Expected Completion Criteria: A test call through an ElevenLabs agent
completes provider and family scenarios end-to-end with all 6 must-have
guarantees passing on the new path (safety suite green).
```

```
Task 2 — Follow-up Agent: SMS → outbound calls

Developer: Person 2
Goal: Replace the SMS-based follow-up contract with ElevenLabs outbound
calls, keeping the bounded retry/escalation semantics (must-have.md #6).
Files Owned:
- services/followup/ (new canonical Follow-up Agent module + tests)
Classes/Functions Owned:
- OutboundCallClient (ElevenLabs outbound-call API wrapper),
  FollowUpAgent retry scheduler (retry in 2h, escalate after 3 attempts),
  call-outcome handling (answered / voicemail / no-answer)
Dependencies:
- Task 3's ElevenLabs credentials + outbound-enabled phone number
- Task 1's outbound-mode agent config (the outbound call re-enters the
  same safety-gated flow — no separate unguarded path)
Implementation Steps:
1. Define the NotificationClient-equivalent interface for outbound calls
   (mirror local/backend/followup/notifications.py semantics WITHOUT
   touching local/)
2. Implement ElevenLabs outbound call initiation + status polling/webhook
3. Retry scheduling: voicemail/no-answer → retry in 2 hours
4. 3-attempt escalation to human coordinator, never infinite retries
5. Tests: stub client covering answered / voicemail / escalation paths
Documentation To Update: services/README.md, docs/ARCHITECTURE.md
follow-up section
Expected Completion Criteria: A DECLINE/NEEDS_MORE_INFO decision triggers
an outbound follow-up call attempt; simulated failures produce exactly the
documented retry/escalation behavior in tests.
```

```
Task 3 — Platform provisioning + configuration (do first, day 1)

Developer: Person 3
Goal: Stand up the ElevenLabs account, agent, and phone number; define all
configuration and secrets handling so Tasks 1–2 have real targets.
Files Owned:
- .env.example (ElevenLabs variables added, Twilio variables marked
  deprecated — never touch real .env files)
- docs/ELEVENLABS_SETUP.md (new: provisioning runbook)
- infra/ ElevenLabs-related config (if any)
Classes/Functions Owned:
- Settings additions in a new shared config surface for api_elevenlabs
  (coordinate the interface with Task 1 before coding)
Dependencies:
- None — unblocks everyone; start immediately
Implementation Steps:
1. Create ElevenLabs workspace + API key; document plan/limits relevant
   to the demo (concurrent calls, outbound enablement)
2. Provision inbound phone number (native or SIP) for the demo region
3. Create the agent shell (voice, language, Custom LLM endpoint slot)
4. Update .env.example: ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID,
   ELEVENLABS_PHONE_NUMBER_ID, webhook secret
5. Write docs/ELEVENLABS_SETUP.md end-to-end runbook (account → first call)
Documentation To Update: docs/ELEVENLABS_SETUP.md, infra/README.md
Expected Completion Criteria: A colleague can follow the runbook to place
a raw test call to the provisioned number, and Tasks 1–2 have working
credentials via .env.example variable names.
```

```
Task 4 — Documentation restructure + Twilio decommission plan

Developer: Person 4
Goal: Bring every doc in the canonical tree in line with the ElevenLabs
decision, and write the decommission plan for the Twilio code path.
Files Owned:
- PROJECT.md (add the decision record + tech-stack update; keep the
  organizers' brief verbatim as historical), WORKFLOW.md, docs/ARCHITECTURE.md,
  docs/BACKLOG.md, must-have.md (channel wording only — guarantees unchanged),
  per-folder README.md/CLAUDE.md files with Twilio references
  (apis/, ai-agents/, services/, infra/)
- docs/TWILIO_DECOMMISSION.md (new: what gets deleted when, feature_list
  renumbering impact, which of features 40–45 must be re-verified)
Classes/Functions Owned:
- None (documentation only — deletes no code; twilio.py removal happens
  only after Task 1's path is green AND the autonomous agent's branch
  has merged)
Dependencies:
- WAIT for the autonomous agent's uncommitted edits on WORKFLOW.md /
  PROJECT.md / twilio.py to land before editing those specific files
Implementation Steps:
1. PROJECT.md: decision record, tech stack table, build plan deltas
2. WORKFLOW.md: replace Twilio references in Path A narration + progress
   tables (also fixing the stale "Voice Agent not started" rows)
3. Sweep remaining .md files (grep -ril twilio, excluding local/)
4. Write docs/TWILIO_DECOMMISSION.md with the deletion checklist
Documentation To Update: (this task IS documentation)
Expected Completion Criteria: `grep -ril twilio` over the canonical tree
returns only PROJECT.md's historical brief, the decommission doc, and
this migration doc; no doc instructs anyone to build on Twilio.
```

**Order:** Task 3 starts immediately (unblocks credentials). Tasks 1 and 2 start against documented event shapes without waiting. Task 4 starts on the files without foreign uncommitted edits and finishes once the autonomous agent's branch lands.
