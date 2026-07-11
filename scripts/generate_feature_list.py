#!/usr/bin/env python3
"""One-time generator for feature_list.json derived from app_spec.txt."""
import json

F = []


def add(category, app, description, ref, steps):
    F.append({
        "id": len(F) + 1,
        "category": category,
        "app": app,
        "description": description,
        "spec_reference": ref,
        "steps": steps,
        "passes": False,
    })


OK = "Expected result: the command/check completes successfully with no blocking errors."
API_OK = "Expected result: the endpoint returns the documented status code and JSON shape."
UI_OK = "Expected result: the UI renders the described element without console errors."

# ---------------- setup ----------------
add("setup", "infra", "Docker Compose stack: PostgreSQL+pgvector, Neo4j, Redis, FastAPI, React dev server", "technology_stack/infrastructure", [
    f"Verify infra/docker-compose.yml defines services postgres (with pgvector image), neo4j, redis, api, and web. {OK}",
    f"Run docker compose config to validate the file. {OK}",
    f"Run docker compose up -d for postgres, neo4j, redis and confirm all three report healthy. {OK}",
    f"Verify no credentials are hardcoded; all secrets come from environment variables referenced in .env.example. {OK}",
])
add("setup", "apis", "FastAPI backend skeleton with app factory, settings from env, and /health endpoint", "api_endpoints_summary/core", [
    f"Verify apis/ contains a FastAPI app package with pyproject.toml or requirements.txt pinning fastapi, uvicorn, langgraph, redis, psycopg, neo4j. {OK}",
    f"Verify settings are loaded from environment variables (pydantic-settings) with no hardcoded URLs or keys. {OK}",
    f"Start the app and GET /health returns 200 with per-dependency status (postgres, neo4j, redis). {API_OK}",
])
add("setup", "apps", "React intake dashboard scaffold (Vite + TypeScript) with dev/build/lint/type-check scripts", "ui_layout/dashboard", [
    f"Verify apps/dashboard/package.json declares scripts dev, build, lint, type-check and engines.node >= 20. {OK}",
    f"Run npm run build in apps/dashboard with zero type errors. {OK}",
    f"Run npm run dev and confirm HTTP 200 on the base route. {OK}",
])
add("setup", "infra", "PostgreSQL migration SQL creating all operational tables from the schema", "database_schema/postgresql", [
    f"Verify migration files create intake_records, extracted_fields, gap_list, caregivers, service_areas, insurance_contracts, referral_sources, call_records, follow_up_events, audit_trail, icd10_codes, zip_codes, medication_dosage_ranges. {OK}",
    f"Verify intake_records has JSONB columns for patient, clinical, insurance and an is_synthetic boolean NOT NULL. {OK}",
    f"Apply migrations against a fresh database and confirm all tables exist. {OK}",
])
add("setup", "infra", "Neo4j Cypher seed scripts for the 13-node/14-relationship knowledge graph", "database_schema/neo4j", [
    f"Verify Cypher seeds create the 13 node types (Patient, Diagnosis, Payer, InsurancePlan, CoverageRule, ServiceType, CertificationType, Caregiver, ServiceArea, Physician, ReferralSource, Medication, Document). {OK}",
    f"Verify the 14 relationship types are created including REQUIRES, NEEDS_CERTIFICATION, HAS_CERTIFICATION, SERVES_AREA, COVERS. {OK}",
    f"Run the seed script against Neo4j and query counts per label to confirm data loaded from data/reference JSON files. {OK}",
])
add("setup", "infra", "Redis key conventions and connection module for pipeline/call/eligibility/retry state", "database_schema/redis", [
    f"Verify a shared Redis module defines key builders pipeline:{{doc_id}}, call:{{call_sid}}, eligibility_cache:{{zip}}:{{payer}}:{{plan}}, retry_queue. {OK}",
    f"Verify eligibility cache entries are written with a short TTL. {OK}",
    f"Unit test round-trips a value through each key type. {OK}",
])
add("setup", "infra", ".env.example documenting every required environment variable", "technology_stack", [
    f"Verify .env.example lists DATABASE_URL, NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, REDIS_URL, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, GEMINI_API_KEY, PUBLIC_BASE_URL (ngrok). {OK}",
    f"Verify no real secret values appear in .env.example and no .env file is committed. {OK}",
])
add("setup", "data", "Reference data present and loadable: ICD-10 subset, diagnosis-service-cert mapping, payer rules", "data_model/knowledge_reference", [
    f"Verify data/reference contains icd10_top30_home_health.json, diagnosis_service_certification_mapping.json, payer_coverage_rules.json (5 payers, 8 plans). {OK}",
    f"Verify a loader parses each file into typed structures without error. {OK}",
    f"Verify every diagnosis in the mapping references an ICD-10 code present in the subset. {OK}",
])
add("setup", "data", "Synthetic seed data: caregiver roster (20-30), referral sources, sample referral PDFs", "implementation_steps/prework", [
    f"Verify data/synthetic contains a caregiver roster JSON with 20-30 caregivers including type, certifications with expiry, zips, availability, languages, load, capacity, status. {OK}",
    f"Verify 3-4 sample referral PDFs of varying quality exist for pipeline testing. {OK}",
    f"Verify every synthetic record is tagged is_synthetic: true when loaded into PostgreSQL. {OK}",
])
add("setup", "apis", "Backend test harness with pytest and CI-runnable safety suite entry point", "safety_requirements", [
    f"Verify pytest is configured and a tests/ package exists in apis/. {OK}",
    f"Verify tests/test_safety_layer.py exists and is wired so the suite fails the build if any safety test fails. {OK}",
    f"Run pytest and confirm the suite executes. {OK}",
])

