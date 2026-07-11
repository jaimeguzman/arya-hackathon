# ponytail: flat service — ceiling: complex merge audit trail; upgrade: event log table
"""Intake record lifecycle: create, get, list, status transitions, JSONB merge."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schemas import IntakeRecordCreate, IntakeRecordUpdate, StatusUpdate
from backend.models.tables import IntakeRecord, IntakeStatus
from backend.services.guardrail_service import GuardrailService

ALLOWED_TRANSITIONS: dict[IntakeStatus, set[IntakeStatus]] = {
    IntakeStatus.new: {
        IntakeStatus.processing,
        IntakeStatus.pending_documents,
        IntakeStatus.escalated,
    },
    IntakeStatus.processing: {
        IntakeStatus.pending_documents,
        IntakeStatus.eligible,
        IntakeStatus.declined,
        IntakeStatus.escalated,
    },
    IntakeStatus.pending_documents: {
        IntakeStatus.processing,
        IntakeStatus.eligible,
        IntakeStatus.declined,
        IntakeStatus.escalated,
    },
    IntakeStatus.eligible: {
        IntakeStatus.accepted,
        IntakeStatus.declined,
        IntakeStatus.escalated,
    },
    IntakeStatus.accepted: set(),
    IntakeStatus.declined: set(),
    IntakeStatus.escalated: {
        IntakeStatus.processing,
        IntakeStatus.eligible,
        IntakeStatus.accepted,
        IntakeStatus.declined,
    },
}

JSONB_FIELDS = (
    "patient_data",
    "clinical_data",
    "physician_data",
    "insurance_data",
    "care_request",
    "referral_source",
    "extraction_confidence",
)


class IntakeService:
    def __init__(self, guardrails: GuardrailService | None = None) -> None:
        self._guardrails = guardrails or GuardrailService()

    async def create(self, session: AsyncSession, body: IntakeRecordCreate) -> IntakeRecord:
        row = IntakeRecord(
            source=body.source,
            urgency=body.urgency,
            patient_data=body.patient_data,
            clinical_data=body.clinical_data,
            physician_data=body.physician_data,
            insurance_data=body.insurance_data,
            care_request=body.care_request,
            referral_source=body.referral_source,
            status=IntakeStatus.new,
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return row

    async def get(self, session: AsyncSession, intake_id: UUID) -> IntakeRecord:
        row = await session.get(IntakeRecord, intake_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Intake record not found")
        return row

    async def list(
        self,
        session: AsyncSession,
        *,
        status: Optional[IntakeStatus] = None,
        since: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[IntakeRecord], int]:
        stmt = select(IntakeRecord)
        if status is not None:
            stmt = stmt.where(IntakeRecord.status == status)
        if since is not None:
            stmt = stmt.where(IntakeRecord.created_at >= since)
        stmt = stmt.order_by(IntakeRecord.created_at.desc()).offset(offset).limit(limit)
        rows = list((await session.execute(stmt)).scalars().all())
        # ponytail: count ≈ len for demo scale
        return rows, len(rows)

    async def update_status(
        self, session: AsyncSession, intake_id: UUID, body: StatusUpdate
    ) -> IntakeRecord:
        row = await self.get(session, intake_id)
        allowed = ALLOWED_TRANSITIONS.get(row.status, set())
        if body.new_status not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot transition from {row.status.value} to {body.new_status.value}",
            )
        row.status = body.new_status
        if body.new_status == IntakeStatus.escalated:
            row.escalated = True
            if body.reason:
                row.escalation_reason = body.reason
        await session.flush()
        await session.refresh(row)
        return row

    async def update_data(
        self, session: AsyncSession, intake_id: UUID, body: IntakeRecordUpdate
    ) -> IntakeRecord:
        row = await self.get(session, intake_id)
        previous = {
            "patient_data": dict(row.patient_data or {}),
            "insurance_data": dict(row.insurance_data or {}),
            "clinical_data": dict(row.clinical_data or {}),
            "care_request": dict(row.care_request or {}),
        }
        data = body.model_dump(exclude_unset=True)
        gaps = list(row.gaps or [])

        for field in JSONB_FIELDS:
            if field not in data or data[field] is None:
                continue
            incoming = data[field]
            existing = getattr(row, field) or {}
            merged, new_gaps = self._merge_jsonb(existing, incoming)
            setattr(row, field, merged)
            gaps.extend(new_gaps)

        if "gaps" in data and data["gaps"] is not None:
            gaps = data["gaps"]
        row.gaps = gaps

        for key in (
            "urgency",
            "eligibility_decision",
            "eligibility_reasons",
            "matched_caregivers",
            "status",
        ):
            if key in data and data[key] is not None:
                setattr(row, key, data[key])

        await session.flush()
        await session.refresh(row)
        # eligibility watcher (Phase 4)
        try:
            from backend.workers.eligibility_watcher import on_intake_updated

            await on_intake_updated(session, row, previous=previous)
            await session.flush()
            await session.refresh(row)
        except Exception:
            pass
        return row

    def _merge_jsonb(
        self, existing: dict[str, Any], incoming: dict[str, Any]
    ) -> tuple[dict[str, Any], list[Any]]:
        out = dict(existing)
        gaps: list[Any] = []
        for key, new_val in incoming.items():
            if key not in out or out[key] in (None, "", {}, []):
                out[key] = new_val
                continue
            if out[key] == new_val:
                continue
            result = self._guardrails.resolve_merge_conflict(key, out[key], new_val)
            action = result["action"]
            if action == "overwrite" and result["winner"] is not None:
                out[key] = result["winner"]
            else:
                gaps.append(result["audit"])
        return out, gaps
