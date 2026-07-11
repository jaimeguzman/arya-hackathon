# CLAUDE.md — ai-agents

Rules for working inside the `ai-agents/` folder. Inherits every rule from the root [`../CLAUDE.md`](../CLAUDE.md) and [`../PROJECT.md`](../PROJECT.md). This file adds folder-specific guidance only.

## Ownership boundaries

- This folder owns agent behavior: system prompts, conversation flows, guardrail definitions, and knowledge grounding.
- Do NOT put FastAPI endpoints or WebSocket handlers here — that belongs in [`../apis`](../apis).
- Do NOT put infrastructure config or seed scripts here — that belongs in [`../infra`](../infra).

## Hard constraints (non-negotiable)

- **Guardrails are prerequisites, not extras.** Every agent must: never give medical advice, never confirm admission before eligibility is verified, escalate to a human on low confidence, and stay within HIPAA-appropriate boundaries.
- **Knowledge must be grounded** — decisions trace back to real data (ICD-10, Neo4j, coverage rules), never free-floating LLM guesses.
- Telephony is **Twilio only** — never design a flow that assumes another provider.
- **Never** modify `.env`, `.env.test`, `.env.local`, or `.env.prod`. Only `.env.example` is editable.
- No hardcoded values, no magic numbers, no static/empty fallbacks.

## Language

- All prompts, docs, comments, and commit messages in English. Agent-facing conversation copy may be in the caller's language, but source content stays English.

## Definition of done

A change is done only when: (1) it works, (2) the relevant `.md` docs are updated, (3) another developer can continue without asking the author.