# ---------------- safety (functional) ----------------
add("functional", "apis", "Safety guarantee 1: fake data only — is_synthetic enforced on every DB write", "safety_requirements/guarantee 1", [
    f"Verify the DB write layer hard-asserts is_synthetic is true and raises on any record missing or false. {OK}",
    f"Verify the app refuses to boot unless DATABASE_URL matches an allowlisted demo database name. {OK}",
    f"Test in test_safety_layer.py: writing a non-synthetic record raises; booting against a non-allowlisted DB name aborts. {OK}",
])
add("functional", "apis", "Safety guarantee 2: tokenize -> LLM -> rehydrate wrapper; single LLM entry point", "safety_requirements/guarantee 2", [
    f"Verify exactly one function in the codebase calls the Gemini API and all agents route through it. {OK}",
    f"Verify identifiers (name, DOB, phone, address, member ID) are replaced with placeholders like {{{{PATIENT_NAME}}}} before the payload is built. {OK}",
    f"Verify the wrapper regex-scans its outgoing payload for identifier patterns (phone formats, DOB dates, member ID formats) and refuses to send on match. {OK}",
    f"Verify rehydration replaces placeholders only inside the backend after the LLM responds. {OK}",
    f"Verify a grep/static check confirms no other module imports the LLM SDK directly. {OK}",
    f"Verify token maps are stored per-request in backend memory or Redis, never sent to the LLM. {OK}",
    f"Verify DOB, address, and member ID patterns are each covered by the outgoing regex scan. {OK}",
    f"Verify the wrapper logs a redacted audit event when it blocks a payload. {OK}",
    f"Verify vision-path document images are handled per the same policy (identifier fields tokenized in accompanying text prompts). {OK}",
    f"Test in test_safety_layer.py: payload containing a raw phone number is rejected; tokenized round-trip restores original values. {OK}",
])
add("functional", "apis", "Safety guarantee 3: check_eligibility() is deterministic code, never LLM-decided", "safety_requirements/guarantee 3", [
    f"Verify check_eligibility() contains no LLM calls and evaluates zip match, insurance acceptance, and caregiver availability from tables/graph only. {OK}",
    f"Verify the response-generation function requires a pre-computed EligibilityResult object as a mandatory input parameter. {OK}",
    f"Test in test_safety_layer.py: clear-yes case returns ACCEPT, clear-no returns DECLINE, ambiguous returns NEEDS_MORE_INFO. {OK}",
])
add("functional", "apis", "Safety guarantee 4: consent gather is the first node of every call flow", "safety_requirements/guarantee 4", [
    f"Verify the consent node is the only node wired to the incoming-call trigger in the call flow graph. {OK}",
    f"Verify every data-collection function reads consent_given from the persisted call record and refuses to run when false. {OK}",
    f"Verify a 'no' answer routes to human transfer or graceful end with zero data collection. {OK}",
    f"Test in test_safety_layer.py: data collection without consent raises; consent 'no' produces the handoff path. {OK}",
])
add("functional", "apis", "Safety guarantee 5: banned-phrase filter via SafeResponse type before TTS", "safety_requirements/guarantee 5", [
    f"Verify speak()/TTS output only accepts a SafeResponse typed object that filters banned phrases ('guarantee', 'promise', 'definitely will', '100%', 'for sure', 'confirmed appointment at') on construction. {OK}",
    f"Verify there is no code path that sends text to TTS without constructing SafeResponse. {OK}",
    f"Test in test_safety_layer.py: an over-promising draft never reaches output verbatim. {OK}",
])
add("functional", "apis", "Safety guarantee 6: no silent call drop — every failure degrades to human handoff", "safety_requirements/guarantee 6", [
    f"Verify every call turn is wrapped in a try/except boundary routing exceptions, timeouts, and clarification_attempts threshold breaches to the handoff path. {OK}",
    f"Verify the handoff path speaks a fallback message and logs the handoff (transfer or scheduled callback). {OK}",
    f"Test in test_safety_layer.py: force-raise mid-turn asserts a spoken response plus a logged handoff. {OK}",
])
add("functional", "apis", "CI safety suite test_safety_layer.py covers all 6 guarantees and gates the build", "success_criteria/safety", [
    f"Verify test_safety_layer.py contains at least one assertion per guarantee (1-6). {OK}",
    f"Run the suite and confirm all safety tests pass. {OK}",
    f"Verify a CI script or make target runs the safety suite and exits non-zero on failure. {OK}",
])

# ---------------- eligibility agent ----------------
add("agent", "apis", "EligibilityResult model: ACCEPT / DECLINE / NEEDS_MORE_INFO with reasons list", "agent_architecture/eligibility_agent", [
    f"Verify a typed EligibilityResult carries exactly one status of ACCEPT, DECLINE, NEEDS_MORE_INFO plus structured reasons. {OK}",
    f"Unit test constructs each status and serializes to JSON. {OK}",
])
add("agent", "apis", "Service area check against agency zip list", "core_features/eligibility_engine", [
    f"Verify a served zip returns pass and an unserved zip returns a hard fail with reason 'zip not served'. {OK}",
    f"Verify missing zip yields NEEDS_MORE_INFO, not DECLINE. {OK}",
    f"Unit tests cover served, unserved, and missing zip. {OK}",
])
add("agent", "apis", "Insurance check against payer/plan contracts", "core_features/eligibility_engine", [
    f"Verify accepted payer+plan passes; unaccepted payer hard-fails with reason. {OK}",
    f"Verify unknown or fuzzy plan names route through pgvector/pg_trgm fuzzy match before failing. {OK}",
    f"Verify missing insurance info yields NEEDS_MORE_INFO. {OK}",
    f"Unit tests cover accepted, rejected, fuzzy-matched, and missing cases. {OK}",
])
add("agent", "apis", "Clinical matching: diagnosis -> service type -> certification via Neo4j traversal", "database_schema/neo4j", [
    f"Verify the Cypher traversal Diagnosis-REQUIRES->ServiceType-NEEDS_CERTIFICATION->CertType<-HAS_CERTIFICATION-Caregiver-SERVES_AREA->ServiceArea returns matching caregivers. {OK}",
    f"Verify expired certifications are excluded via the HAS_CERTIFICATION expiry property. {OK}",
    f"Unit test with seeded graph: known diagnosis+zip returns the expected caregiver set. {OK}",
])
add("agent", "apis", "Caregiver availability filter: capacity, status, schedule", "data_model/caregiver_roster", [
    f"Verify caregivers at max capacity or with status other than active are excluded from matches. {OK}",
    f"Unit tests cover at-capacity, on-leave, and available caregivers. {OK}",
])
add("agent", "apis", "Coverage rules: insurance plan COVERS service type, prior auth requirements", "core_features/eligibility_engine", [
    f"Verify InsurancePlan-COVERS->ServiceType is cross-checked and uncovered services fail with reason. {OK}",
    f"Verify REQUIRES_AUTH surfaces 'prior authorization required' in the result's documentation needs. {OK}",
    f"Unit tests cover covered, uncovered, and auth-required plans using payer_coverage_rules.json. {OK}",
])
add("agent", "apis", "Decision engine bias: DECLINE only on black-and-white facts, else NEEDS_MORE_INFO", "workflows/decision_engine", [
    f"Verify DECLINE fires only when zip or insurance fails unambiguously. {OK}",
    f"Verify any ambiguity (no caregiver match, missing fields, fuzzy insurance) yields NEEDS_MORE_INFO with specific missing items. {OK}",
    f"Unit tests assert an ambiguous case never returns DECLINE. {OK}",
])
add("agent", "apis", "Eligibility result caching in Redis keyed by zip:payer:plan with short TTL", "database_schema/redis", [
    f"Verify a repeated check hits the cache (no second Neo4j query) within the TTL. {OK}",
    f"Verify cache expiry triggers a fresh traversal. {OK}",
    f"Unit test with fake Redis asserts cache hit and miss behavior. {OK}",
])
add("agent", "apis", "Only the Eligibility Agent writes eligibility/acceptance decisions", "agent_architecture/data_access_rules", [
    f"Verify the intake status transitions to eligible/accepted/declined only through the Eligibility Agent's write path. {OK}",
    f"Unit test: attempts to set an acceptance status from voice or pipeline modules are rejected. {OK}",
])
add("agent", "apis", "Eligibility check performance suitable for mid-call loop (2-3 seconds)", "agent_architecture/voice_agent", [
    f"Measure check_eligibility() end-to-end against local databases and confirm it completes within 3 seconds. {OK}",
    f"Verify the voice layer emits filler speech when the loop exceeds the threshold. {OK}",
])

