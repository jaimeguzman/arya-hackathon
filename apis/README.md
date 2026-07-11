# apis

Backend services for IntakeAI — the FastAPI application layer, HTTP/WebSocket endpoints, and agent orchestration wiring.

## Scope

- FastAPI application (health checks, WebSocket endpoint for Twilio ConversationRelay).
- HTTP endpoints: `POST /eligibility-check`, `POST /process-document`.
- LangGraph orchestrator (Intake Agent) and sub-agents: Eligibility, Document Pipeline, Voice, Follow-up.
- Twilio Programmable SMS / Voice integration for outbound follow-up.

See [`../PROJECT.md`](../PROJECT.md) for the full architecture, data model, and workflows. This folder owns application code only.

## Encapsulation

Every API lives in its own named subfolder — one folder per API — never loose at the `apis/` root (see the root [`../CLAUDE.md`](../CLAUDE.md) "API encapsulation rule"). Each API owns its own `app/`, `tests/`, `pytest.ini`, and `requirements.txt` inside its folder.

Current APIs:

- [`api_intake/`](api_intake) — core IntakeAI backend: FastAPI app, safety layer, and orchestration wiring.

## Tech stack

- **Backend**: FastAPI (Python)
- **Agent orchestration**: LangGraph
- **LLM**: Gemini Flash
- **Telephony**: Twilio ConversationRelay (voice), Twilio Programmable SMS
- **Data access**: PostgreSQL, Neo4j, Redis, pgvector

## Structure

```
apis/
├── api_intake/          # Core IntakeAI backend API (one folder per API)
│   ├── app/             # FastAPI application
│   │   ├── main.py      # App entrypoint, routers, health checks
│   │   ├── config.py    # Environment-driven settings
│   │   ├── agents/      # Data-backed agents (eligibility_agent.py)
│   │   ├── routes/      # HTTP + WebSocket endpoints
│   │   └── safety/      # Non-negotiable safety layer (must-have.md Part 1)
│   ├── tests/           # API and safety tests
│   ├── pytest.ini
│   └── requirements.txt
├── CLAUDE.md
└── README.md
```

## Endpoints (api_intake)

| Endpoint | Type | Purpose |
|---|---|---|
| `GET /health` | HTTP | Liveness + dependency (postgres/neo4j/redis) TCP status |
| `POST /eligibility-check` | HTTP | Deterministic ACCEPT / DECLINE / NEEDS_MORE_INFO over `data/` datasets, with reasons, matched plan, required docs, matched caregivers |
| `POST /twilio/voice` | HTTP (Twilio webhook) | Returns TwiML `<Connect><ConversationRelay>` pointing at the WebSocket below (needs `PUBLIC_BASE_URL`) |
| `WS /twilio/conversation-relay` | WebSocket | Safety-gated conversation loop: consent first → field extraction → deterministic eligibility → banned-phrase filter → handoff on failure |

Voice Agent mode prompts live in [`../ai-agents/voice-agent/`](../ai-agents/voice-agent).

## Requirements

- Node.js 20+ for any tooling; Python for the service runtime.
- Environment variables come from `.env` (never committed). Use `.env.example` as reference.

## Related

- Infrastructure and local orchestration: [`../infra`](../infra)
- Agent design and prompts: [`../ai-agents`](../ai-agents)
