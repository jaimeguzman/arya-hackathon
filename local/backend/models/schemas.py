"""Pydantic request/response schemas for Phase 3 APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.models.tables import (
    CallDirection,
    CallMode,
    CallStatus,
    DocumentProcessingStatus,
    FollowUpStatus,
    FollowUpType,
    IntakeSource,
    IntakeStatus,
)


class ErrorResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None


class StatusUpdate(BaseModel):
    new_status: IntakeStatus
    reason: Optional[str] = None


# --- Intake ---


class IntakeRecordCreate(BaseModel):
    source: IntakeSource
    urgency: str = "routine"
    patient_data: dict[str, Any] = Field(default_factory=dict)
    clinical_data: dict[str, Any] = Field(default_factory=dict)
    physician_data: dict[str, Any] = Field(default_factory=dict)
    insurance_data: dict[str, Any] = Field(default_factory=dict)
    care_request: dict[str, Any] = Field(default_factory=dict)
    referral_source: dict[str, Any] = Field(default_factory=dict)


class IntakeRecordUpdate(BaseModel):
    urgency: Optional[str] = None
    patient_data: Optional[dict[str, Any]] = None
    clinical_data: Optional[dict[str, Any]] = None
    physician_data: Optional[dict[str, Any]] = None
    insurance_data: Optional[dict[str, Any]] = None
    care_request: Optional[dict[str, Any]] = None
    referral_source: Optional[dict[str, Any]] = None
    extraction_confidence: Optional[dict[str, Any]] = None
    gaps: Optional[list[Any]] = None
    eligibility_decision: Optional[str] = None
    eligibility_reasons: Optional[list[Any]] = None
    matched_caregivers: Optional[list[Any]] = None
    status: Optional[IntakeStatus] = None


class IntakeRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: IntakeStatus
    source: IntakeSource
    urgency: str
    patient_data: dict[str, Any]
    clinical_data: dict[str, Any]
    physician_data: dict[str, Any]
    insurance_data: dict[str, Any]
    care_request: dict[str, Any]
    referral_source: dict[str, Any]
    extraction_confidence: dict[str, Any]
    gaps: list[Any]
    eligibility_decision: str
    eligibility_reasons: list[Any]
    matched_caregivers: list[Any]
    escalated: bool
    escalation_reason: Optional[str] = None
    human_review_required: bool
    created_at: datetime
    updated_at: datetime


class IntakeRecordList(BaseModel):
    items: list[IntakeRecordResponse]
    count: int


# --- Eligibility ---


class EligibilityCheckRequest(BaseModel):
    icd_code: Optional[str] = None
    diagnosis_text: Optional[str] = None
    insurance_payer: str
    insurance_plan: Optional[str] = None
    zip_code: str
    service_types_needed: Optional[list[str]] = None
    intake_record_id: Optional[UUID] = None
    persist: bool = False


class EligibilityReason(BaseModel):
    code: str
    message: str


class CoverageDetail(BaseModel):
    service_type: str
    prior_auth_required: bool = False
    required_docs: list[str] = Field(default_factory=list)
    visit_limit: Optional[int] = None
    episode_days: Optional[int] = None


class CaregiverMatchItem(BaseModel):
    id: UUID
    name: str
    type: str
    certifications: list[str] = Field(default_factory=list)
    zip_codes: list[str] = Field(default_factory=list)
    current_load: int
    max_capacity: int
    match_score: float
    reasons: list[str] = Field(default_factory=list)


class EligibilityCheckResponse(BaseModel):
    decision: str  # ACCEPT | DECLINE | NEEDS_MORE_INFO
    reasons: list[EligibilityReason]
    matched_caregivers: list[CaregiverMatchItem]
    coverage_details: list[CoverageDetail]
    missing_documents: list[str]
    confidence_score: float
    voice_guidance: str  # CONFIRM | HEDGE | DEFER


class ServiceAreaItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    zip_code: str
    borough: str
    active: bool


class InsuranceContractItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    payer_name: str
    plan_name: str
    plan_type: str
    accepted: bool
    notes: Optional[str] = None


# --- Caregivers ---


class CaregiverMatchRequest(BaseModel):
    certification_types: list[str]
    zip_code: str
    day_of_week: Optional[int] = None
    time: Optional[str] = None  # HH:MM
    language: Optional[str] = None


class CaregiverMatchResponse(BaseModel):
    caregivers: list[CaregiverMatchItem]
    count: int


class CaregiverDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    type: str
    status: str
    languages: list[str]
    current_patient_load: int
    max_patient_capacity: int
    phone: Optional[str] = None
    email: Optional[str] = None
    certifications: list[dict[str, Any]] = Field(default_factory=list)
    service_areas: list[str] = Field(default_factory=list)
    availability: list[dict[str, Any]] = Field(default_factory=list)


class CaregiverListResponse(BaseModel):
    items: list[CaregiverDetailResponse]
    count: int


# --- Documents ---


class DocumentUploadResponse(BaseModel):
    id: UUID
    file_name: str
    page_count: Optional[int] = None
    processing_status: DocumentProcessingStatus


class DocumentStatusResponse(BaseModel):
    id: UUID
    status: DocumentProcessingStatus
    current_layer: Optional[int] = None
    extraction_result: dict[str, Any] = Field(default_factory=dict)
    confidence_scores: dict[str, Any] = Field(default_factory=dict)
    gaps: list[Any] = Field(default_factory=list)


class DocumentPageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    page_number: int
    classification: Optional[str] = None
    extraction_path: Optional[str] = None
    raw_extraction: dict[str, Any]
    validated_extraction: dict[str, Any]
    confidence_scores: dict[str, Any]
    validation_errors: list[Any]


class DocumentExtractionResponse(BaseModel):
    id: UUID
    processing_status: DocumentProcessingStatus
    extraction_result: dict[str, Any]
    pages: list[DocumentPageResponse]


# --- Calls (schema-only) ---


class CallRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    twilio_call_sid: str
    direction: CallDirection
    mode: CallMode
    caller_number: Optional[str] = None
    status: CallStatus
    transcript: Optional[str] = None
    extracted_data: dict[str, Any]
    duration_seconds: Optional[int] = None
    started_at: datetime
    ended_at: Optional[datetime] = None


# --- Follow-up ---


class FollowUpActionCreate(BaseModel):
    intake_record_id: UUID
    type: FollowUpType
    target_phone: Optional[str] = None
    target_email: Optional[str] = None
    message: Optional[str] = None
    scheduled_at: Optional[datetime] = None


class FollowUpActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    intake_record_id: UUID
    type: FollowUpType
    status: FollowUpStatus
    target_phone: Optional[str] = None
    target_email: Optional[str] = None
    message: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    result: dict[str, Any]
    attempt_number: int
    created_at: datetime


class FollowUpStatusUpdate(BaseModel):
    status: FollowUpStatus
    result: Optional[dict[str, Any]] = None


# --- Voice ---


class VoiceTestRequest(BaseModel):
    session_id: str
    message: str


class VoiceTestResponse(BaseModel):
    session_id: str
    response: str
    extracted: dict[str, Any] = Field(default_factory=dict)
    accumulated_data: dict[str, Any] = Field(default_factory=dict)
    ready_for_eligibility: bool = False
    eligibility_result: Optional[dict[str, Any]] = None
    guardrail_violations: list[Any] = Field(default_factory=list)
    conversation_mode: Optional[str] = None


class VoiceOutboundRequest(BaseModel):
    to: str
    mission: str
    person_name: Optional[str] = None
    role: Optional[str] = None
    facility_name: Optional[str] = None
    patient_name: Optional[str] = None
    known_data: Optional[dict[str, Any]] = None
    gaps: Optional[list[Any]] = None
    intake_record_id: Optional[UUID] = None
    callback_number: Optional[str] = None
