# services

Background and scheduled services for IntakeAI — work that runs outside the request/response cycle.

## Scope

- **Scheduler / Follow-up service** — retry logic and callback scheduling for the Follow-up Agent:
  - Retry a call in 2 hours if it went to voicemail.
  - Follow up next morning if an SMS gets no response.
  - Escalate to a human coordinator after 3 failed contact attempts.
- Timed jobs (e.g. "follow up in 4 hours if the F2F note is not received").
- Any worker that consumes queued work (document processing queue, outbound action queue).

See [`../PROJECT.md`](../PROJECT.md) — *Feature 4: Automated Outbound Follow-up* and the Redis "follow-up retry scheduling" notes. This folder owns scheduling and background workers; the agent logic they invoke lives in [`../ai-agents`](../ai-agents) and the HTTP surface in [`../apis`](../apis).

## Scheduling backbone

- **Redis** holds retry schedules, active-call state, and rate-limit counters for Twilio calls.
- Services read due jobs and trigger actions (outbound call, SMS, escalation) through the `apis` layer — they do not talk to Twilio conversation flows directly.

## Structure (proposed)

```
services/
├── scheduler/           # Due-job runner (retries, callbacks, escalations)
├── workers/             # Queue consumers (document pipeline, outbound actions)
└── README.md
```

## Requirements

- Node.js 20+ for tooling.
- Config from `.env` (never committed); `.env.example` is the reference.

## Related

- Application services and endpoints: [`../apis`](../apis)
- Agent behavior invoked by jobs: [`../ai-agents`](../ai-agents)
- Redis provisioning: [`../infra`](../infra)
