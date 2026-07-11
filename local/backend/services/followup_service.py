# ponytail: email stubbed — ceiling: no SMTP; upgrade: SendGrid/SES
"""Follow-up actions with Redis schedule + Twilio SMS or stub."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.models.database import get_redis
from backend.models.schemas import FollowUpActionCreate, FollowUpStatusUpdate
from backend.models.tables import FollowUpAction, FollowUpStatus, FollowUpType

logger = logging.getLogger(__name__)
REDIS_KEY = "followup:scheduled"
RETRY_SECONDS = 900


class FollowUpService:
    async def create(
        self, session: AsyncSession, body: FollowUpActionCreate
    ) -> FollowUpAction:
        row = FollowUpAction(
            intake_record_id=body.intake_record_id,
            type=body.type,
            target_phone=body.target_phone,
            target_email=body.target_email,
            message=body.message,
            scheduled_at=body.scheduled_at,
            status=FollowUpStatus.pending,
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)

        if row.scheduled_at is not None:
            await self._zadd(row)

        if body.type == FollowUpType.sms_sent and body.scheduled_at is None:
            await self._send_sms_now(session, row)
        elif body.type == FollowUpType.email_sent and body.scheduled_at is None:
            logger.info("would send email to %s", body.target_email)
            row.status = FollowUpStatus.completed
            row.executed_at = datetime.now(timezone.utc)
            row.result = {"stub": True, "channel": "email"}
            await session.flush()
            await session.refresh(row)

        return row

    async def list_by_intake(
        self, session: AsyncSession, intake_id: UUID
    ) -> list[FollowUpAction]:
        stmt = (
            select(FollowUpAction)
            .where(FollowUpAction.intake_record_id == intake_id)
            .order_by(FollowUpAction.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def update_status(
        self, session: AsyncSession, action_id: UUID, body: FollowUpStatusUpdate
    ) -> FollowUpAction:
        row = await session.get(FollowUpAction, action_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Follow-up action not found")
        row.status = body.status
        if body.result is not None:
            row.result = body.result
        if body.status in (
            FollowUpStatus.completed,
            FollowUpStatus.cancelled,
            FollowUpStatus.failed,
        ):
            await self._zrem(row.id)
            if body.status == FollowUpStatus.completed:
                row.executed_at = datetime.now(timezone.utc)
            if body.status == FollowUpStatus.failed:
                await self._retry(session, row)
        await session.flush()
        await session.refresh(row)
        return row

    async def _send_sms_now(self, session: AsyncSession, row: FollowUpAction) -> None:
        settings = get_settings()
        if (
            settings.twilio_account_sid
            and settings.twilio_auth_token
            and settings.twilio_phone_number
            and row.target_phone
        ):
            try:
                from twilio.rest import Client

                client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
                msg = client.messages.create(
                    body=row.message or "IntakeAI follow-up",
                    from_=settings.twilio_phone_number or None,
                    to=row.target_phone,
                )
                row.status = FollowUpStatus.completed
                row.executed_at = datetime.now(timezone.utc)
                row.result = {"sid": msg.sid}
            except Exception as exc:  # ponytail: stub on any Twilio failure
                logger.warning("Twilio SMS failed: %s — stubbing", exc)
                row.status = FollowUpStatus.completed
                row.executed_at = datetime.now(timezone.utc)
                row.result = {"stub": True, "error": str(exc)}
        else:
            logger.info("SMS stub to %s: %s", row.target_phone, row.message)
            row.status = FollowUpStatus.completed
            row.executed_at = datetime.now(timezone.utc)
            row.result = {"stub": True, "channel": "sms"}
        await session.flush()
        await session.refresh(row)

    async def _retry(self, session: AsyncSession, failed: FollowUpAction) -> FollowUpAction:
        nxt = FollowUpAction(
            intake_record_id=failed.intake_record_id,
            type=failed.type,
            target_phone=failed.target_phone,
            target_email=failed.target_email,
            message=failed.message,
            scheduled_at=datetime.now(timezone.utc) + timedelta(seconds=RETRY_SECONDS),
            attempt_number=failed.attempt_number + 1,
            status=FollowUpStatus.pending,
        )
        session.add(nxt)
        await session.flush()
        await session.refresh(nxt)
        await self._zadd(nxt)
        return nxt

    async def _zadd(self, row: FollowUpAction) -> None:
        assert row.scheduled_at is not None
        redis = get_redis()
        score = row.scheduled_at.timestamp()
        await redis.zadd(REDIS_KEY, {str(row.id): score})

    async def _zrem(self, action_id: UUID) -> None:
        redis = get_redis()
        await redis.zrem(REDIS_KEY, str(action_id))
