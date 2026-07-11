# CLAUDE.md — infra

Rules for working inside the `infra/` folder. Inherits every rule from the root [`../CLAUDE.md`](../CLAUDE.md) and [`../PROJECT.md`](../PROJECT.md). This file adds folder-specific guidance only.

## Ownership boundaries

- This folder owns infrastructure: Docker Compose, database migrations and seed scripts, Redis setup, and Twilio provisioning config.
- Do NOT put application code or agent prompts here — those belong in [`../apis`](../apis) and [`../ai-agents`](../ai-agents).

## Hard constraints (non-negotiable)

- **Never** modify `.env`, `.env.test`, `.env.local`, or `.env.prod` — this is critical. The ONLY editable env file is `.env.example`, which is the reference.
- **Twilio is mandatory** for telephony. Provision Twilio numbers and ConversationRelay only — no other telephony provider.
- Security is a prerequisite: databases must support encrypted storage of PHI; no PHI in logs. HIPAA-eligible configuration.
- Scalability must be explainable: modular services, each scaling independently.
- No hardcoded secrets, no magic numbers. Secrets come from the environment.
- Node.js 20+ for tooling.

## Language

- All config, comments, docs, and commit messages in English.

## Definition of done

A change is done only when: (1) it works, (2) the relevant `.md` docs are updated, (3) another developer can bring the stack up without asking the author.
