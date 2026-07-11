# infra

Infrastructure, local orchestration, and data provisioning for IntakeAI.

## Scope

- Docker Compose for local development (PostgreSQL, Neo4j, Redis, FastAPI, React dev server).
- Database provisioning: PostgreSQL migrations and Neo4j Cypher seed scripts.
- Twilio account configuration and ConversationRelay setup notes.
- Redis setup for pipeline state and caching.
- Environment reference (`.env.example`) and service wiring.

See [`../PROJECT.md`](../PROJECT.md) for the database architecture and the reasoning behind the 4-database design.

## Databases

| Store | Purpose |
|---|---|
| PostgreSQL | Operational/relational data, intake records, caregiver roster, audit trails |
| Neo4j | Knowledge graph — eligibility path traversal (diagnosis → service → certification → caregiver) |
| Redis | Pipeline state, active-call state, eligibility caching, retry scheduling |
| pgvector | Fuzzy matching (insurance/medication/physician names) — PostgreSQL extension |

## Structure (proposed)

```
infra/
├── docker-compose.yml   # PostgreSQL, Neo4j, Redis, FastAPI, React
├── postgres/            # Migrations + reference/lookup seed data
├── neo4j/               # Cypher seed scripts (ICD-10 subset, mappings, rules)
├── twilio/              # ConversationRelay + number configuration notes
└── README.md
```

## Requirements

- Node.js 20+ for tooling.
- Environment variables live in `.env` (never committed). `.env.example` is the reference — keep it current.

## Related

- Application services: [`../apis`](../apis)
- Agent design: [`../ai-agents`](../ai-agents)