# ---------------- document pipeline ----------------
add("agent", "apis", "Layer 1 — Ingestion and preprocessing: PDF/TIFF standardization and page cleanup", "document_pipeline/layer 1", [
    f"Verify uploads of PDF and TIFF are standardized to per-page images/text with deskew/denoise/contrast steps applied. {OK}",
    f"Verify each page is tagged scanned-image vs digital-text. {OK}",
    f"Unit test with a sample PDF asserts page count and per-page type detection. {OK}",
])
add("agent", "apis", "Layer 2 — Page classification into document types", "document_pipeline/layer 2", [
    f"Verify each page is classified as one of: physician order, face-to-face note, discharge summary, medication list, insurance card, lab results, consent form, fax cover sheet. {OK}",
    f"Verify fax cover sheets are marked junk and excluded from extraction. {OK}",
    f"Test with a sample packet asserts expected classifications per page. {OK}",
])
add("agent", "apis", "Layer 3 Path B — rule-based extraction for digital-text PDFs (Docling + regex)", "document_pipeline/layer 3", [
    f"Verify Docling parses text layers and regex/keyword rules extract patient name (after 'Patient:'/'Name:'), ICD codes (letter+digits), member IDs by payer format, NPI (10 digits). {OK}",
    f"Unit tests feed known text snippets and assert extracted fields. {OK}",
])
add("agent", "apis", "Layer 3 Path C — Gemini vision extraction for image pages", "document_pipeline/layer 3", [
    f"Verify image pages route to the Gemini Flash vision extractor through the single tokenizing LLM wrapper. {OK}",
    f"Verify extraction returns fields with per-field values from the image. {OK}",
    f"Test with a scanned sample page asserts non-empty structured output (mockable in CI). {OK}",
])
add("agent", "apis", "Layer 4 — Both paths converge into standardized raw JSON per page", "document_pipeline/layer 4", [
    f"Verify rules-path and vision-path outputs normalize to the same schema including extraction_path (rules/vision) per field. {OK}",
    f"Unit test asserts schema equality of both paths' outputs. {OK}",
])
add("agent", "apis", "Layer 5 — Validation Agent: ICD-10, NPI Luhn+NPPES, member ID format, dates, zip, dosage ranges", "document_pipeline/layer 5", [
    f"Verify ICD-10 codes are validated against the reference table. {OK}",
    f"Verify NPI passes Luhn check and (when online) NPPES registry lookup. {OK}",
    f"Verify member ID matches the payer-specific format, DOB is reasonable, discharge date is after admission date, zip exists. {OK}",
    f"Verify medication dosage is checked against medication_dosage_ranges (e.g. Metformin 50000mg flagged as OCR error). {OK}",
    f"Verify an invalid ICD-10 code produces a validation failure record naming the field and rule. {OK}",
    f"Verify an NPI failing the Luhn check is flagged even when NPPES is unreachable. {OK}",
    f"Verify DOB in the future or older than 120 years is rejected as unreasonable. {OK}",
    f"Verify discharge date earlier than admission date is flagged. {OK}",
    f"Verify a nonexistent zip code is flagged against the zip_codes reference table. {OK}",
    f"Unit tests cover a passing record and one failure per validator. {OK}",
])
add("agent", "apis", "Layer 5 — Correction Agent: reasons about validation failures with confidence tiers", "document_pipeline/layer 5", [
    f"Verify 'M17.1I' is auto-corrected to 'M17.11' with high confidence. {OK}",
    f"Verify a medium-confidence correction (e.g. 'H12O456789' O->0) is applied but flagged for review. {OK}",
    f"Verify an uncorrectable value (e.g. 'Lisinopril 200mg') is flagged for human review and added to the gap list for voice verification. {OK}",
    f"Unit tests assert all three confidence outcomes. {OK}",
])
add("agent", "apis", "Layer 5 — Cross-Reference Agent: consistency across pages", "document_pipeline/layer 5", [
    f"Verify mismatched patient name/DOB across documents is flagged. {OK}",
    f"Verify diagnosis text vs ICD code mismatch is flagged. {OK}",
    f"Verify medication-diagnosis inconsistency (Warfarin without anticoagulation indication) is flagged for clinical review. {OK}",
    f"Unit tests cover each cross-reference rule. {OK}",
])
add("agent", "apis", "Layer 6 — Completeness check against the requirements checklist with gap generation", "document_pipeline/layer 6", [
    f"Verify the checklist covers demographics, signed physician orders, face-to-face documentation, insurance info, diagnosis+ICD, homebound status, medication list. {OK}",
    f"Verify each missing item becomes a specific gap_list row with a follow-up task for the Voice Agent. {OK}",
    f"Test with an incomplete packet asserts the expected gaps. {OK}",
])
add("agent", "apis", "Layer 7 — Confidence scoring and routing (HIGH/MEDIUM/LOW)", "document_pipeline/layer 7", [
    f"Verify HIGH (rules+validated+cross-confirmed) auto-populates the intake record. {OK}",
    f"Verify MEDIUM (vision+validated, single doc) auto-populates and flags for review. {OK}",
    f"Verify LOW (failed validation/uncertain correction) is withheld and added to the gap list. {OK}",
    f"Unit tests assert routing per tier. {OK}",
])
add("agent", "apis", "Pipeline state tracked in Redis per document across layers", "database_schema/redis", [
    f"Verify pipeline:{{doc_id}} records current layer, extracted-so-far, and validation status as the document progresses. {OK}",
    f"Test asserts state transitions through all 7 layers. {OK}",
])
add("functional", "apis", "End-to-end pipeline run on sample referral PDFs with seeded OCR errors", "success_criteria/functionality", [
    f"Run POST /process-document with each sample PDF from data/synthetic. {OK}",
    f"Verify all 7 layers execute and structured JSON with confidence scores and gap list is returned. {API_OK}",
    f"Verify the seeded OCR error (e.g. 'M17.1I') is corrected with the right confidence. {OK}",
    f"Verify extracted fields land in extracted_fields with source document and page traceability. {OK}",
    f"Verify an intake_records row is created with status reflecting completeness. {OK}",
])

