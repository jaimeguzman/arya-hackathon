# CLAUDE.md — apps

Rules for working inside the `apps/` folder. Inherits every rule from the root [`../CLAUDE.md`](../CLAUDE.md) and [`../PROJECT.md`](../PROJECT.md). This file adds folder-specific guidance only.

## Ownership boundaries

- This folder owns the frontend (React dashboard and any web UI).
- Do NOT put backend logic, endpoints, or agent code here — those belong in [`../apis`](../apis) and [`../ai-agents`](../ai-agents).
- The UI consumes the backend through the `apis` layer only — no direct database access from the frontend.

## Hard constraints (non-negotiable)

- **UI/UX is a judging criterion** — keep the dashboard usable and clear; it is part of the bar, not decoration.
- **Security**: no PHI rendered without authentication; never log PHI in the browser console.
- API base URLs, keys, and feature flags are **configuration** read from the environment — never hardcoded, no magic numbers.
- **Never** modify `.env`, `.env.test`, `.env.local`, or `.env.prod`. Only `.env.example` is editable.
- No static/empty fallbacks that hide missing data — surface real state (loading / empty / error).
- **Node.js 20+**. For a Next.js codebase, wire `lint`, `type-check`, and `validate` scripts and run `npm run validate` before large changes.

## Language

- All code, comments, docs, and commit messages in English.

## Definition of done

A change is done only when: (1) it works, (2) the relevant `.md` docs are updated, (3) another developer can run the UI without asking the author.
