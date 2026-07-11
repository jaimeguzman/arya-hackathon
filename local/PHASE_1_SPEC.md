# PHASE 1: Data & Storage

## Objective

Stand up all three databases (PostgreSQL, Neo4j, Redis) with schemas and seed data loaded from external JSON files. After this phase, any engineer can import a db client and query real data. Nothing else in the project works without this.

## Owner

**Engineer 3** (primary) — all 4 engineers help during Hour 1, but Engineer 3 owns the databases end-to-end.

## Core Principle: No Hardcoded Data

All seed data — diagnoses, medications, caregivers, insurance rules, service areas, referral sources, diagnosis-to-service mappings, certification mappings — lives in JSON files under the `data/` directory. The database scripts define structure only (tables, node labels, indexes, constraints). A Python loader script reads the JSON files and populates both PostgreSQL and Neo4j.

Why this matters:
- Adding a diagnosis, caregiver, or insurance plan during the hackathon is a JSON edit + re-run loader, not a schema change
- The JSON files double as documentation — anyone can open `insurance_rules.json` and see exactly what plans the system knows about
- Same JSON files feed tests, dashboard mocks, and demo prep
- Clear separation: schema is code, data is config

## Ponytail Rules for This Phase

- **Docker Compose**: use official images directly, no custom Dockerfiles for databases
- **PostgreSQL init**: one raw SQL file mounted via docker-entrypoint — schema only, zero INSERT statements
- **Neo4j structure**: constraints and indexes only via Cypher — zero CREATE node statements in the Cypher file
- **Connection utilities**: one file exporting three clients — no wrapper classes, no retry decorators, no health check abstractions
- **Loader script**: one Python file that reads all JSON files and populates both databases — no factory patterns, no Faker, no fixture frameworks
- Mark every shortcut with `# ponytail:` naming the ceiling and upgrade path

---

## Deliverable 1: Docker Compose

**File:** `docker-compose.yml`

Three services: PostgreSQL, Neo4j, Redis. All databases only — backend and frontend run on host for fast iteration during the hackathon.

**PostgreSQL service:**
- Image: `pgvector/pgvector:pg16` (gives us pgvector extension for free if we need fuzzy matching later)
- Port 5432 exposed
- Database name: `intakeai`, user: `intakeai`, password: `intakeai_dev`
- Mount the SQL init file to `/docker-entrypoint-initdb.d/init.sql` so it runs automatically on first container start
- Named volume for data persistence across restarts
- Healthcheck using `pg_isready`

**Neo4j service:**
- Image: `neo4j:5`
- Ports 7474 (browser UI) and 7687 (bolt protocol) exposed
- Auth: `neo4j/intakeai_dev`
- APOC plugin enabled (useful for batch operations during seeding)
- Named volume for data persistence
- Healthcheck using `neo4j status`

**Redis service:**
- Image: `redis:7-alpine` (smallest image)
- Port 6379 exposed
- No persistence volume needed — Redis data is ephemeral by design in this system (pipeline state, cache, call state)
- Healthcheck using `redis-cli ping`

No other services. Backend and frontend run directly on the host machine for maximum iteration speed.

**Git commit:** `phase-1: docker-compose with postgres, neo4j, redis`

**Verify:** `docker compose up -d` → `docker compose ps` shows all three services healthy.

---

## Deliverable 2: PostgreSQL Schema

**File:** `backend/db/postgres_init.sql`

This file defines tables, types, indexes, and triggers ONLY. Zero data. It runs once when the PostgreSQL container first starts.

### Tables to Create

**`intake_records`** — the central table, one row per referral.