# ---------------- voice agent ----------------
add("agent", "apis", "Twilio ConversationRelay WebSocket handler at /twilio/conversation-relay", "technology_stack/telephony", [
    f"Verify the WebSocket endpoint accepts ConversationRelay setup, prompt, and interrupt message types. {OK}",
    f"Verify TwiML/voice webhook configuration connects the Twilio number to the WebSocket URL (PUBLIC_BASE_URL). {OK}",
    f"Integration test with a simulated ConversationRelay client completes a message round-trip. {OK}",
])
add("agent", "ai-agents", "Consent gather node: AI + recording disclosure, yes/no branch, persisted flag", "workflows/flow Discharge planner calls", [
    f"Verify the first spoken message discloses AI handling and recording and asks for consent. {OK}",
    f"Verify 'yes' persists consent_given=true on the call record before any data question. {OK}",
    f"Verify 'no' routes to transfer/graceful end with zero data collection. {OK}",
    f"Test both branches via the simulated call harness. {OK}",
])
add("agent", "ai-agents", "Caller type detection routing to Provider / Family / Patient modes (WORKFLOW Path A Step 3)", "core_features/inbound_call_handling", [
    f"Verify detection runs only after consent_given=true, so no classification or data collection precedes consent. {OK}",
    f"Verify early-turn classification assigns provider, family, or patient mode from caller statements. {OK}",
    f"Verify the mode selects the corresponding static system prompt (Layer 1 control) and is persisted as call.mode in Redis. {OK}",
    f"Verify a caller who self-identifies ('I'm the discharge planner', 'I'm his daughter', 'I need care for myself') maps to the correct mode. {OK}",
    f"Verify inbound is never routed to Outbound mode — Outbound is reserved for agency-initiated calls carrying a mission parameter. {OK}",
    f"Tests assert each mode is selected from representative utterances for provider, family, and patient. {OK}",
])
add("agent", "ai-agents", "Caller type detection: ambiguous or low-confidence classification handling (WORKFLOW Path A Step 3)", "core_features/inbound_call_handling", [
    f"Verify an ambiguous opening (caller type unclear) triggers one neutral clarifying question rather than guessing a mode. {OK}",
    f"Verify classification confidence is recorded on the call record and low confidence keeps the safe default mode. {OK}",
    f"Verify the default mode when still unresolved is the most cautious (Family/plain-language, never-promise) profile. {OK}",
    f"Verify repeated failure to resolve caller type increments clarification_attempts and can reach the human handoff path (guarantee 6). {OK}",
    f"Test asserts an ambiguous utterance yields a clarifying question and the cautious default, not a random mode. {OK}",
])
add("agent", "ai-agents", "Mid-call mode switch when caller type becomes clearer (WORKFLOW Path A Step 3)", "core_features/inbound_call_handling", [
    f"Verify a later turn revealing the true caller type re-assigns call.mode and swaps to the corresponding system prompt. {OK}",
    f"Verify a mode switch preserves already-collected structured fields in call state (no data loss on switch). {OK}",
    f"Verify each mode transition is logged with old_mode, new_mode, and the triggering turn for dashboard visibility. {OK}",
    f"Verify a switch never bypasses the 4 safety gates on subsequent turns. {OK}",
    f"Test asserts a family->provider switch mid-call keeps prior fields and applies the new prompt. {OK}",
])
add("agent", "ai-agents", "Provider mode: clinical, structured intake with real-time eligibility mid-call", "agent_architecture/voice_agent", [
    f"Verify provider mode collects name, DOB, diagnosis, insurance, zip in a structured flow. {OK}",
    f"Verify extracted data flows to the orchestrator -> Eligibility Agent mid-call and the result shapes the next utterance (Layer 2 dynamic control). {OK}",
    f"Verify an ACCEPT with missing F2F note produces the specific document ask. {OK}",
    f"Verify a DECLINE result is communicated honestly and immediately during the call. {OK}",
    f"Verify a NEEDS_MORE_INFO result asks for the specific missing fields. {OK}",
    f"Verify the eligibility loop uses only tokenized structured fields (zip, payer, service type). {OK}",
    f"Verify every provider-mode utterance passed the banned-phrase filter before TTS. {OK}",
    f"Verify collected fields accumulate in the call state across turns. {OK}",
    f"Simulated call test reaches a real-time ACCEPT/DECLINE/NEEDS_MORE_INFO before hangup. {OK}",
])
add("agent", "ai-agents", "Family mode: compassionate plain language, never promises coverage", "core_features/inbound_call_handling", [
    f"Verify family-mode prompt uses plain language, no jargon, and captures partial information gracefully. {OK}",
    f"Verify responses never promise coverage or availability (banned-phrase filter plus prompt constraints) and always schedule a coordinator follow-up. {OK}",
    f"Simulated midnight family call ends with intake status NEW, human flag by 9 AM, and SMS confirmation queued. {OK}",
])
add("agent", "ai-agents", "Patient mode: slower pace, explains physician order requirement", "core_features/inbound_call_handling", [
    f"Verify patient mode explains the physician order requirement for skilled care and offers to coordinate with their doctor. {OK}",
    f"Verify contact info is captured for follow-up. {OK}",
    f"Simulated self-referral call test asserts the explanation and captured contact. {OK}",
])
add("agent", "ai-agents", "Outbound mode: single-mission calls (collect document, verify detail, schedule visit)", "agent_architecture/voice_agent", [
    f"Verify outbound calls carry exactly one mission parameter and open with the same consent gather. {OK}",
    f"Verify outbound calls pass through the identical safety-gated flow (tokenize, filter, handoff). {OK}",
    f"Test asserts an outbound document-request call collects the answer and updates the gap. {OK}",
])
add("agent", "apis", "Real-time structured extraction from caller speech into the call state", "agent_architecture/safety_gated_call_flow", [
    f"Verify each caller turn updates call:{{call_sid}} in Redis with collected fields and remaining questions. {OK}",
    f"Verify only structured, tokenized fields (zip, payer, service type) are sent to eligibility — never names. {OK}",
    f"Test asserts incremental field accumulation across turns. {OK}",
])
add("agent", "apis", "4-gate safety flow on every conversation turn", "agent_architecture/safety_gated_call_flow", [
    f"Verify the turn pipeline order: extract -> tokenize -> deterministic eligibility (parallel) -> LLM draft -> rehydrate -> banned-phrase filter -> TTS. {OK}",
    f"Verify no code path skips a gate. {OK}",
    f"Integration test traces one turn and asserts all gates executed in order. {OK}",
])
add("agent", "apis", "Filler speech when the eligibility loop exceeds 2-3 seconds", "agent_architecture/voice_agent", [
    f"Verify a timer emits natural filler speech ('Let me check our availability for that area... one moment') when the loop is slow. {OK}",
    f"Test with an artificially delayed eligibility call asserts filler is spoken. {OK}",
])
add("agent", "apis", "Clarification attempts counter with threshold-triggered human handoff", "safety_requirements/guarantee 6", [
    f"Verify clarification_attempts increments in call state on misunderstood turns. {OK}",
    f"Verify crossing the threshold routes to the handoff path with spoken fallback. {OK}",
    f"Test asserts the handoff after N failed clarifications. {OK}",
])
add("functional", "apis", "Call transcript capture and consent flag persisted per call", "database_schema/postgresql", [
    f"Verify call_records stores call_sid, mode, consent_given, full transcript, timestamps. {OK}",
    f"Verify the transcript is retrievable via GET /intakes/:id/transcript. {API_OK}",
])

