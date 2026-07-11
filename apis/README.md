# apis

Backend services for IntakeAI — the FastAPI application layer, HTTP/WebSocket endpoints, and agent orchestration wiring.

## Scope

- FastAPI application (health checks, WebSocket endpoint for Twilio ConversationRelay).
- HTTP endpoints: `POST /eligibility-check`, `POST /process-document`.
- LangGraph orchestrator (Intake Agent) and sub-agents: Eligibility, Document Pipeline, Voice, Follow-up.
- Twilio Programmable SMS / Voice integration for outbound follow-up.

See [`../PROJECT.md`](../PROJECT.md) for the full architecture, data model, and workflows. This folder owns application code only.

## Tech stack

- **Backend**: FastAPI (Python)
- **Agent orchestration**: LangGraph
- **LLM**: Gemini Flash
- **Telephony**: Twilio ConversationRelay (voice), Twilio Programmable SMS
- **Data access**: PostgreSQL, Neo4j, Redis, pgvector

## Structure (proposed)

```
apis/
├── app/                 # FastAPI application
│   ├── main.py          # App entrypoint, routers, health checks
│   ├── agents/          # Orchestrator + sub-agents (LangGraph)
│   ├── routes/          # HTTP + WebSocket endpoints
│   └── db/              # Database clients and queries
├── tests/               # API and agent tests
└── README.md
```

## Requirements

- Node.js 20+ for any tooling; Python for the service runtime.
- Environment variables come from `.env` (never committed). Use `.env.example` as reference.

## Related

- Infrastructure and local orchestration: [`../infra`](../infra)
- Agent design and prompts: [`../ai-agents`](../ai-agents)
