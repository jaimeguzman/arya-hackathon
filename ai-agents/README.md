# ai-agents

Design and configuration for IntakeAI's conversational and processing agents — prompts, conversation flows, guardrails, and knowledge grounding.

## Scope

- Agent definitions and system prompts for the Voice Agent modes (Provider, Family, Outbound).
- Document Pipeline agents (Validation, Correction, Cross-Reference).
- Eligibility Agent decision logic specs and prompt templates.
- Guardrail definitions (clinical, operational, data) — see [Feature 6 in PROJECT.md](../PROJECT.md).
- Knowledge grounding: ICD-10 subset, diagnosis→service→certification mappings, payer coverage rules, agency service area, caregiver roster, referral-source history — all seeded in [`../data`](../data), see [`../data/README.md`](../data/README.md).

See [`../PROJECT.md`](../PROJECT.md) for the full agent architecture and the two-layer Voice Agent control model, and [`../WORKFLOW.md`](../WORKFLOW.md) for the plain-English end-to-end walkthrough. This folder owns agent behavior and prompt design — not the FastAPI wiring (that lives in [`../apis`](../apis)).

## Agent inventory

| Agent | Role |
|---|---|
| Intake Agent (Orchestrator) | Manages workflow state, routes tasks, makes admit/decline decisions |
| Voice Agent | Handles Twilio calls; listens, speaks, extracts data; does NOT decide |
| Eligibility Agent | Traverses PostgreSQL + Neo4j; returns ACCEPT / DECLINE / NEEDS_MORE_INFO |
| Document Pipeline agents | Validation, Correction, Cross-Reference over extracted fields |
| Follow-up Agent | SMS/email confirmations, retry logic, callback scheduling |

## Guardrails (must always hold)

- Never gives medical advice.
- Never confirms admission before the Eligibility Agent verifies.
- Escalates to a human on low confidence.
- Maintains HIPAA-appropriate conversation boundaries and an audit trail.

## Related

- Application wiring and endpoints: [`../apis`](../apis)
- Local orchestration and databases: [`../infra`](../infra)
