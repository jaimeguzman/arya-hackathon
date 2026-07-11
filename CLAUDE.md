# CLAUDE.md

This file contains project-specific instructions for Claude Code.
Este archivo contiene instrucciones específicas del proyecto para Claude Code.

## Hackathon Collaboration Protocol (4 developers, parallel work)

This is the standing operating protocol for this repo. Apply it any time a team member asks for a feature, change, task breakdown, or plan — not just when explicitly invoked.

### Official challenge rules — strict, non-negotiable

The organizers' brief is reproduced in full in [`PROJECT.md`](PROJECT.md#official-challenge-brief-strict--do-not-deviate). Treat these as hard constraints on every plan and implementation, not preferences:

- **Twilio is mandatory for telephony.** No sponsor-prize eligibility without it — never propose or accept a non-Twilio telephony path (no other voice/SMS provider as the primary channel).
- The demo must be a **full end-to-end conversation** ("hello to done") for a real healthcare workflow — not a partial flow or a mocked segment.
- **Reliability, guardrails, security, and scalability are prerequisites**, not stretch goals — do not deprioritize them under time pressure without flagging it to the user first.
- **Everything demoed must be built during the sprint.** Pre-work is limited to data prep and scaffolding (see `PROJECT.md`'s Hackathon Build Plan) — do not present pre-built application logic as sprint output.
- Before calling any feature "done," check it against the Compliance Checklist and the Judging Criteria table in `PROJECT.md`.
- If a requested change would violate any of the above (e.g., "let's skip Twilio and mock the call," "let's cut guardrails to save time"), say so explicitly and ask for confirmation before proceeding — do not silently comply.

### Source of truth

- [`PROJECT.md`](PROJECT.md) is the single source of truth and backbone of this project (problem, architecture, data model, database design, tech stack, workflows, build plan). Note: the team's generic prompt refers to it as `projects.md` — this repo's actual file is `PROJECT.md`; always read/update that one.
- Before suggesting, creating, modifying, or deleting any feature, check `PROJECT.md` first.
- Any architectural decision, feature addition, implementation change, dependency change, API change, database schema change, or major workflow update must be reflected in the relevant `.md` doc immediately — documentation must never lag behind implementation.

### Task creation rules

- Break work into exactly 4 parallelizable tasks whenever possible — there are 4 developers working simultaneously.
- Tasks must let developers work independently without blocking each other.
- Never assign two people to modify the same files, classes, modules, or core components.
- Each task must specify: Owner/developer, Objective, Files/classes/modules owned, Dependencies (if any), Expected output, Documentation files to update.

Example shape:

```
Task 1 (Developer A): Build authentication module
- Owns: auth_service.py, auth_models.py
- Updates: docs/auth.md

Task 2 (Developer B): Build database layer
- Owns: database.py, schemas.py
- Updates: docs/database.md

Task 3 (Developer C): Build frontend components
- Owns: components/dashboard/
- Updates: docs/frontend.md

Task 4 (Developer D): Build testing and evaluation pipeline
- Owns: tests/, evaluation.md
- Updates: docs/testing.md
```

### File and class ownership rules

- Design architecture so each developer owns separate files/classes whenever possible.
- Avoid shared files that multiple developers need to modify; prefer modular, loosely-coupled architecture.
- Every class/module has a clear owner.
- Before creating a new class/file, ask: Who owns this? Will another developer need to modify it? Can it be isolated into its own module? Could it cause merge conflicts?
- If a shared component is unavoidable: document ownership clearly, define the interface/contract before implementation, and minimize the surface area multiple people need to touch.

### Development workflow for every feature

1. **Review** — `PROJECT.md`, existing architecture docs, current implementation state.
2. **Plan** — break into 4 independent tasks, assign ownership, define file boundaries.
3. **Implement** — modify only owned files; avoid unnecessary refactors of someone else's work; follow existing patterns.
4. **Document** — immediately update the relevant `.md` file(s) with what changed, why, how to use it, dependencies, known limitations.
5. **Sync** — check for documentation updates from other developers before starting new work.

### Coding principles

Prioritize: clean modular architecture, low coupling, clear ownership boundaries, fast iteration, hackathon-friendly implementation, working prototype over unnecessary complexity.

Avoid: large refactors during parallel development, modifying files owned by others, hidden dependencies, shipping features without doc updates.

### Required response format for implementation plans

When proposing changes, structure the response as:

1. **Current Understanding** — what exists today, relevant doc references.
2. **Proposed Changes** — architecture impact, files/classes affected.
3. **Parallel Task Breakdown** — 4 independent tasks with ownership (per the rules above).
4. **Documentation Updates Required** — every `.md` file that must change.
5. **Risks** — possible conflicts, dependencies, integration concerns.

### Definition of done

A feature is not complete until: (1) it works, (2) the relevant documentation is updated, (3) another developer can understand and continue the work without asking the original developer.
