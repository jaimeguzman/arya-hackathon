"""SQLAlchemy 2.0 mapped tables mirroring postgres_init.sql."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, time
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for IntakeAI tables."""


class IntakeStatus(str, enum.Enum):
    new = "new"
    processing = "processing"
    pending_documents = "pending_documents"
    eligible = "eligible"
    accepted = "accepted"
    declined = "declined"
    escalated = "escalated"


class IntakeSource(str, enum.Enum):
    fax = "fax"
    inbound_call_provider = "inbound_call_provider"
    inbound_call_family = "inbound_call_family"
    inbound_call_patient = "inbound_call_patient"
    physician_referral = "physician_referral"
    snf_referral = "snf_referral"


class CaregiverType(str, enum.Enum):
    RN = "RN"
    LPN = "LPN"
    CNA = "CNA"
    PT = "PT"
    OT = "OT"
    ST = "ST"
    HHA = "HHA"


class CaregiverStatus(str, enum.Enum):
    active = "active"
    on_leave = "on_leave"
    suspended = "suspended"
    inactive = "inactive"


class DocumentProcessingStatus(str, enum.Enum):
    uploaded = "uploaded"
    preprocessing = "preprocessing"
    classifying = "classifying"
    extracting = "extracting"
    validating = "validating"
    complete = "complete"
    failed = "failed"


class CallDirection(str, enum.Enum):
    inbound = "inbound"
    outbound = "outbound"


class CallMode(str, enum.Enum):
    provider = "provider"
    family = "family"
    patient = "patient"
    outbound_followup = "outbound_followup"


class CallStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    failed = "failed"
    voicemail = "voicemail"
    no_answer = "no_answer"


class FollowUpType(str, enum.Enum):
    sms_sent = "sms_sent"
    email_sent = "email_sent"
    outbound_call_attempted = "outbound_call_attempted"
    voicemail_left = "voicemail_left"
    callback_scheduled = "callback_scheduled"
    document_received = "document_received"
    document_requested = "document_requested"
    eligibility_recheck = "eligibility_recheck"


class FollowUpStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class IntakeRecord(Base):
    __tablename__ = "intake_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    status: Mapped[IntakeStatus] = mapped_column(
        Enum(IntakeStatus, name="intake_status", create_type=False),
        nullable=False,
        server_default="new",
    )
    source: Mapped[IntakeSource] = mapped_column(
        Enum(IntakeSource, name="intake_source", create_type=False), nullable=False
    )
    urgency: Mapped[str] = mapped_column(Text, nullable=False, server_default="routine")
    patient_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    clinical_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    physician_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    insurance_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    care_request: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    referral_source: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    extraction_confidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    gaps: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    eligibility_decision: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="pending"
    )
    eligibility_reasons: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    matched_caregivers: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    escalated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    escalation_reason: Mapped[Optional[str]] = mapped_column(Text)
    human_review_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Caregiver(Base):
    __tablename__ = "caregivers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[CaregiverType] = mapped_column(
        Enum(CaregiverType, name="caregiver_type", create_type=False), nullable=False
    )
    status: Mapped[CaregiverStatus] = mapped_column(
        Enum(CaregiverStatus, name="caregiver_status", create_type=False),
        nullable=False,
        server_default="active",
    )
    languages: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    current_patient_load: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_patient_capacity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="8")
    phone: Mapped[Optional[str]] = mapped_column(Text)
    email: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    certifications: Mapped[list["CaregiverCertification"]] = relationship(
        back_populates="caregiver", cascade="all, delete-orphan"
    )
    service_areas: Mapped[list["CaregiverServiceArea"]] = relationship(
        back_populates="caregiver", cascade="all, delete-orphan"
    )
    availability: Mapped[list["CaregiverAvailability"]] = relationship(
        back_populates="caregiver", cascade="all, delete-orphan"
    )


class CaregiverCertification(Base):
    __tablename__ = "caregiver_certifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    caregiver_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("caregivers.id", ondelete="CASCADE"), nullable=False
    )
    certification_name: Mapped[str] = mapped_column(Text, nullable=False)
    issued_date: Mapped[Optional[date]] = mapped_column(Date)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date)

    caregiver: Mapped[Caregiver] = relationship(back_populates="certifications")

    @property
    def is_active(self) -> bool:
        """True when cert has no expiry or expiry is today/future."""
        return self.expiry_date is None or self.expiry_date >= date.today()


