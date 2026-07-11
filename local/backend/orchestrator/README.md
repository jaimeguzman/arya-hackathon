# Orchestrator + Follow-up Agent (Task 4)

The Intake Agent "brain" (LangGraph) plus the Follow-up Agent. Built offline
against stubs — no Docker, DB, or Twilio needed to run or test.

## What's here

| Path | What it is |
|---|---|
| `orchestrator/state.py` | `ReferralState` — the shared object flowing through the graph, input-agnostic (voice or fax fill the same fields) |
| `orchestrator/eligibility.py` | Orchestrator's `EligibilityClient` contract + `EligibilityResult`, `StubEligibilityClient` (tiny hermetic fixture), and **`RealEligibilityClient`** (the real connection — graph default) |
| `orchestrator/eligibility_core.py` | The team's deterministic `check_eligibility()` decision core (must-have.md #3), **vendored** from `develop:apis/api_intake/app/safety/eligibility.py`. Pure function, no DB, no LLM. |
| `orchestrator/eligibility_data.py` | The data-fetch layer: `JsonEligibilityDataProvider` (offline), `DbEligibilityDataProvider` (Postgres+Neo4j), `FallbackDataProvider` (DB→JSON) |
| `orchestrator/graph.py` | `build_graph()` / `run_referral()` — the state machine: `intake_received → check_eligibility → decide → followup_{accept,decline,needs_info} → END` |
| `orchestrator/demo.py` | CLI to watch referrals flow through the graph |
| `followup/agent.py` | `FollowUpAgent` — decision → action, plus bounded retry/escalation (`FollowUpPolicy`) |
| `followup/notifications.py` | **Contract** (`NotificationClient`) + `StubNotificationClient`. The seam Task 1 (Twilio) fills. |

## How eligibility is wired (Task 3 ↔ Task 4)

```
graph.check_eligibility node
   → RealEligibilityClient.check(zip, payer, plan, service_type, ...)
       → eligibility_data provider  (DbEligibilityDataProvider, falls back to JSON when Docker is down)
             served_zips()        ← Postgres service_areas  / local/data/service_areas.json
             accepted_plans()     ← Postgres insurance_contracts / insurance_rules.json
             caregivers_available ← Postgres caregivers+certs+areas + Neo4j service→cert / caregiver_roster.json
       → check_eligibility(...)   ← the team's deterministic core (eligibility_core.py)  →  ACCEPT/DECLINE/NEEDS_MORE_INFO
       → RealEligibilityClient maps the verdict + computes missing_documents
```

Swapping data sources or the decision core requires no graph change — inject a
different client via `build_graph(eligibility_client=...)` or a different data
provider via `RealEligibilityClient(data_provider=...)`.

## Run it

```bash
cd local
./scripts/test_orchestrator.sh                       # tests + demo, all offline
# or individually:
export PYTHONPATH="$PWD"
python -m pytest backend/orchestrator/tests backend/followup/tests -v
python -m backend.orchestrator.demo                  # all scenarios
python -m backend.orchestrator.demo --scenario decline
```

## Contracts other tasks fill (build against these, no changes needed here)

**Task 3 — Eligibility.** ✅ Connected. The team's deterministic core is vendored
in `eligibility_core.py` and driven by `eligibility_data.py`. When the folder
trees are reconciled, collapse `eligibility_core.py` back to the single team copy
(don't let the two diverge — tracked in NEXT-STEPS). The live DB path needs Docker
up to verify end-to-end; the JSON path is verified offline in
`tests/test_eligibility_integration.py`.

**Task 1 — Twilio.** Implement `NotificationClient.send_sms` / `place_call`. Inject
via `FollowUpAgent(notifier=...)`. Twilio is mandatory (PROJECT.md brief); the stub
sends nothing, it only records intended sends.

## Safety properties enforced here

- **must-have.md #3** — the orchestrator's decision comes only from the injected
  eligibility client's result; no LLM in the decision path.
- **must-have.md #6** — follow-up retries are bounded by `FollowUpPolicy.max_attempts`
  (default 3), then escalate to a human. No infinite retry, no silent drop.

## Not built yet (deliberately out of scope for this task)

Real DB-backed eligibility (Task 3), real Twilio (Task 1), the FastAPI router that
mounts this (`main.py`, coordinate with Task 1), and the dashboard (later). The graph
is exposed as `run_referral()` / `build_graph()` for whoever wires the HTTP surface.
