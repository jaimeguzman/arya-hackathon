-- IntakeAI Phase 1 schema — structure only, zero INSERTs
-- ponytail: pgvector image available but unused in Phase 1

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Enums
CREATE TYPE intake_status AS ENUM (
    'new', 'processing', 'pending_documents', 'eligible',
    'accepted', 'declined', 'escalated'
);

CREATE TYPE intake_source AS ENUM (
    'fax', 'inbound_call_provider', 'inbound_call_family',
    'inbound_call_patient', 'physician_referral', 'snf_referral'
);

CREATE TYPE caregiver_type AS ENUM (
    'RN', 'LPN', 'CNA', 'PT', 'OT', 'ST', 'HHA'
);

CREATE TYPE caregiver_status AS ENUM (
    'active', 'on_leave', 'suspended', 'inactive'
);

CREATE TYPE document_processing_status AS ENUM (
    'uploaded', 'preprocessing', 'classifying', 'extracting',
    'validating', 'complete', 'failed'
);

CREATE TYPE call_direction AS ENUM ('inbound', 'outbound');

CREATE TYPE call_mode AS ENUM (
    'provider', 'family', 'patient', 'outbound_followup'
);

CREATE TYPE call_status AS ENUM (
    'active', 'completed', 'failed', 'voicemail', 'no_answer'
);

CREATE TYPE follow_up_type AS ENUM (
    'sms_sent', 'email_sent', 'outbound_call_attempted', 'voicemail_left',
    'callback_scheduled', 'document_received', 'document_requested',
    'eligibility_recheck'
);

CREATE TYPE follow_up_status AS ENUM (
    'pending', 'completed', 'failed', 'cancelled'
);

-- Shared updated_at trigger
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 1. intake_records
-- ponytail: JSONB per domain instead of 40+ columns — flexible for hackathon;
-- ceiling: no DB-level field constraints; upgrade: promote critical fields to columns
CREATE TABLE intake_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status intake_status NOT NULL DEFAULT 'new',
    source intake_source NOT NULL,
    urgency TEXT NOT NULL DEFAULT 'routine',
    patient_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    clinical_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    physician_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    insurance_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    care_request JSONB NOT NULL DEFAULT '{}'::jsonb,
    referral_source JSONB NOT NULL DEFAULT '{}'::jsonb,
    extraction_confidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    gaps JSONB NOT NULL DEFAULT '[]'::jsonb,
    eligibility_decision TEXT NOT NULL DEFAULT 'pending',
    eligibility_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    matched_caregivers JSONB NOT NULL DEFAULT '[]'::jsonb,
    escalated BOOLEAN NOT NULL DEFAULT FALSE,
    escalation_reason TEXT,
    human_review_required BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_intake_records_updated_at
    BEFORE UPDATE ON intake_records
    FOR EACH ROW EXECUTE PROCEDURE set_updated_at();

-- 2. caregivers
CREATE TABLE caregivers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    type caregiver_type NOT NULL,
    status caregiver_status NOT NULL DEFAULT 'active',
    -- ponytail: text[] instead of join table; ceiling: weak per-element indexing
    languages TEXT[] NOT NULL DEFAULT '{}',
    current_patient_load INTEGER NOT NULL DEFAULT 0,
    max_patient_capacity INTEGER NOT NULL DEFAULT 8,
    phone TEXT,
    email TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_caregivers_updated_at
    BEFORE UPDATE ON caregivers
    FOR EACH ROW EXECUTE PROCEDURE set_updated_at();

-- 3. caregiver_certifications
-- ponytail: CURRENT_DATE is not IMMUTABLE, so GENERATED STORED can't use it.
-- Ceiling: is_active must be evaluated in queries as
--   (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
-- Upgrade: nightly job materializing is_active, or app-layer hybrid property.
CREATE TABLE caregiver_certifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    caregiver_id UUID NOT NULL REFERENCES caregivers(id) ON DELETE CASCADE,
    certification_name TEXT NOT NULL,
    issued_date DATE,
    expiry_date DATE
);

