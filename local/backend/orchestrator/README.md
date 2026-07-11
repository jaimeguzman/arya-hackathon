# Orchestrator + Follow-up Agent (Task 4)

The Intake Agent "brain" (LangGraph) plus the Follow-up Agent. Built offline
against stubs — no Docker, DB, or Twilio needed to run or test.

## What's here

| Path | What it is |
|---|---|
| `orchestrator/state.py` | `ReferralState` — the shared object flowing through the graph, input-agnostic (voice or fax fill the same fields) |
| `orchestrator/eligibility.py` | **Contract** (`EligibilityClient`, `EligibilityResult`) + `StubEligibilityClient`. The seam Task 3 fills. |
| `orchestrator/graph.py` | `build_graph()` / `run_referral()` — the state machine: `intake_received → check_eligibility → decide → followup_{accept,decline,needs_info} → END` |
| `orchestrator/demo.py` | CLI to watch referrals flow through the graph |
| `followup/agent.py` | `FollowUpAgent` — decision → action, plus bounded retry/escalation (`FollowUpPolicy`) |
| `followup/notifications.py` | **Contract** (`NotificationClient`) + `StubNotificationClient`. The seam Task 1 (Twilio) fills. |

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

**Task 3 — Eligibility Agent.** Implement `EligibilityClient.check(...)` returning
an `EligibilityResult` with `status` ∈ {ACCEPT, DECLINE, NEEDS_MORE_INFO}. The
graph imports only the protocol, so replacing `StubEligibilityClient` is a
one-line injection at `build_graph(eligibility_client=...)`. Eligibility is
deterministic code, never an LLM (must-have.md #3) — this module has no LLM import.

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