# ---------------- orchestrator ----------------
add("agent", "apis", "LangGraph orchestrator state machine: received -> processed -> decided lifecycle", "agent_architecture/core_principle", [
    f"Verify a LangGraph graph models referral received -> document processing -> eligibility -> decision -> follow-up. {OK}",
    f"Verify the orchestrator never calls Twilio, never parses documents, and never queries databases directly — only routes to sub-agents. {OK}",
    f"Unit test drives a referral through the full state sequence. {OK}",
])
add("agent", "apis", "Orchestrator routing between pipeline, eligibility, and voice actions", "implementation_steps/step 5", [
    f"Verify a completed document run routes extracted data to the Eligibility Agent. {OK}",
    f"Verify NEEDS_MORE_INFO results trigger follow-up tasks (outbound call/SMS) for each gap. {OK}",
    f"Test asserts routing decisions per eligibility outcome. {OK}",
])
add("agent", "apis", "Merge logic: document + voice data into one unified intake record", "implementation_steps/step 5", [
    f"Verify fields from a fax and a subsequent call about the same patient merge into one intake record without duplicates. {OK}",
    f"Verify higher-confidence values win on conflict and conflicts are flagged. {OK}",
    f"Unit test merges overlapping document and voice data and asserts the resolved record. {OK}",
])
add("functional", "apis", "Intake record status lifecycle with timestamps for every event", "data_model/pipeline_operational", [
    f"Verify statuses new, processing, pending_documents, eligible, accepted, declined transition correctly with validation of legal transitions. {OK}",
    f"Verify timestamps recorded for received, extraction complete, eligibility checked, first call made, patient admitted. {OK}",
    f"Unit tests cover a legal path and an illegal transition rejection. {OK}",
])
add("functional", "apis", "Audit trail: every decision logged with the data that informed it", "core_features/guardrails_compliance", [
    f"Verify every eligibility decision writes an audit_trail row containing inputs (zip, payer, diagnosis, caregiver matches) and the outcome. {OK}",
    f"Verify no PHI appears in application logs (tokenized values only). {OK}",
    f"Test asserts an audit row per decision and log scan finds no identifier patterns. {OK}",
])
add("functional", "apis", "ACID protection against double-accepting a patient", "technology_stack/databases", [
    f"Verify accepting an intake uses a transaction/row lock so two concurrent accepts cannot both succeed. {OK}",
    f"Concurrency test fires two simultaneous accepts and asserts exactly one wins. {OK}",
])

# ---------------- follow-up agent ----------------
add("agent", "services", "Follow-up Agent: SMS confirmations via Twilio Programmable SMS", "core_features/outbound_follow_up", [
    f"Verify POST /follow-up/sms sends a confirmation SMS with referral ID through Twilio (mockable client). {API_OK}",
    f"Verify the send is logged in follow_up_events with result. {OK}",
])
add("agent", "services", "Document request links via SMS/email", "core_features/outbound_follow_up", [
    f"Verify gap follow-ups can include a document upload link in SMS/email. {OK}",
    f"Verify the link resolves to the upload endpoint feeding the document pipeline. {OK}",
])
add("agent", "services", "Retry logic: voicemail -> 2h retry, silent SMS -> next morning, 3 failures -> human escalation", "core_features/outbound_follow_up", [
    f"Verify a voicemail result schedules a retry in 2 hours via the Redis retry_queue. {OK}",
    f"Verify an unanswered SMS schedules a next-morning follow-up. {OK}",
    f"Verify the third failed contact attempt escalates to a human coordinator and stops automated retries. {OK}",
    f"Unit tests cover each retry rule and the escalation cutoff. {OK}",
])
add("agent", "services", "Outbound call trigger re-enters the safety-gated flow", "core_features/outbound_follow_up", [
    f"Verify POST /follow-up/outbound-call initiates a Twilio outbound call whose flow starts at the consent node. {API_OK}",
    f"Verify there is no separate unguarded outbound path in the codebase. {OK}",
])
add("agent", "services", "Callback scheduling with POST /follow-up/schedule", "api_endpoints_summary/follow_up", [
    f"Verify scheduling persists to follow_up_events and enqueues in retry_queue with the target time. {API_OK}",
    f"Verify the scheduler worker picks up due items and executes the action. {OK}",
])
add("agent", "services", "Scheduler worker service processing the Redis retry queue", "repository_structure", [
    f"Verify a services/ worker polls retry_queue and dispatches due follow-ups (call, SMS, escalation). {OK}",
    f"Verify Twilio rate limits are respected via the Redis rate-limit keys. {OK}",
    f"Test with a fake clock asserts due items are dispatched exactly once. {OK}",
])