CREATE INDEX idx_caregiver_certs_lookup
    ON caregiver_certifications (caregiver_id, certification_name);

-- 4. caregiver_service_areas
CREATE TABLE caregiver_service_areas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    caregiver_id UUID NOT NULL REFERENCES caregivers(id) ON DELETE CASCADE,
    zip_code TEXT NOT NULL
);

CREATE INDEX idx_caregiver_service_areas_zip ON caregiver_service_areas (zip_code);
CREATE INDEX idx_caregiver_service_areas_cg ON caregiver_service_areas (caregiver_id);

-- 5. caregiver_availability
CREATE TABLE caregiver_availability (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    caregiver_id UUID NOT NULL REFERENCES caregivers(id) ON DELETE CASCADE,
    day_of_week INTEGER NOT NULL CHECK (day_of_week >= 0 AND day_of_week <= 6),
    start_time TIME NOT NULL,
    end_time TIME NOT NULL
);

CREATE INDEX idx_caregiver_availability_day
    ON caregiver_availability (caregiver_id, day_of_week);

-- 6. service_areas
CREATE TABLE service_areas (
    zip_code TEXT PRIMARY KEY,
    borough TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE
);

-- 7. insurance_contracts
CREATE TABLE insurance_contracts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payer_name TEXT NOT NULL,
    plan_name TEXT NOT NULL,
    plan_type TEXT NOT NULL,
    accepted BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT
);

CREATE INDEX idx_insurance_contracts_accepted
    ON insurance_contracts (payer_name, plan_name)
    WHERE accepted = TRUE;

-- 8. referral_sources
CREATE TABLE referral_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    facility_name TEXT NOT NULL,
    facility_type TEXT NOT NULL,
    contact_name TEXT,
    phone TEXT,
    fax TEXT,
    email TEXT,
    ehr_system TEXT,
    total_referrals INTEGER NOT NULL DEFAULT 0,
    accepted_referrals INTEGER NOT NULL DEFAULT 0,
    acceptance_rate NUMERIC GENERATED ALWAYS AS (
        CASE
            WHEN total_referrals = 0 THEN NULL
            ELSE accepted_referrals::numeric / total_referrals::numeric
        END
    ) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_referral_sources_updated_at
    BEFORE UPDATE ON referral_sources
    FOR EACH ROW EXECUTE PROCEDURE set_updated_at();

-- 9. documents
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_record_id UUID REFERENCES intake_records(id) ON DELETE SET NULL,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    page_count INTEGER,
    processing_status document_processing_status NOT NULL DEFAULT 'uploaded',
    failed_at_layer INTEGER CHECK (failed_at_layer IS NULL OR (failed_at_layer >= 1 AND failed_at_layer <= 7)),
    extraction_result JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_documents_updated_at
    BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE PROCEDURE set_updated_at();

-- 10. document_pages
CREATE TABLE document_pages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    classification TEXT,
    extraction_path TEXT,
    raw_extraction JSONB NOT NULL DEFAULT '{}'::jsonb,
    validated_extraction JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence_scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    validation_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 11. call_records
CREATE TABLE call_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_record_id UUID REFERENCES intake_records(id) ON DELETE SET NULL,
    twilio_call_sid TEXT NOT NULL UNIQUE,
    direction call_direction NOT NULL,
    mode call_mode NOT NULL,
    caller_number TEXT,
    status call_status NOT NULL DEFAULT 'active',
    transcript TEXT,
    extracted_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    duration_seconds INTEGER,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ
);

-- 12. follow_up_actions
CREATE TABLE follow_up_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_record_id UUID NOT NULL REFERENCES intake_records(id) ON DELETE CASCADE,
    type follow_up_type NOT NULL,
    status follow_up_status NOT NULL DEFAULT 'pending',
    target_phone TEXT,
    target_email TEXT,
    message TEXT,
    scheduled_at TIMESTAMPTZ,
    executed_at TIMESTAMPTZ,
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_follow_up_pending_scheduled
    ON follow_up_actions (scheduled_at)
    WHERE status = 'pending';
