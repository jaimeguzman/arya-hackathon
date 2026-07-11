# Voice Agent

The Voice Agent is the mouth and ears of the Intake Agent. It talks to callers over Twilio ConversationRelay, extracts structured data from what they say, and follows instructions from the orchestrator. **It never makes admit/decline decisions** — those come exclusively from the deterministic Eligibility Agent (`check_eligibility()`).

## Two-layer control model (from PROJECT.md)

1. **Static — system prompt per mode.** Before any call starts, the orchestrator assigns one of the three mode prompts in this folder:
   - [`provider-mode.md`](provider-mode.md) — discharge planner / physician office calling in.
   - [`family-mode.md`](family-mode.md) — family member or patient calling in.
   - [`outbound-mode.md`](outbound-mode.md) — agent calling out to fill gaps or confirm details.
2. **Dynamic — mid-call instructions.** During the call, extracted fields go to the orchestrator, which runs the deterministic eligibility check and returns exact instructions for what to say next. The Voice Agent speaks only what comes back.

## Safety gates around every mode (enforced in code, reinforced in prompts)

All three modes run inside the safety-gated call flow implemented in `apis/api_intake/app/safety/`:

| Gate | Code | What it enforces |
|---|---|---|
| Consent gather first | `consent.py` | No data collection before a recorded "yes"; "no" routes to human handoff |
| Tokenize → LLM → rehydrate | `llm_gateway.py` | Raw name/DOB/phone/address/member ID never reach the LLM |
| Deterministic eligibility | `eligibility.py` | ACCEPT/DECLINE/NEEDS_MORE_INFO is plain code, never an LLM opinion |
| Banned-phrase filter | `safe_response.py` | Every response screened before TTS (`speak()` only accepts `SafeResponse`) |
| No silent drop | `handoff.py` | Any failure or 3 failed clarifications degrades to human handoff |

The prompts below repeat the behavioral rules so the LLM cooperates, but the guarantees hold even if it does not — the code is the enforcement layer.

## Shared guardrails (all modes)

- Never give medical advice of any kind. Deflect to "your doctor or care team".
- Never confirm admission, coverage, or a caregiver assignment — only relay the eligibility result the orchestrator provides, with the wording it provides.
- Never promise ("guarantee", "definitely", "100%") — the banned-phrase filter will rewrite these anyway.
- Always tell callers a human coordinator reviews every decision.
- On confusion, distress, or any request for a human: hand off immediately.
- Collect only the fields listed for the mode — nothing else.
