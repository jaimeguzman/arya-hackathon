# ponytail: 30s poll — ceiling: up to 30s late; upgrade: keyspace notifications
"""Follow-up scheduler — poll Redis ZSET every 30 seconds."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from backend.models.database import get_redis, get_sessionmaker
from backend.models.tables import FollowUpAction, FollowUpStatus, FollowUpType
from backend.services.followup_service import REDIS_KEY, FollowUpService

logger = logging.getLogger(__name__)
POLL_SECONDS = 30

RETRY_DELAY = {
    FollowUpType.outbound_call_attempted: timedelta(hours=2),
    FollowUpType.sms_sent: timedelta(hours=4),
    FollowUpType.email_sent: timedelta(hours=24),
    FollowUpType.eligibility_recheck: timedelta(hours=2),
}


class FollowUpScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._svc = FollowUpService()

    def start(self) -> None:
        if self._task is None:
            self._stop = asyncio.Event()
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, RuntimeError):
                pass
            self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:
                logger.exception("followup scheduler tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=POLL_SECONDS)
            except asyncio.TimeoutError:
                pass

    async def tick(self) -> None:
        redis = get_redis()
        now = datetime.now(timezone.utc).timestamp()
        due = await redis.zrangebyscore(REDIS_KEY, "-inf", now)
        if not due:
            return
        Session = get_sessionmaker()
        async with Session() as session:
            for member in due:
                action_id = UUID(member if isinstance(member, str) else member.decode())
                row = await session.get(FollowUpAction, action_id)
                await redis.zrem(REDIS_KEY, member)
                if row is None:
                    continue
                try:
                    await self._execute(session, row)
                except Exception as exc:
                    logger.exception("followup %s failed: %s", action_id, exc)
                    await self._fail(session, row)
            await session.commit()

    async def _execute(self, session, row: FollowUpAction) -> None:
        if row.type == FollowUpType.sms_sent:
            await self._svc._send_sms_now(session, row)
        elif row.type == FollowUpType.email_sent:
            logger.info("would send email to %s", row.target_email)
            row.status = FollowUpStatus.completed
            row.executed_at = datetime.now(timezone.utc)
            row.result = {"stub": True, "channel": "email"}
        elif row.type == FollowUpType.eligibility_recheck:
            row.status = FollowUpStatus.completed
            row.executed_at = datetime.now(timezone.utc)
            row.result = {"channel": "eligibility_recheck"}
            try:
                from backend.agents.orchestrator import get_orchestrator

                await get_orchestrator().resume(
                    row.intake_record_id, event="eligibility_recheck"
                )
            except Exception:
                logger.exception("orchestrator eligibility_recheck resume failed")
        elif row.type == FollowUpType.outbound_call_attempted:
            row.executed_at = datetime.now(timezone.utc)
            if not row.target_phone:
                row.status = FollowUpStatus.failed
                row.result = {"error": "missing_target_phone"}
                await self._fail(session, row)
                return
            try:
                from backend.api.voice import voice_outbound
                from backend.models.schemas import VoiceOutboundRequest

                result = await voice_outbound(
                    VoiceOutboundRequest(
                        to=row.target_phone,
                        mission=row.message or "follow-up",
                        intake_record_id=row.intake_record_id,
                    )
                )
                row.status = FollowUpStatus.completed
                row.result = result if isinstance(result, dict) else {"result": result}
            except Exception as exc:
                logger.exception("outbound dial failed")
                row.status = FollowUpStatus.failed
                row.result = {"error": str(exc)}
                await self._fail(session, row)
                return
        else:
            logger.warning("unknown followup type %s", row.type)
            row.status = FollowUpStatus.failed
            row.result = {"error": "unknown_type"}
            await self._fail(session, row)
            return
        await session.flush()

    async def _fail(self, session, row: FollowUpAction) -> None:
        row.status = FollowUpStatus.failed
        if row.attempt_number >= 3:
            logger.info("followup_permanent_failure %s", row.id)
            await session.flush()
            return
        delay = RETRY_DELAY.get(row.type, timedelta(hours=4))
        nxt = FollowUpAction(
            intake_record_id=row.intake_record_id,
            type=row.type,
            target_phone=row.target_phone,
            target_email=row.target_email,
            message=row.message,
            scheduled_at=datetime.now(timezone.utc) + delay,
            attempt_number=row.attempt_number + 1,
            status=FollowUpStatus.pending,
        )
        session.add(nxt)
        await session.flush()
        redis = get_redis()
        await redis.zadd(REDIS_KEY, {str(nxt.id): nxt.scheduled_at.timestamp()})


_scheduler = FollowUpScheduler()


def get_scheduler() -> FollowUpScheduler:
    return _scheduler
