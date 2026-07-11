"""OpenAI-compatible chat completions endpoint for ElevenLabs' "Custom LLM"
Conversational AI mode.

ElevenLabs handles STT/TTS/audio; for each turn it POSTs the running message
history here in OpenAI's chat-completions shape, and expects an OpenAI-shaped
response back. This is a thin adapter over the exact same consent/mode/
guardrail/failure-handoff pipeline built for Twilio in backend/voice/ — none
of that logic is duplicated here.

# ponytail: session key falls back to a fixed "default" id if ElevenLabs
# doesn't send a stable conversation identifier in a field we recognize.
# Fine for solo testing (one call at a time); breaks under concurrent calls.
# The first real request gets logged in full below — check the logs and
# adjust _extract_session_id() once we see ElevenLabs' actual request shape.
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, Request

from backend.models.tables import CallStatus
from backend.voice import consent, handler, session, transcripts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm", tags=["llm"])


def _extract_session_id(body: dict, headers: dict) -> str:
    for key in ("conversation_id", "session_id", "user"):
        value = body.get(key)
        if value:
            return str(value)
    for header_name in ("xi-conversation-id", "elevenlabs-conversation-id"):
        value = headers.get(header_name)
        if value:
            return str(value)
    logger.warning(
        "No conversation id found in ElevenLabs request (body keys: %s, headers: %s) "
        "— falling back to a single shared session. Fine for solo testing only.",
        list(body.keys()),
        list(headers.keys()),
    )
    return "default"


def _latest_user_message(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""


@router.post("/chat/completions")
async def chat_completions(request: Request) -> dict:
    body = await request.json()
    logger.info("ElevenLabs custom-LLM request: %s", body)  # first-call diagnostic, keep until verified

    messages = body.get("messages", [])
    caller_text = _latest_user_message(messages)
    call_sid = _extract_session_id(body, dict(request.headers))

    call_session = session.get_or_create(call_sid)

    if not call_session.consent_given:
        if consent.is_negative(caller_text):
            reply_text = "No problem — thank you for calling. Goodbye."
            session.drop(call_sid)
        elif consent.is_affirmative(caller_text):
            call_session.consent_given = True
            reply_text = "Thank you. How can I help you today?"
        else:
            reply_text = consent.CONSENT_QUESTION
    else:
        if call_session.clarification_attempts >= handler.MAX_CLARIFICATION_ATTEMPTS:
            reply_text = handler.FALLBACK_MESSAGE
            await transcripts.save(call_session, status=CallStatus.failed)
            session.drop(call_sid)
        else:
            reply_text = handler.handle_turn(call_session, caller_text)
            call_session.transcript.append({"caller": caller_text, "agent": reply_text})
            await transcripts.save(call_session)

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "intakeai-voice-agent"),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply_text},
                "finish_reason": "stop",
            }
        ],
    }
