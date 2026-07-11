"""Guarantee 6: no silent call drop — every failure degrades to human handoff.

Every call turn runs inside run_call_turn(): any exception, timeout, or a
clarification_attempts counter crossing its threshold routes to the same
handoff path as a consent 'no' — a spoken fallback plus a logged handoff.
"""

import logging
from collections.abc import Callable

from app.safety.consent import CallRecord
from app.safety.safe_response import SafeResponse, speak

logger = logging.getLogger("intakeai.safety.handoff")

HANDOFF_FALLBACK_MESSAGE = "Let me connect you with a coordinator who can help you further."
CLARIFICATION_ATTEMPTS_THRESHOLD = 3


class TurnResult:
    __slots__ = ("spoken_text", "handoff")

    def __init__(self, spoken_text: str, handoff: bool) -> None:
        self.spoken_text = spoken_text
        self.handoff = handoff


def trigger_handoff(call: CallRecord, reason: str) -> TurnResult:
    """Speak the fallback and log the handoff (transfer or scheduled callback)."""
    logger.warning(
        "safety.handoff.triggered",
        extra={"call_sid": call.call_sid, "reason": reason},
    )
    return TurnResult(spoken_text=speak(SafeResponse(HANDOFF_FALLBACK_MESSAGE)), handoff=True)


def run_call_turn(
    call: CallRecord,
    turn: Callable[[CallRecord], str],
    clarification_attempts: int = 0,
) -> TurnResult:
    """Try/except boundary around every call turn."""
    if clarification_attempts >= CLARIFICATION_ATTEMPTS_THRESHOLD:
        return trigger_handoff(call, "clarification_attempts threshold reached")
    try:
        draft = turn(call)
    except Exception as exc:  # noqa: BLE001 — every failure must degrade to handoff
        return trigger_handoff(call, f"turn error: {type(exc).__name__}")
    return TurnResult(spoken_text=speak(SafeResponse(draft)), handoff=False)
