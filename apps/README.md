# apps

Frontend applications for IntakeAI — the web UI for fast interaction and demo.

## Scope

- **Intake Dashboard** (React) — the primary UI for the demo and for coordinators:
  - Active referrals and pipeline status (new → processing → eligible → accepted/declined).
  - Extracted data per referral with confidence scores (green/yellow/red).
  - Gap list — what's missing and what actions were taken.
  - Call transcripts for every voice interaction.
  - Caregiver match results and referral-source analytics.
  - Time-to-decision metrics.

See [`../PROJECT.md`](../PROJECT.md) — *Feature 7: Intake Dashboard* and the Tech Stack. This folder owns the UI only; it consumes the backend via the `apis` layer.

## Tech stack

- **Frontend**: React (simple status dashboard for the demo).
- Runs against the FastAPI backend in [`../apis`](../apis).
- Served in local dev via Docker Compose in [`../infra`](../infra).

## Structure (proposed)

```
apps/
├── dashboard/           # React intake dashboard
│   ├── src/
│   └── package.json
└── README.md
```

## Requirements

- Node.js 20+.
- Config from `.env` (never committed); `.env.example` is the reference. Never hardcode API URLs or keys — read them from environment.

## Related

- Backend API consumed by the UI: [`../apis`](../apis)
- Local orchestration / dev server: [`../infra`](../infra)