# ---------------- API ----------------
add("api", "apis", "GET /health with per-dependency status", "api_endpoints_summary/core", [
    f"GET /health returns 200 with status for postgres, neo4j, redis. {API_OK}",
    f"Verify a downed dependency is reported degraded without crashing the endpoint. {OK}",
])
add("api", "apis", "POST /eligibility-check returns status with reasons", "api_endpoints_summary/core", [
    f"POST with zip/payer/plan/diagnosis returns ACCEPT, DECLINE, or NEEDS_MORE_INFO plus reasons and documentation needs. {API_OK}",
    f"Verify request validation rejects malformed payloads with 422. {OK}",
    f"Integration tests cover each of the three outcomes. {OK}",
])
add("api", "apis", "POST /process-document runs the 7-layer pipeline", "api_endpoints_summary/core", [
    f"POST a PDF and receive structured JSON with extracted fields, confidence scores, and gap list. {API_OK}",
    f"Verify processing is tracked in Redis and results persisted to PostgreSQL. {OK}",
])
add("api", "apis", "GET /intakes lists referrals with status for the dashboard", "api_endpoints_summary/intake", [
    f"GET /intakes returns all referrals with status, timestamps, and urgency. {API_OK}",
    f"Verify filtering by status works. {OK}",
])
add("api", "apis", "GET /intakes/:id returns the full intake record", "api_endpoints_summary/intake", [
    f"Response includes extracted fields with confidence, gaps, transcript references, and referral source. {API_OK}",
    f"Verify 404 for unknown id. {OK}",
])
add("api", "apis", "GET /intakes/:id/gaps returns the gap list with follow-up status", "api_endpoints_summary/intake", [
    f"Response lists each missing item, actions taken, attempts, and current status. {API_OK}",
])
add("api", "apis", "GET /intakes/:id/transcript returns call transcripts", "api_endpoints_summary/intake", [
    f"Response includes per-call transcript, mode, and consent status. {API_OK}",
])
add("api", "apis", "GET /analytics/referral-sources: volume, acceptance rate, response times", "api_endpoints_summary/dashboard_support", [
    f"Response aggregates referral count, acceptance rate, and average response time per source. {API_OK}",
    f"Integration test with seeded data asserts the computed metrics. {OK}",
])
add("api", "apis", "GET /analytics/time-to-decision speed metrics", "api_endpoints_summary/dashboard_support", [
    f"Response returns time-to-decision distribution/averages computed from event timestamps. {API_OK}",
])
add("api", "apis", "GET /caregivers/matches/:intake_id with selection/rejection reasons", "api_endpoints_summary/dashboard_support", [
    f"Response lists considered caregivers and why each was selected or ruled out (cert, area, capacity, expiry). {API_OK}",
])
add("api", "apis", "Twilio webhook signature validation on inbound HTTP webhooks", "success_criteria/judging_alignment security", [
    f"Verify inbound Twilio webhooks validate the X-Twilio-Signature header and reject invalid signatures with 403. {OK}",
    f"Test with a forged signature asserts rejection. {OK}",
])
add("api", "apis", "Consistent error envelope and no-PHI error messages across the API", "core_features/guardrails_compliance", [
    f"Verify errors return a consistent JSON envelope without stack traces or identifiers. {OK}",
    f"Test asserts a triggered error contains no patient identifiers. {OK}",
])

# ---------------- personalization ----------------
add("functional", "apis", "Returning caller recognition from referral source phone number", "core_features/caller_personalization", [
    f"Verify an inbound call from a known referral-source number loads their history before the greeting. {OK}",
    f"Verify the greeting acknowledges the caller ('Hi Sarah, calling from Mount Sinai?') using tokenized-safe rendering. {OK}",
    f"Test with a seeded referral source asserts the personalized greeting path. {OK}",
])
add("functional", "apis", "Referral source history: count, acceptance rate, preferred communication method", "core_features/caller_personalization", [
    f"Verify referral_sources stores and updates history per interaction. {OK}",
    f"Verify the Voice Agent receives history as context for returning callers. {OK}",
])
add("functional", "apis", "Cross-interaction context: prior family call informs today's follow-up", "core_features/caller_personalization", [
    f"Verify a follow-up call about an existing intake loads the prior transcript summary and collected fields. {OK}",
    f"Test: create an intake via a simulated family call, then start a follow-up and assert the context is present. {OK}",
])

# ---------------- guardrails ----------------
add("functional", "ai-agents", "Clinical guardrail: never gives medical advice", "core_features/guardrails_compliance", [
    f"Verify prompts instruct refusal of medical advice with redirection to the physician/coordinator. {OK}",
    f"Test: a medical-advice question in a simulated call yields a refusal + redirect, never advice. {OK}",
])
add("functional", "ai-agents", "Operational guardrail: no admission promise before eligibility confirms; human named as final confirmer", "core_features/guardrails_compliance", [
    f"Verify accept-style language is only generated when an EligibilityResult of ACCEPT is present. {OK}",
    f"Verify responses name a human coordinator as the final confirmer. {OK}",
    f"Test asserts a pre-eligibility turn contains no admission confirmation. {OK}",
])
add("functional", "ai-agents", "Escalation on low confidence or complexity", "core_features/guardrails_compliance", [
    f"Verify low-confidence extractions and complex scenarios flag the intake for the human needs-review queue. {OK}",
    f"Test asserts a LOW-confidence field produces a review flag. {OK}",
])
add("functional", "apis", "Field-level traceability: every extracted field maps to source document and page", "core_features/guardrails_compliance", [
    f"Verify extracted_fields rows carry source document id, page number, and extraction path. {OK}",
    f"Test asserts traceability for every field extracted from a sample PDF. {OK}",
])