Fields:
- `id` — UUID primary key, auto-generated
- `status` — enum: new, processing, pending_documents, eligible, accepted, declined, escalated
- `source` — enum: fax, inbound_call_provider, inbound_call_family, inbound_call_patient, physician_referral, snf_referral
- `urgency` — string: routine, urgent, stat
- `patient_data` — JSONB containing name, dob, gender, address, phone, language, emergency_contact. Using JSONB instead of 15 nullable columns because different referral sources produce different fields. A fax extraction might have 40+ fields while a family call captures 8. JSONB handles this naturally.
- `clinical_data` — JSONB containing diagnosis, icd_codes, medications, allergies, homebound_status, procedures
- `physician_data` — JSONB containing name, npi, phone, fax, specialty, orders, f2f_date
- `insurance_data` — JSONB containing payer, plan_type, member_id, group_number, effective_date, auth_required
- `care_request` — JSONB containing service_types, frequency, duration, special_instructions
- `referral_source` — JSONB containing facility_name, facility_type, contact_name, phone, fax, email
- `extraction_confidence` — JSONB mapping field names to confidence scores (0.0 to 1.0)
- `gaps` — JSONB array of objects, each with field name, priority, status, and follow-up action
- `eligibility_decision` — string: accept, decline, needs_more_info, pending
- `eligibility_reasons` — JSONB array of reason objects
- `matched_caregivers` — JSONB array of caregiver match objects with scores
- `escalated` — boolean flag
- `escalation_reason` — text
- `human_review_required` — boolean flag
- `created_at` and `updated_at` — timestamps with timezone, auto-managed

Design decision: one JSONB column per domain (patient, clinical, physician, insurance, care request, referral source) rather than 40+ flat columns. This is a `ponytail:` choice — flexible schema, no ALTER TABLE during hackathon, query with JSONB operators. Ceiling: JSONB fields can't have database-level constraints. Upgrade path: promote critical fields to real columns if validation at the DB layer matters.

**`caregivers`** — the roster of available caregivers.

Fields:
- `id` — UUID primary key
- `name` — string, required
- `type` — enum: RN, LPN, CNA, PT, OT, ST, HHA
- `status` — enum: active, on_leave, suspended, inactive
- `languages` — PostgreSQL text array (e.g., `{'English', 'Spanish'}`). Using a native array instead of a join table — `ponytail:` fewer tables, array contains operator handles the query. Ceiling: can't index individual array elements efficiently. Upgrade: separate `caregiver_languages` table if language queries become complex.
- `current_patient_load` — integer, starts at 0
- `max_patient_capacity` — integer, default 8
- `phone` and `email` — contact info
- `created_at` and `updated_at`

**`caregiver_certifications`** — which certifications each caregiver holds.

This is a proper join table (not JSONB) because the Eligibility Agent queries this table heavily: "find all caregivers who have wound care certification AND it's not expired." That query needs indexed columns, not JSONB scanning.