class CaregiverServiceArea(Base):
    __tablename__ = "caregiver_service_areas"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    caregiver_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("caregivers.id", ondelete="CASCADE"), nullable=False
    )
    zip_code: Mapped[str] = mapped_column(Text, nullable=False)

    caregiver: Mapped[Caregiver] = relationship(back_populates="service_areas")


class CaregiverAvailability(Base):
    __tablename__ = "caregiver_availability"
    __table_args__ = (
        CheckConstraint("day_of_week >= 0 AND day_of_week <= 6", name="ck_day_of_week"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    caregiver_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("caregivers.id", ondelete="CASCADE"), nullable=False
    )
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    caregiver: Mapped[Caregiver] = relationship(back_populates="availability")


class ServiceArea(Base):
    __tablename__ = "service_areas"

    zip_code: Mapped[str] = mapped_column(Text, primary_key=True)
    borough: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class InsuranceContract(Base):
    __tablename__ = "insurance_contracts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    payer_name: Mapped[str] = mapped_column(Text, nullable=False)
    plan_name: Mapped[str] = mapped_column(Text, nullable=False)
    plan_type: Mapped[str] = mapped_column(Text, nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    notes: Mapped[Optional[str]] = mapped_column(Text)


class ReferralSource(Base):
    __tablename__ = "referral_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    facility_name: Mapped[str] = mapped_column(Text, nullable=False)
    facility_type: Mapped[str] = mapped_column(Text, nullable=False)
    contact_name: Mapped[Optional[str]] = mapped_column(Text)
    phone: Mapped[Optional[str]] = mapped_column(Text)
    fax: Mapped[Optional[str]] = mapped_column(Text)
    email: Mapped[Optional[str]] = mapped_column(Text)
    ehr_system: Mapped[Optional[str]] = mapped_column(Text)
    total_referrals: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    accepted_referrals: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    acceptance_rate: Mapped[Optional[float]] = mapped_column(
        Numeric,
        Computed(
            "CASE WHEN total_referrals = 0 THEN NULL "
            "ELSE accepted_referrals::numeric / total_referrals::numeric END",
            persisted=True,
        ),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    intake_record_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intake_records.id", ondelete="SET NULL")
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    page_count: Mapped[Optional[int]] = mapped_column(Integer)
    processing_status: Mapped[DocumentProcessingStatus] = mapped_column(
        Enum(DocumentProcessingStatus, name="document_processing_status", create_type=False),
        nullable=False,
        server_default="uploaded",
    )
    failed_at_layer: Mapped[Optional[int]] = mapped_column(Integer)
    extraction_result: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DocumentPage(Base):
    __tablename__ = "document_pages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    classification: Mapped[Optional[str]] = mapped_column(Text)
    extraction_path: Mapped[Optional[str]] = mapped_column(Text)
    raw_extraction: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    validated_extraction: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    confidence_scores: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    validation_errors: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CallRecord(Base):
    __tablename__ = "call_records"
    __table_args__ = (UniqueConstraint("twilio_call_sid", name="uq_twilio_call_sid"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    intake_record_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intake_records.id", ondelete="SET NULL")
    )
    twilio_call_sid: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[CallDirection] = mapped_column(
        Enum(CallDirection, name="call_direction", create_type=False), nullable=False
    )
    mode: Mapped[CallMode] = mapped_column(
        Enum(CallMode, name="call_mode", create_type=False), nullable=False
    )
    caller_number: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[CallStatus] = mapped_column(
        Enum(CallStatus, name="call_status", create_type=False),
        nullable=False,
        server_default="active",
    )
    transcript: Mapped[Optional[str]] = mapped_column(Text)
    extracted_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class FollowUpAction(Base):
    __tablename__ = "follow_up_actions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    intake_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intake_records.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[FollowUpType] = mapped_column(
        Enum(FollowUpType, name="follow_up_type", create_type=False), nullable=False
    )
    status: Mapped[FollowUpStatus] = mapped_column(
        Enum(FollowUpStatus, name="follow_up_status", create_type=False),
        nullable=False,
        server_default="pending",
    )
    target_phone: Mapped[Optional[str]] = mapped_column(Text)
    target_email: Mapped[Optional[str]] = mapped_column(Text)
    message: Mapped[Optional[str]] = mapped_column(Text)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