# ---------------- dashboard UI ----------------
add("ui", "apps", "Pipeline board: referrals by status with timestamps and urgency badges", "ui_layout/dashboard", [
    f"Verify columns/sections for new, processing, pending documents, eligible, accepted, declined. {UI_OK}",
    f"Verify each card shows patient reference, timestamps, and an urgency badge. {UI_OK}",
    f"Component test renders seeded intakes into the correct columns. {OK}",
])
add("ui", "apps", "Referral detail view with confidence color coding (green/yellow/red)", "ui_layout/dashboard", [
    f"Verify extracted fields render with green (high), yellow (medium), red (low) confidence indicators. {UI_OK}",
    f"Verify each field shows source document and page traceability. {UI_OK}",
    f"Component test asserts color mapping per confidence tier. {OK}",
])
add("ui", "apps", "Gap list panel with per-gap action history", "ui_layout/dashboard", [
    f"Verify each gap shows the missing item, actions taken (SMS sent, call attempted), attempts, and status. {UI_OK}",
    f"Component test renders a gap with two actions and asserts the history order. {OK}",
])
add("ui", "apps", "Transcript panel: full transcripts, consent status, caller mode", "ui_layout/dashboard", [
    f"Verify transcripts render per call with consent status badge and mode label (provider/family/patient/outbound). {UI_OK}",
    f"Component test asserts consent and mode display. {OK}",
])
add("ui", "apps", "Caregiver match panel with selection/rejection reasons", "ui_layout/dashboard", [
    f"Verify considered caregivers list shows why each was selected or ruled out. {UI_OK}",
    f"Component test renders match data from GET /caregivers/matches/:intake_id. {OK}",
])
add("ui", "apps", "Analytics view: referral source volume, acceptance rates, time-to-decision", "ui_layout/dashboard", [
    f"Verify charts/tables render referral-source analytics and time-to-decision metrics from the analytics endpoints. {UI_OK}",
    f"Component test asserts rendering with seeded metric data. {OK}",
])
add("ui", "apps", "Needs-review queue for flagged medium/low confidence fields and escalations", "ui_layout/dashboard", [
    f"Verify flagged fields and escalations appear in a dedicated queue for the human coordinator. {UI_OK}",
    f"Component test asserts a flagged field appears in the queue. {OK}",
])
add("ui", "apps", "Live/refreshing pipeline status so demo updates are visible", "implementation_steps/demo_script", [
    f"Verify the dashboard reflects backend status changes (polling or websocket) without a manual full reload. {UI_OK}",
    f"Test: change an intake status via API and assert the board updates. {OK}",
])
add("ui", "apps", "Document upload UI feeding POST /process-document for the fax demo", "implementation_steps/demo_script", [
    f"Verify a PDF can be uploaded from the dashboard and the pipeline progress (7 layers) is visible. {UI_OK}",
    f"Test: upload a sample PDF and assert layer progress renders. {OK}",
])
add("style", "apps", "Consistent design system: colors, typography, spacing tokens", "hackathon_constraints/judging_criteria UI/UX", [
    f"Verify a central token set (Tailwind config or CSS variables) drives colors/spacing; no ad-hoc hex values scattered in components. {OK}",
    f"Visual pass confirms consistent look across all panels. {UI_OK}",
])
add("style", "apps", "Status and confidence color semantics consistent across the app", "ui_layout/dashboard", [
    f"Verify the same green/yellow/red semantics are used everywhere confidence appears, and status colors are consistent between board and detail view. {UI_OK}",
])
add("style", "apps", "Responsive layout: dashboard usable on laptop and projector resolutions", "hackathon_constraints/judging_criteria UI/UX", [
    f"Verify the board and detail views render without overflow at 1280x800 and 1920x1080. {UI_OK}",
])
add("style", "apps", "Loading, empty, and error states for every data panel", "hackathon_constraints/judging_criteria UI/UX", [
    f"Verify each panel shows a loading indicator, a friendly empty state, and a non-technical error state. {UI_OK}",
    f"Component tests assert all three states per panel. {OK}",
])
add("style", "apps", "Accessible components: labels, contrast, keyboard navigation on interactive elements", "hackathon_constraints/judging_criteria UI/UX", [
    f"Verify interactive elements have accessible names and visible focus, and confidence colors meet contrast plus a non-color cue (icon/text). {UI_OK}",
])
add("style", "apps", "Urgency badges visually distinct (routine / urgent / 24-hour start of care)", "data_model/care_request", [
    f"Verify the three urgency levels render distinct badges on the pipeline board. {UI_OK}",
])

# ---------------- external integrations ----------------
add("functional", "apis", "NPPES NPI Registry live validation with offline fallback", "data_model/knowledge_reference", [
    f"Verify NPI validation calls the free NPPES API and interprets found/not-found. {OK}",
    f"Verify a network failure degrades to Luhn-only validation with a MEDIUM confidence flag, never a crash. {OK}",
    f"Test with mocked API covers found, not found, and timeout. {OK}",
])
add("functional", "apis", "RxNorm medication normalization via RxNav API", "data_model/knowledge_reference", [
    f"Verify medication names normalize through RxNav with fuzzy local fallback for variants. {OK}",
    f"Test with mocked API asserts normalization of a known variant. {OK}",
])
add("functional", "apis", "pgvector/pg_trgm fuzzy matching for insurance plans, medications, physician names", "technology_stack/databases", [
    f"Verify fuzzy lookup resolves near-miss names ('Untied Healthcare' -> 'UnitedHealthcare') above a similarity threshold. {OK}",
    f"Unit tests cover a hit, a below-threshold miss, and an exact match. {OK}",
])
add("functional", "infra", "Twilio number + ConversationRelay + ngrok wiring documented and scriptable", "technology_stack/infrastructure", [
    f"Verify infra contains a setup script/README section wiring the Twilio number's voice webhook to PUBLIC_BASE_URL. {OK}",
    f"Verify starting the tunnel and updating the webhook is a single documented command sequence. {OK}",
])

