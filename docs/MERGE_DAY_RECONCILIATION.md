# Merge-Day Reconciliation Checklist

Executed ONCE, deliberately, when the autonomous coder agent's branch
(`autonomous-coder/*`) merges into the integration line. Until that day,
`local/` is the agent's untouchable workspace (see CLAUDE.md "Workspace
Boundaries"). Do not run any step below while the agent is active.

## Why this exists

The repo intentionally carries two parallel trees. The vendored copy in
`local/backend/orchestrator/eligibility_core.py` says it itself:

> "When the folder trees are reconciled, this should collapse back to a single
> copy — tracked as a reconciliation item, do not let the two diverge."

This document is that reconciliation item.

## The integration contract (already in force — no waiting)

| Seam | Canonical side | local/ side |
|---|---|---|
| Eligibility decision | `POST /eligibility-check` (`apis/api_intake`) — ACCEPT / DECLINE / NEEDS_MORE_INFO with reasons | `EligibilityClient` protocol (`local/backend/orchestrator/eligibility.py`) with a vendored copy of the same deterministic core |
| Decision semantics | `must-have.md` #3: deterministic code, never LLM; bias to NEEDS_MORE_INFO on ambiguity | identical (vendored) |
| Status write path | `app/eligibility/status_writer.set_intake_status` (guarded) | orchestrator writes intake status via graph nodes |

## Collapse map (execute in this order)

1. **Deterministic core** — delete `local/backend/orchestrator/eligibility_core.py`;
   point imports at `app/safety/eligibility.py` (`CoreEligibilityStatus` →
   `EligibilityStatus`, `CoreEligibilityResult` → `EligibilityResult`). The two
   are verbatim-identical today; diff before deleting to confirm no divergence.
2. **Orchestrator** — move `local/backend/orchestrator/{state,graph,eligibility,demo}.py`
   → `apis/api_intake/app/orchestrator/` rewriting `from backend.` → `from app.`.
   Rewire `RealEligibilityClient` to call the canonical engine
   (`app.agents.eligibility_agent.decide`) instead of
   `eligibility_data.py` — then delete `eligibility_data.py` (its JSON provider
   reads the camelCase `local/data` shapes that die in step 5).
3. **Follow-up + guardrails + prompts** — move `local/backend/followup/`,
   `local/backend/services/guardrail_service.py`, `local/backend/prompts/`
   → `apis/api_intake/app/`. `guardrail_service` default rules path →
   `data/reference/guardrail_rules.json` (migrated in step 5).
4. **Models** — decide whether `local/backend/models/` (SQLAlchemy async) is still
   needed: the canonical tree talks to PostgreSQL via `psycopg` against the
   `infra/init/postgres_init.sql` schema. If nothing else imports the SQLAlchemy
   layer after steps 1–3, drop it instead of migrating (requires no
   sqlalchemy/asyncpg deps in `apis/`).
5. **Data** — migrate the two `local/data` files with no canonical equivalent:
   `guardrail_rules.json`, `medications_reference.json` → `data/reference/`.
   The remaining 6 camelCase files are derivations of canonical `data/` files —
   verify nothing imports them after step 2, then delete `local/data/`.
6. **Infra** — move `local/docker-compose.yml` → `infra/docker-compose.yml` and
   `local/backend/db/postgres_init.sql` → `infra/init/postgres_init.sql`; update
   the volume mount to `./init/postgres_init.sql`; set `POSTGRES_DB: intakeai_demo`
   (the db_guard allowlist name). `init.sh` already expects these paths.
7. **Tests** — move `local/backend/tests/` + `local/backend/orchestrator/tests/`
   → `apis/api_intake/tests/` with the same import rewrite; the full suite and
   `make safety` must pass before the merge commit lands.
8. **Docs** — update WORKFLOW.md (remove the boundary note), CLAUDE.md
   (remove the Workspace Boundaries section or mark it historical),
   `docs/ARCHITECTURE.md` §8, `data/README.md`, and delete this file's
   "do not run" warning by replacing it with the merge commit hash.

## Verification gate

- [ ] `cd apis/api_intake && make test` — full suite green
- [ ] `make safety` — the 6 must-have guarantees green
- [ ] `POST /eligibility-check` returns identical decisions for the 4
      `data/synthetic/sample_referrals.json` scenarios before and after
- [ ] `grep -r "from backend\." apis/ local/` returns nothing
- [ ] `local/` directory no longer exists
