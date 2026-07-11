# CLAUDE.md — services

Rules for working inside the `services/` folder. Inherits every rule from the root [`../CLAUDE.md`](../CLAUDE.md) and [`../PROJECT.md`](../PROJECT.md). This file adds folder-specific guidance only.

## Ownership boundaries

- This folder owns background and scheduled work: the scheduler, retry/escalation logic, and queue consumers.
- Do NOT put HTTP/WebSocket endpoints here — those belong in [`../apis`](../apis).
- Do NOT put agent prompts or conversation flows here — those belong in [`../ai-agents`](../ai-agents).
- Services trigger actions through the `apis` layer; they do NOT own Twilio conversation flows directly.

## Hard constraints (non-negotiable)

- **Twilio only** for any telephony action (calls, SMS) triggered by a job.
- Reliability is a prerequisite: retry logic and escalation must be explicit and bounded (e.g. escalate to a human after 3 failed attempts) — no silent infinite retries.
- Scheduling intervals and retry limits are **configuration**, not magic numbers hardcoded in the source.
- **Never** modify `.env`, `.env.test`, `.env.local`, or `.env.prod`. Only `.env.example` is editable.
- No hardcoded values, no static/empty fallbacks.
- Node.js 20+ for tooling.

## Language

- All code, comments, docs, and commit messages in English.

## Definition of done

A change is done only when: (1) it works, (2) the relevant `.md` docs are updated, (3) another developer can run and reason about the jobs without asking the author.
