# CLAUDE.md

This file contains project-specific instructions for Claude Code.

All content in this repository — code, comments, documentation, commit messages — must be written in English. See [`.claude/rules/language.md`](.claude/rules/language.md). No exceptions, including this file.

## Hackathon Collaboration Protocol (4 developers, parallel work)

This is the standing operating protocol for this repo. It governs every request — questions, architecture suggestions, task creation, code, file edits, debugging, proposals — not only explicit feature requests.

### Mandatory first step: read all documentation

Before doing anything — including answering questions, suggesting architecture, creating tasks, writing code, modifying files, debugging, or proposing improvements:

1. Read every `.md` file in the repository. Currently: [`PROJECT.md`](PROJECT.md), [`must-have.md`](must-have.md), [`architecture.md`](architecture.md), `CLAUDE.md`, `AGENTS.md`, `README.md`, [`.claude/rules/language.md`](.claude/rules/language.md), and anything under `docs/`.
2. Treat these files as the complete context and current state of the project: architecture, existing features, completed work, in-progress work, developer ownership, pending tasks, technical decisions, known issues, future plans.
3. Never make assumptions based only on code files — the `.md` documentation represents the team's shared understanding.

If the `.md` files and the actual code (or other `.md` files) appear inconsistent:
- Identify the mismatch and say so explicitly.
- Update the relevant `.md` file only after confirming the actual implementation state.
- Do not silently overwrite existing decisions — surface the conflict first.

### Official challenge rules — strict, non-negotiable

The organizers' brief is reproduced in full in [`PROJECT.md`](PROJECT.md#official-challenge-brief-strict--do-not-deviate). Treat these as hard constraints on every plan and implementation, not preferences:

