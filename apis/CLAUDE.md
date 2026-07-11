# CLAUDE.md — apis

Rules for working inside the `apis/` folder. Inherits every rule from the root [`../CLAUDE.md`](../CLAUDE.md) and [`../PROJECT.md`](../PROJECT.md). This file adds folder-specific guidance only.

## API encapsulation (non-negotiable)

- Every API MUST live inside its own named subfolder — one folder per API — e.g. `apis/api_intake/`, `apis/api_twilio/`. Never place API code, `app/`, `tests/`, or loose files directly at the root of `apis/`.
- Each API owns its own `app/`, `tests/`, `pytest.ini`, and `requirements.txt` inside its folder.
- Only folder-level docs (`CLAUDE.md`, `README.md`) live at the `apis/` root.

## Ownership boundaries

- This folder owns the backend application: FastAPI app, endpoints, orchestrator, and sub-agents.
- Do NOT put agent prompt design or knowledge-base content here — that belongs in [`../ai-agents`](../ai-agents).
- Do NOT put Docker Compose, database seed scripts, or infrastructure config here — that belongs in [`../infra`](../infra).

## Hard constraints (non-negotiable)

- **Twilio is mandatory** for all telephony (voice and SMS). Never introduce another provider.
- Reliability, guardrails, security, and scalability are prerequisites, not extras — do not cut them under time pressure without flagging it first.
- **Never** modify `.env`, `.env.test`, `.env.local`, or `.env.prod`. The only editable env file is `.env.example`.
- No hardcoded values, no magic numbers, no static/empty fallbacks. Configuration comes from environment.
- Node.js 20+ for any JS tooling.

## Language

- All code, comments, docs, and commit messages in English.

## Definition of done

A change is done only when: (1) it works, (2) the relevant `.md` docs are updated, (3) another developer can continue without asking the author.
