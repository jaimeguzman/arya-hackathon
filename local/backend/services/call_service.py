"""CallRecord persistence — create after mode known; complete on disconnect."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.tables import CallDirection, CallMode, CallRecord, CallStatus


class CallService:
    async def create(
        self,
        session: AsyncSession,
        *,
        twilio_call_sid: str,
        direction: CallDirection,
        mode: CallMode,
        caller_number: str | None = None,
        intake_record_id: UUID | None = None,
    ) -> CallRecord:
        row = CallRecord(
            twilio_call_sid=twilio_call_sid,
            direction=direction,
            mode=mode,
            caller_number=caller_number,
            intake_record_id=intake_record_id,
            status=CallStatus.active,
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return row

    async def complete(
        self,
        session: AsyncSession,
        twilio_call_sid: str,
        *,
        transcript: str | None = None,
        extracted_data: dict[str, Any] | None = None,
        status: CallStatus = CallStatus.completed,
        duration_seconds: int | None = None,
    ) -> CallRecord | None:
        from sqlalchemy import select

        row = (
            await session.execute(
                select(CallRecord).where(CallRecord.twilio_call_sid == twilio_call_sid)
            )
        ).scalars().first()
        if row is None:
            return None
        row.status = status
        if transcript is not None:
            row.transcript = transcript
        if extracted_data is not None:
            row.extracted_data = extracted_data
        if duration_seconds is not None:
            row.duration_seconds = duration_seconds
        row.ended_at = datetime.now(timezone.utc)
        await session.flush()
        await session.refresh(row)
        return row

    async def update_mode(
        self, session: AsyncSession, twilio_call_sid: str, mode: CallMode
    ) -> CallRecord | None:
        from sqlalchemy import select

        row = (
            await session.execute(
                select(CallRecord).where(CallRecord.twilio_call_sid == twilio_call_sid)
            )
        ).scalars().first()
        if row is None:
            return None
        row.mode = mode
        await session.flush()
        return row