Fields:
- `id` — UUID primary key
- `caregiver_id` — foreign key to caregivers, cascade delete
- `certification_name` — string matching the CertificationType names in Neo4j (e.g., "RN", "wound_care", "orthopedic")
- `issued_date` — date
- `expiry_date` — date, nullable (some certifications don't expire)
- `is_active` — boolean, computed/generated column: true if expiry_date is null OR expiry_date is in the future. This is a PostgreSQL GENERATED ALWAYS AS STORED column — the database keeps it updated automatically. No application code needed to check expiry.

Index: composite index on (caregiver_id, certification_name) filtered to active-only records. This is the exact index shape the caregiver matching query needs.

**`caregiver_service_areas`** — which zip codes each caregiver covers.

Fields:
- `id` — UUID primary key
- `caregiver_id` — foreign key to caregivers, cascade delete
- `zip_code` — string

Indexes on both zip_code (for "find caregivers in this zip") and caregiver_id (for "what zips does this caregiver cover").

**`caregiver_availability`** — weekly schedule template.

Fields:
- `id` — UUID primary key
- `caregiver_id` — foreign key
- `day_of_week` — integer 0-6 (0=Monday) with check constraint
- `start_time` and `end_time` — TIME type

Index on (caregiver_id, day_of_week) for the scheduling query.

**`service_areas`** — zip codes the agency serves (agency-level configuration, not per-caregiver).

Fields:
- `zip_code` — string, primary key
- `borough` — string (Manhattan, Brooklyn, Queens, Bronx, Staten Island — useful for display)
- `active` — boolean

This is the first check in eligibility: "do we serve this zip code?" It's a simple primary key lookup.

**`insurance_contracts`** — which payer/plan combinations the agency accepts.

Fields:
- `id` — UUID primary key
- `payer_name` — string (e.g., "Medicare", "Humana", "Aetna")
- `plan_name` — string (e.g., "Medicare Part A", "Humana Gold Plus HMO")
- `plan_type` — string (part_a, part_b, medicare_advantage, medicaid, ppo, hmo)
- `accepted` — boolean
- `notes` — text for any special conditions

Partial index on (payer_name, plan_name) filtered to accepted=true only — we only ever query accepted contracts.

**`referral_sources`** — hospitals, SNFs, and physician offices that refer patients.

Fields:
- `id` — UUID primary key
- `facility_name` — string
- `facility_type` — string: hospital, snf, physician_office
- `contact_name`, `phone`, `fax`, `email` — contact details
- `ehr_system` — string (which EHR they use, informational)
- `total_referrals` and `accepted_referrals` — integer counters
- `acceptance_rate` — computed/generated column: accepted_referrals / total_referrals. Using a GENERATED ALWAYS AS column so the rate updates automatically when the counters change.
- `created_at` and `updated_at`

**`documents`** — uploaded/faxed PDFs and their processing state.

Fields:
- `id` — UUID primary key
- `intake_record_id` — foreign key to intake_records (nullable — document might be uploaded before an intake record is created)
- `file_path` — where the file is stored on disk
- `file_name` — original filename
- `page_count` — integer
- `processing_status` — enum: uploaded, preprocessing, classifying, extracting, validating, complete, failed
- `failed_at_layer` — integer 1-7, which pipeline layer failed (null if no failure)
- `extraction_result` — JSONB containing the final merged extraction from all pages
- `created_at` and `updated_at`

**`document_pages`** — per-page extraction results within a document.

Fields:
- `id` — UUID primary key
- `document_id` — foreign key to documents, cascade delete
- `page_number` — integer
- `classification` — string: discharge_summary, physician_order, insurance_card, medication_list, f2f_note, lab_results, consent_form, cover_sheet
- `extraction_path` — string: "rules" or "vision" (which Layer 3 path was used)
- `raw_extraction` — JSONB from initial extraction
- `validated_extraction` — JSONB after the agentic review loop
- `confidence_scores` — JSONB mapping field names to scores
- `validation_errors` — JSONB array of error objects
- `created_at`

**`call_records`** — every voice interaction (inbound and outbound).

Fields:
- `id` — UUID primary key
- `intake_record_id` — foreign key to intake_records (nullable)
- `twilio_call_sid` — string, unique (Twilio's call identifier)
- `direction` — enum: inbound, outbound
- `mode` — enum: provider, family, patient, outbound_followup
- `caller_number` — string
- `status` — enum: active, completed, failed, voicemail, no_answer
- `transcript` — text, populated after call ends
- `extracted_data` — JSONB, structured data extracted during the call
- `duration_seconds` — integer
- `started_at` and `ended_at` — timestamps

**`follow_up_actions`** — event log tracking every follow-up action per referral.

Fields:
- `id` — UUID primary key
- `intake_record_id` — foreign key, required
- `type` — enum: sms_sent, email_sent, outbound_call_attempted, voicemail_left, callback_scheduled, document_received, document_requested, eligibility_recheck
- `status` — enum: pending, completed, failed, cancelled
- `target_phone` and `target_email` — who the action targets
- `message` — text content
- `scheduled_at` — when to execute (for scheduled retries)
- `executed_at` — when it actually ran
- `result` — JSONB with outcome details
- `attempt_number` — integer for retry tracking
- `created_at`

Index on scheduled_at filtered to pending status — this is what the follow-up scheduler worker polls.

**Shared infrastructure across all tables:**
- Every table gets UUID primary keys generated by the database (gen_random_uuid from pgcrypto)
- Every table with an `updated_at` field gets a trigger that auto-updates it on any row change
- Define the trigger function once, apply it to each table. One function, multiple triggers.

**Git commit:** `phase-1: postgresql schema migration (all tables)`

---

## Deliverable 3: Neo4j Graph Structure

**File:** `backend/db/neo4j_seed.cypher`

This file defines constraints and indexes ONLY. Zero node creation. The loader script creates all nodes and relationships by reading from JSON files.

### Constraints and Indexes to Create

**Uniqueness constraints** (these also create indexes automatically):
- Diagnosis nodes: unique on `icdCode`
- ServiceType nodes: unique on `name`
- CertificationType nodes: unique on `name`
- Payer nodes: unique on `name`
- InsurancePlan nodes: unique on `code`
- Medication nodes: unique on `genericName`

**Additional indexes** for query performance:
- Diagnosis: index on `name` (for text-based lookups when the caller says "hip replacement" not "Z96.641")
- Diagnosis: index on `category` (for filtering by disease category)
- InsurancePlan: index on `name` (for fuzzy matching when fax says "Humana Gold" not the exact plan code)
- Medication: index on `name` (for brand name lookups)

### Node Types the Loader Will Create

The loader reads from JSON files and creates these node types:

**Diagnosis** — from `data/icd10_home_health_top30.json`
- Properties: icdCode, name, category
- ~30 nodes covering the most common home health diagnoses

**ServiceType** — from `data/diagnosis_service_map.json`
- Properties: name, displayName, description
- 6 nodes: skilled_nursing, physical_therapy, occupational_therapy, speech_therapy, home_health_aide, medical_social_work

**CertificationType** — from `data/diagnosis_service_map.json`
- Properties: name, displayName
- ~15 nodes: RN, LPN, CNA, PT, OT, ST, HHA, plus specialty certs (wound_care, iv_therapy, cardiac, orthopedic, diabetes_education, pediatric, hospice_palliative, oncology)

**Payer** — from `data/insurance_rules.json`
- Properties: name, type (federal/state/commercial)
- 5 nodes: Medicare, Medicaid_NY, Humana, Aetna, UnitedHealthcare

**InsurancePlan** — from `data/insurance_rules.json`
- Properties: name, planType, code
- ~9 nodes covering Medicare Part A/B, Medicare Advantage plans, Medicaid, commercial PPO/HMO

**Medication** — from `data/medications_reference.json`
- Properties: name, genericName, category, minDose, maxDose, unit, commonDoses
- ~20 nodes covering the most common medications in home health patients

### Relationship Types the Loader Will Create

**Diagnosis → REQUIRES → ServiceType**
- From `data/diagnosis_service_map.json`
- Properties on relationship: priority (primary/secondary), specialization (e.g., "wound_care" if the diagnosis specifically needs that specialty)
- ~40+ relationships mapping each diagnosis to the service types it requires

**ServiceType → NEEDS_CERTIFICATION → CertificationType**
- From `data/diagnosis_service_map.json`
- Properties: either (boolean — if true, any of the linked certs qualifies, e.g., skilled nursing needs RN OR LPN)
- ~10 relationships

**InsurancePlan → UNDER_PAYER → Payer**
- From `data/insurance_rules.json`
- 9 relationships linking each plan to its payer

**InsurancePlan → COVERS → ServiceType**
- From `data/insurance_rules.json`
- Properties on relationship: priorAuthRequired (boolean), requiredDocs (list of strings), visitLimit (integer), episodeDays (integer), notes (string)
- ~30+ relationships defining what each plan covers and under what conditions

**Medication → CONTRAINDICATED_WITH → Medication**
- From `data/medications_reference.json`
- Properties: severity (major/moderate/minor), reason (text explaining the interaction)
- ~10-15 critical drug interaction relationships (bidirectional — create both directions or query without direction)

**Git commit:** `phase-1: neo4j constraints and indexes`

---

## Deliverable 4: JSON Data Files

All files live in the `data/` directory. These are the single source of truth for all seed data.

### `data/icd10_home_health_top30.json`

Array of diagnosis objects. Each object has:
- `icdCode` — the ICD-10-CM code (e.g., "Z96.641")
- `name` — human-readable description (e.g., "Presence of right artificial hip joint")
- `category` — disease grouping (musculoskeletal, cardiovascular, cerebrovascular, endocrine, respiratory, skin, neurological, renal, post_surgical, palliative, oncology)

Include the top 30 most common home health diagnoses. Source this from real CMS data. Focus on: joint replacements, hip fractures, stroke, heart failure, diabetes, COPD, pressure ulcers, chronic wounds, Alzheimer's, Parkinson's, ESRD, post-surgical rehab, palliative care, lung cancer, hypertension.

### `data/diagnosis_service_map.json`

This is the core knowledge mapping file. Structure it as:

Top level has three sections:
- `service_types` — array of service type definitions (name, displayName, description)
- `certification_types` — array of certification definitions (name, displayName)
- `mappings` — array of objects, each mapping a diagnosis (by icdCode or by category) to required service types, and each service type to required certifications

The mappings section is where the domain knowledge lives. Example structure per mapping:
- `diagnosis_codes` — list of ICD-10 codes this mapping applies to
- `required_services` — list of objects, each with service type name, priority, and optional specialization
- `service_certification_map` — for each service type, which certifications qualify (with an "either" flag for OR logic)

This single file drives the entire REQUIRES and NEEDS_CERTIFICATION relationship graph in Neo4j. To add a new diagnosis and its care requirements, edit this one file.

### `data/insurance_rules.json`

Structure:
- `payers` — array of payer objects (name, type)
- `plans` — array of plan objects, each with: name, planType, code, payerName, and a `coverage` array
- Each coverage entry specifies: serviceType, priorAuthRequired, requiredDocs, visitLimit, episodeDays, notes

This single file drives the entire Payer → InsurancePlan → COVERS → ServiceType graph in Neo4j, AND the insurance_contracts table in PostgreSQL (the loader populates both from this one source).

### `data/medications_reference.json`

Array of medication objects:
- `name` — brand name
- `genericName` — generic name (used as the Neo4j node key)
- `category` — drug class
- `minDose`, `maxDose` — valid dosage range (what the Validation Agent checks against)
- `unit` — mg, mcg, units, etc.
- `commonDoses` — array of typical prescribed doses
- `contraindications` — array of objects, each with `genericName` of the interacting drug, `severity`, and `reason`

The contraindications array within each medication drives the CONTRAINDICATED_WITH relationships in Neo4j. The loader reads them and creates the graph edges.

### `data/caregiver_roster.json`

Array of 25 caregiver objects. Each has:
- `name` — realistic name
- `type` — RN, LPN, CNA, PT, OT, ST, or HHA
- `status` — active, on_leave, or suspended
- `languages` — array of languages spoken
- `currentPatientLoad` and `maxPatientCapacity`
- `phone` and `email`
- `certifications` — array of objects, each with certificationName, issuedDate, expiryDate (some expired intentionally for testing)
- `serviceAreas` — array of zip code strings
- `availability` — array of objects, each with dayOfWeek, startTime, endTime

Important data variety to include:
- Mix of types: 8 RN, 5 LPN, 3 CNA, 4 PT, 2 OT, 1 ST, 2 HHA
- Cover NYC zips: Brooklyn (112xx), Manhattan (100xx), Queens (111xx), Bronx (104xx)
- 3-4 caregivers who speak Spanish
- 2 caregivers at max patient load (tests capacity filtering)
- 1 caregiver on leave (tests status filtering)
- 2-3 caregivers with expired certifications (tests the is_active computed column and compliance scenarios)
- At least 2 caregivers with orthopedic certification in Brooklyn zip codes (for the primary demo scenario: hip replacement patient in 11201)

### `data/service_areas.json`

Array of objects with zip_code, borough, and active flag.

Include ~30 NYC zip codes:
- Manhattan: 10001-10010
- Brooklyn: 11201-11210
- Queens: 11101-11105
- Bronx: 10451-10455

Intentionally do NOT include zip 90210 (Beverly Hills) — this is the test case for the decline scenario where the patient is outside the service area.

### `data/referral_sources.json`

Array of 5 referral source objects:
- Mount Sinai Hospital (hospital type, contact: Sarah Chen) — this is referenced in the demo script
- NYU Langone Health (hospital type, contact: Dr. James Park) — referenced in the family call demo
- Brooklyn Methodist Hospital (hospital type)
- Sunrise Senior Living (SNF type)
- Dr. Patricia Williams Primary Care (physician_office type)

Each has facility_name, facility_type, contact_name, phone, fax, email, ehr_system. The totalReferrals and acceptedReferrals start at realistic numbers (not zero) so the acceptance_rate computed column shows meaningful data on the dashboard.

**Git commit:** `phase-1: json data files created (all seed data)`

---

## Deliverable 5: Data Loader Script

**File:** `backend/db/sample_data.py`

One Python script that reads ALL JSON files from `data/` and populates BOTH PostgreSQL and Neo4j. Run it once after the databases are up.

### What the loader does:

**Step 1: Connect to both databases.**
Use asyncpg for PostgreSQL, the neo4j Python driver for Neo4j. Read connection details from config/environment.

**Step 2: Load PostgreSQL tables from JSON.**

Read `caregiver_roster.json` → for each caregiver, insert into the `caregivers` table, then insert their certifications into `caregiver_certifications`, their zip codes into `caregiver_service_areas`, and their schedule into `caregiver_availability`. Use batch inserts where possible (executemany or COPY) for speed.

Read `service_areas.json` → bulk insert into `service_areas` table.

Read `insurance_rules.json` → extract the plans section, insert each plan into `insurance_contracts` table. The JSON has all the info needed: payer_name, plan_name, plan_type, and whether the agency accepts it.

Read `referral_sources.json` → insert into `referral_sources` table.

**Step 3: Load Neo4j graph from JSON.**

Read `icd10_home_health_top30.json` → create Diagnosis nodes using MERGE (idempotent — safe to re-run).

Read `diagnosis_service_map.json` → create ServiceType nodes, CertificationType nodes, then create the REQUIRES relationships (Diagnosis → ServiceType) and NEEDS_CERTIFICATION relationships (ServiceType → CertificationType). Use MERGE for all node creation, CREATE for relationships (after clearing old relationships to allow re-runs).

Read `insurance_rules.json` → create Payer nodes, InsurancePlan nodes, UNDER_PAYER relationships, and COVERS relationships with all the coverage rule properties.

Read `medications_reference.json` → create Medication nodes, then read the contraindications arrays and create CONTRAINDICATED_WITH relationships.

**Step 4: Print summary.**
Count and print: how many rows in each PostgreSQL table, how many nodes and relationships of each type in Neo4j. This is the verification output.

### Loader design principles:
- Idempotent — safe to run multiple times. Use MERGE in Neo4j, use ON CONFLICT DO NOTHING or truncate-and-reload in PostgreSQL.
- One function per data file — `load_caregivers()`, `load_service_areas()`, `load_insurance()`, `load_referral_sources()`, `load_neo4j_diagnoses()`, `load_neo4j_insurance()`, `load_neo4j_medications()`
- A `main()` that calls them all in sequence with error handling per step (if medications fail to load, caregivers are still in the DB)
- Runnable as `python -m backend.db.sample_data` from the project root

**Git commit:** `phase-1: data loader script populating postgres and neo4j from json files`

---

## Deliverable 6: Database Connection Utilities

**File:** `backend/models/database.py`

One file exporting three database clients. No wrapper classes, no connection pool abstractions, no retry logic.

Three module-level clients:
- **PostgreSQL**: an asyncpg connection pool. Initialize with min 2, max 10 connections. The DSN is built from settings. Export an `init_postgres()`, a `get_pg()` that returns the pool, and a `close_postgres()`.
- **Neo4j**: an async driver from the official neo4j Python package. Initialize with URI + auth from settings. Export `init_neo4j()`, `get_neo4j()`, `close_neo4j()`.
- **Redis**: an async Redis client from redis.asyncio. Initialize from the REDIS_URL setting. Export `init_redis()`, `get_redis()`, `close_redis()`.

Plus convenience functions:
- `init_all_dbs()` — calls all three init functions. Called once on FastAPI startup.
- `close_all_dbs()` — calls all three close functions. Called on FastAPI shutdown.

`ponytail:` no retry logic — databases are local Docker containers on the same machine. No connection will flake. Ceiling: if any DB container is slow to start, the app crashes on startup. Upgrade path: add a simple retry loop with backoff in init_all_dbs if needed.

**File:** `backend/config.py`

One Pydantic BaseSettings class that reads from `.env` file automatically. Contains all environment variables defined in the .cursorrules (Twilio, ngrok, Gemini, PostgreSQL, Neo4j, Redis, app settings). No nested settings classes, no per-environment overrides — `ponytail:` one flat class is enough.

**Git commit:** `phase-1: database connection utilities and config`

---

## Deliverable 7: Verification

**File:** `scripts/seed_databases.sh`

A shell script that:
1. Waits a few seconds for containers to be ready
2. Runs the Python loader script
3. Queries PostgreSQL and prints row counts for each table
4. Queries Neo4j and prints node/relationship counts by type
5. Pings Redis to confirm it's alive
6. Prints a summary pass/fail

This is the "did Phase 1 work?" script. Run it after `docker compose up -d`.

**Git commit:** `phase-1: verify all databases connected and seeded`

---

## Verification Checklist

After Phase 1, these must all pass:

| Check | Expected |
|-------|----------|
| Docker services running | 3 services, all healthy |
| PostgreSQL schema exists | 11 tables visible |
| Caregivers loaded | 25 rows |
| Caregiver certifications loaded | ~75-100 rows (3-4 per caregiver) |
| Caregiver service areas loaded | ~200+ rows (8-10 zips per caregiver) |
| Service areas loaded | ~30 rows |
| Insurance contracts loaded | ~9 rows |
| Referral sources loaded | 5 rows |
| Neo4j Diagnosis nodes | 30 |
| Neo4j ServiceType nodes | 6 |
| Neo4j CertificationType nodes | ~15 |
| Neo4j Payer nodes | 5 |
| Neo4j InsurancePlan nodes | ~9 |
| Neo4j Medication nodes | ~20 |
| Neo4j REQUIRES relationships | ~40+ |
| Neo4j NEEDS_CERTIFICATION relationships | ~10 |
| Neo4j COVERS relationships | ~30+ |
| Neo4j CONTRAINDICATED_WITH relationships | ~10-15 |
| Redis alive | PING → PONG |
| Python connects to all 3 | init_all_dbs() succeeds |

**Critical integration test — the query that proves the graph works:**

Run a Neo4j traversal: "Given diagnosis Z96.641 (hip replacement) with insurance plan MCARE_A (Medicare Part A), what service types are required, what certifications are needed for each, and what are the coverage rules?"

The query traverses: Diagnosis → REQUIRES → ServiceType → NEEDS_CERTIFICATION → CertificationType, and separately InsurancePlan → COVERS → ServiceType.

Expected result:
- Hip replacement requires skilled_nursing (needs RN or LPN) + physical_therapy (needs PT)
- Medicare Part A covers both, no prior auth required
- Required documents: physician_orders, face_to_face_encounter, homebound_certification

If that traversal returns the correct data from the JSON-loaded graph, Phase 1 is complete. The Eligibility Agent (built in Phase 3) will use exactly this query pattern.

---

## What NOT to Build in Phase 1

- No API endpoints (Phase 3)
- No FastAPI app (Phase 3 — though Engineer 1 scaffolds the skeleton in parallel during Hour 1)
- No Pydantic request/response models (Phase 3)
- No business logic of any kind (Phases 2-5)
- No frontend (Phase 6)
- No Alembic or migration framework — the SQL file IS the migration
- No SQLAlchemy ORM models — we use raw asyncpg queries. `ponytail:` ORM adds a layer between us and the SQL with no benefit for a hackathon. Ceiling: no automatic relationship loading. Upgrade: add SQLAlchemy models if the project goes beyond hackathon.
- No connection retry/backoff logic
- No database health check API endpoints — Docker healthchecks are sufficient
- No pgvector setup yet — `ponytail:` add it when/if fuzzy matching is actually needed

---

## Ponytail Integration

Add the ponytail.mdc file to `.cursor/rules/ponytail.mdc` before anyone starts writing code. This ensures every Cursor agent session across all 4 engineers enforces the YAGNI ladder:

1. Does this need to be built at all?
2. Does the standard library already do this? Use it.
3. Does a native platform feature cover it? Use it.
4. Does an already-installed dependency solve it? Use it.
5. Can this be one line? Make it one line.
6. Only then: write the minimum code that works.

The file content is available at `https://github.com/DietrichGebert/ponytail/blob/main/.cursor/rules/ponytail.mdc` — copy it verbatim. It's 30 lines. Set `alwaysApply: true` so it's active on every file in the project.