# ---------------- end-to-end functional flows ----------------
add("functional", "apis", "E2E flow 1: discharge planner call from hello to done", "workflows/flow Discharge planner calls", [
    f"Start the stack and open a simulated ConversationRelay session in PROVIDER mode. {OK}",
    f"Verify the consent disclosure is the first utterance and 'yes' is logged. {OK}",
    f"Provide referral details (name, DOB, diagnosis, insurance, zip) across turns. {OK}",
    f"Verify mid-call eligibility runs and returns ACCEPT with a missing F2F note. {OK}",
    f"Verify the spoken response passes the banned-phrase filter and asks for the F2F documentation specifically. {OK}",
    f"End the call and verify an intake record exists with status PENDING_DOCUMENTS. {OK}",
    f"Verify an SMS confirmation with the referral ID was sent (mock Twilio). {OK}",
    f"Verify a gap follow-up is scheduled in 4 hours in the retry queue. {OK}",
    f"Verify the full transcript and consent flag are persisted. {OK}",
    f"Verify audit_trail contains the eligibility decision with its inputs. {OK}",
    f"Verify the dashboard shows the new referral in the pending-documents column. {UI_OK}",
])
add("functional", "apis", "E2E flow 2: fax referral arrives and triggers follow-ups", "workflows/flow Fax referral arrives", [
    f"POST a sample referral PDF to /process-document. {API_OK}",
    f"Verify the document advances through all 7 pipeline layers with Redis state visible per layer. {OK}",
    f"Verify extraction output includes confidence scores and the expected gap list (missing F2F note, low-confidence member ID). {OK}",
    f"Verify the orchestrator routes the result to the Eligibility Agent and receives ACCEPT-with-gaps. {OK}",
    f"Verify an outbound provider call task is created to verify the member ID and request the F2F note. {OK}",
    f"Verify an outbound patient/family call task is created to confirm address and schedule the first visit. {OK}",
    f"Verify an SMS/email with a document upload link is queued. {OK}",
    f"Verify both outbound calls are configured to start at the consent node (safety-gated). {OK}",
    f"Verify the intake record, extracted fields, gaps, and audit trail are all persisted and visible in the dashboard detail view. {UI_OK}",
    f"Verify time-to-decision timestamps were recorded at each stage. {OK}",
])
add("functional", "apis", "E2E flow 3: family member calls at midnight", "workflows/flow Family member calls at midnight", [
    f"Open a simulated call classified into FAMILY mode. {OK}",
    f"Verify a compassionate greeting plus consent gather occurs first. {OK}",
    f"Provide partial information (no clinical details) and verify the agent accepts incompleteness gracefully. {OK}",
    f"Verify a preliminary eligibility check runs on zip and general insurance type. {OK}",
    f"Verify the response sets expectations without a firm commitment and asks to prepare the insurance card and doctor contact. {OK}",
    f"Verify banned phrases never appear in any response of the session. {OK}",
    f"End the call and verify the intake record has status NEW and is flagged for a human coordinator by 9 AM. {OK}",
    f"Verify the SMS confirmation was queued. {OK}",
    f"Verify the transcript shows mode=family and consent=true. {OK}",
    f"Verify the dashboard needs-review queue shows the coordinator flag. {UI_OK}",
])
add("functional", "apis", "E2E flow 4: wrong zip / unaccepted insurance -> fast honest DECLINE", "workflows/situation_handling", [
    f"Simulate a provider call with an unserved zip code. {OK}",
    f"Verify the eligibility result is DECLINE with the specific reason. {OK}",
    f"Verify the spoken decline is honest and fast so the referral source can place the patient elsewhere. {OK}",
    f"Verify the intake record is marked declined with the reason in the audit trail. {OK}",
])
add("functional", "apis", "E2E flow 5: outbound follow-up call collects a missing document commitment", "implementation_steps/demo_script", [
    f"Given an intake with a gap, trigger POST /follow-up/outbound-call. {API_OK}",
    f"Verify the outbound call opens with consent and states its single mission. {OK}",
    f"Simulate the provider agreeing to send the document; verify the gap status updates and the retry is cancelled. {OK}",
    f"Verify the interaction is transcribed and audited. {OK}",
])
add("functional", "apis", "E2E flow 6: agent error mid-call degrades to spoken fallback + human handoff", "workflows/situation_handling", [
    f"Force an exception during a simulated call turn. {OK}",
    f"Verify the caller hears the fallback ('Let me connect you with a coordinator') — never silence. {OK}",
    f"Verify a handoff (transfer or scheduled callback) is logged and visible in the dashboard. {OK}",
])
add("functional", "apis", "Concurrent calls and parallel fax processing without state bleed", "success_criteria/judging_alignment scalability", [
    f"Run two simulated calls concurrently and verify call:{{call_sid}} states never mix fields. {OK}",
    f"Process two PDFs in parallel and verify pipeline:{{doc_id}} states remain independent. {OK}",
])
add("functional", "apis", "Garbled OCR fields are never auto-populated; verified by phone instead", "workflows/situation_handling", [
    f"Process a PDF with an uncorrectable garbled field and verify it is withheld from the intake record. {OK}",
    f"Verify a gap entry with a voice-verification task is created for that field. {OK}",
])
add("functional", "apis", "Demo compliance checklist verification script", "success_criteria/compliance_checklist", [
    f"Verify a script/make target runs test_safety_layer.py plus smoke checks (health, eligibility, one PDF, one simulated call) before any demo. {OK}",
    f"Run it and confirm all checks pass with a summarized report. {OK}",
])
add("functional", "apis", "Backend code coverage >= 80% on core modules", "success_criteria", [
    f"Run pytest with coverage over eligibility, pipeline, voice, orchestrator, follow-up, and safety modules. {OK}",
    f"Verify total coverage is at least 80% and the report is generated. {OK}",
])
add("functional", "apps", "Frontend test coverage on dashboard components", "success_criteria", [
    f"Run the frontend test suite (vitest/RTL) covering board, detail, gaps, transcript, matches, analytics, review queue components. {OK}",
    f"Verify coverage of the components package is at least 80%. {OK}",
])
add("functional", "infra", "One-command local bring-up via init.sh", "implementation_steps/prework", [
    f"Run ./init.sh on a clean checkout and verify databases start, migrations/seeds apply, backend and frontend start. {OK}",
    f"Verify the script prints the URLs for API, dashboard, and Neo4j browser plus next steps for ngrok/Twilio. {OK}",
])

assert len(F) >= 100, f"only {len(F)} features"
long_tests = [f for f in F if len(f["steps"]) >= 10]
assert len(long_tests) >= 5, f"only {len(long_tests)} tests with 10+ steps"

with open("feature_list.json", "w") as fh:
    json.dump(F, fh, indent=2)
print(f"wrote {len(F)} features; {len(long_tests)} with 10+ steps")