- **Twilio is mandatory for telephony.** No sponsor-prize eligibility without it — never propose or accept a non-Twilio telephony path (no other voice/SMS provider as the primary channel).
- The demo must be a **full end-to-end conversation** ("hello to done") for a real healthcare workflow — not a partial flow or a mocked segment.
- **Reliability, guardrails, security, and scalability are prerequisites**, not stretch goals — do not deprioritize them under time pressure without flagging it to the user first.
- **Everything demoed must be built during the sprint.** Pre-work is limited to data prep and scaffolding (see `PROJECT.md`'s Hackathon Build Plan) — do not present pre-built application logic as sprint output.
- Before calling any feature "done," check it against the Compliance Checklist and the Judging Criteria table in `PROJECT.md`.
- If a requested change would violate any of the above (e.g., "let's skip Twilio and mock the call," "let's cut guardrails to save time"), say so explicitly and ask for confirmation before proceeding — do not silently comply.

### Source of truth

- [`PROJECT.md`](PROJECT.md) is the main source of truth and backbone of this project (problem, architecture, data model, database design, tech stack, workflows, build plan). Note: the team's generic prompt refers to it as `projects.md` — this repo's actual file is `PROJECT.md`; always read/update that one.
- All other `.md` files ([`must-have.md`](must-have.md), [`architecture.md`](architecture.md), anything under `docs/`, future feature docs) support and extend `PROJECT.md`. Before implementing anything, verify the proposed work aligns with `PROJECT.md`.
- [`must-have.md`](must-have.md) is the companion safety/priority doc — Part 1 is 5 non-negotiable safety checks (fake data only, tokenize/rehydrate before the LLM, deterministic `check_eligibility()`, consent gather as the first call node, banned-phrase filter before TTS) verified before every demo or test call; Part 2 ranks the core app features. It overrides on anything safety-related.
- [`architecture.md`](architecture.md) is the diagram-and-steps reference (Mermaid diagrams, numbered flows, proposed module layout for file ownership) derived from `PROJECT.md`. If it and `PROJECT.md` disagree, `PROJECT.md` wins — fix `architecture.md` to match, not the reverse.
- Any change involving features, architecture, APIs, database design, components, agent workflows, AI models/prompts, integrations, or dependencies must be reflected in the relevant `.md` file immediately. **Documentation updates are part of implementation, not a separate step.**
- A feature is incomplete until: (1) code is implemented, (2) tests/checks are completed, (3) relevant `.md` files are updated.

### Task creation rules

Whenever creating a development plan or breaking down work, always create exactly 4 parallel tasks — one independent track per developer. Each task must:

- Have a clear owner.
- Own separate files/classes/modules — never assign two developers to the same file.
- Avoid modifying another developer's files.
- Be independently executable, with clear inputs and outputs.

Task template (use for every task):

```
Developer:
Goal:
Files Owned:
Classes/Functions Owned:
Dependencies:
Implementation Steps:
Documentation To Update:
Expected Completion Criteria:
```

Example:

```
Task 1 - Backend Developer

Goal:
Create authentication workflow.

Files Owned:
- auth/service.py
- auth/models.py

Documentation:
- docs/auth.md

Dependencies:
None

Completion:
Authentication API works and documentation updated.
```

### File and class ownership rules

Before creating any file/class, evaluate:

1. Which developer owns this?
2. Will another developer need to edit this?
3. Can this be isolated into its own module?
4. Does this create merge conflicts?

Prefer: small independent modules, clear interfaces, separate service layers, separate feature folders.

Avoid: multiple developers editing the same files, large shared utility files, monolithic classes, hidden dependencies.

If a shared component is unavoidable:

1. Define the interface first.
2. Document ownership.
3. Minimize future modifications.
4. Update architecture documentation.

### Development workflow (every request)

**Step 1 — Synchronize context.** Read all `.md` files, project structure, and relevant implementation files. Summarize:

```
Current Project Understanding:
- Existing architecture:
- Current features:
- Active developers/tasks:
- Relevant documentation:
```

**Step 2 — Plan changes.** Before coding, explain:

```
Proposed Change:
- Feature:
- Architecture impact:
- Files affected:
- Developer ownership:
- Documentation updates required:
```

**Step 3 — Parallelize work.** Create 4 independent tasks (per the template above). Ensure minimal overlap, no conflicting files, clear ownership.

**Step 4 — Implement.** Follow existing architecture. Respect file ownership. Never modify files owned by others. Never introduce undocumented behavior.

**Step 5 — Immediately update documentation.** After any change, update the relevant `.md` file(s) with: what changed, why it changed, files modified, new architecture decisions, API changes, usage instructions, testing status, known limitations. Do this immediately — never wait until the end of the feature.

### Documentation synchronization rules

Whenever anything changes, immediately update:

- `PROJECT.md` if project direction or features change.
- `must-have.md` if anything safety-related or a core must-have feature changes.
- Relevant feature documentation, architecture documentation, API documentation, setup documentation.

The next developer should be able to understand the current state only by reading the `.md` files — never by asking a teammate.

### Coding principles

Prioritize: fast hackathon execution, working prototype, modular architecture, clear ownership, low merge conflicts, easy handoff between developers, documentation-driven development.

Avoid: unnecessary refactoring, large cross-cutting changes, editing another developer's modules, features without documentation, decisions that exist only in chat messages.

### Required response format

For every non-trivial request, respond using this structure:

1. **Documentation Review** — which `.md` files were reviewed, summary of relevant context.
2. **Understanding** — current state, existing constraints.
3. **Proposed Approach** — architecture changes, files affected.
4. **Four Parallel Tasks** — developer ownership, files/classes owned, documentation updates (per the task template above).
5. **Implementation Plan** — ordered steps.
6. **Documentation Updates** — exact `.md` files to update.
7. **Risks** — conflicts, dependencies, potential issues.

### Definition of done

A feature is not complete until: (1) it works, (2) tests/checks are completed, (3) the relevant documentation is updated, (4) another developer can understand and continue the work without asking the original developer.

### Final rule

The repository documentation and code must always stay synchronized. Before thinking, read all `.md` files. Before changing code, check documentation. After changing code, update documentation immediately. The goal: any team member can join the project at any moment, read the `.md` files, and fully understand the current state without asking anyone.
