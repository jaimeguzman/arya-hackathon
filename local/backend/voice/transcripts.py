"""Persist call transcripts and outcomes to the call_records table.

Task 1 Step 6. Called after every turn so a mid-call crash doesn't lose the
transcript, and once more on call end to record final status/duration.

# ponytail: a call that ends via consent decline is never persisted, because
# `mode` is a NOT NULL column and mode isn't known until after consent. If
# logging declined-consent calls turns out to matter for the demo, that's a
# schema change (nullable mode) — flagging for whoever owns local/backend/db,
# not changing it here since this task doesn't own the schema.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from backend.models.database import get_sessionmaker
from backend.models.tables import CallDirection, CallMode, CallRecord, CallStatus
from backend.voice.session import CallSession

logger = logging.getLogger(__name__)

_MODE_MAP = {
    "provider": CallMode.provider,
    "family": CallMode.family,
    "outbound": CallMode.outbound_followup,
}


async def save(session: CallSession, *, status: CallStatus = CallStatus.active) -> None:
    """Upsert the CallRecord for this session. No-op until a mode is known.

    Never lets a persistence failure reach the caller — logging the
    transcript is a nice-to-have next to must-have.md #6 (no silent call
    drop). A database outage degrades to "this turn wasn't saved," not
    "the caller gets nothing." Every route call site can call this
    unconditionally without its own try/except.
    """
    if session.mode is None:
        return

    try:
        async with get_sessionmaker()() as db:
            result = await db.execute(
                select(CallRecord).where(CallRecord.twilio_call_sid == session.call_sid)
            )
            record = result.scalar_one_or_none()

            if record is None:
                record = CallRecord(
                    twilio_call_sid=session.call_sid,
                    direction=CallDirection.inbound,
                    mode=_MODE_MAP[session.mode],
                    caller_number=session.caller_number,
                    status=status,
                    started_at=session.started_at,
                )
                db.add(record)
            else:
                record.mode = _MODE_MAP[session.mode]
                record.status = status

            record.transcript = json.dumps(session.transcript)
            record.extracted_data = dict(session.known_fields)

            if status in (CallStatus.completed, CallStatus.failed):
                ended_at = datetime.now(timezone.utc)
                record.ended_at = ended_at
                record.duration_seconds = int((ended_at - session.started_at).total_seconds())

            await db.commit()
            logger.info("call %s: transcript saved (status=%s)", session.call_sid, status.value)
    except Exception:
        logger.exception(
            "call %s: transcript persistence failed (status=%s) — continuing without it",
            session.call_sid,
            status.value,
        )
