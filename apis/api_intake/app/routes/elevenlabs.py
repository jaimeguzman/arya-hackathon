"""ElevenLabs Agents voice transport (Custom LLM pattern).

The ElevenLabs agent is configured with:
- first message = CONSENT_DISCLOSURE (guarantee 4; re-enforced server-side below),
- Custom LLM base URL = {PUBLIC_BASE_URL}/elevenlabs/custom-llm with a Bearer token,
- "Custom LLM extra body" enabled so conversation_id arrives on every turn,
- the end_call system tool (terminates the call after a handoff reply),
- post-call webhook = {PUBLIC_BASE_URL}/elevenlabs/webhooks/post-call (HMAC-signed).

Every conversation turn hits POST /elevenlabs/custom-llm/v1/chat/completions
(OpenAI-compatible) and runs through the exact same safety-gated turn logic as
the ConversationRelay handler: consent gate first, then run_call_turn() around
_post_consent_turn(). Barge-in/interrupts are handled by ElevenLabs itself and
never reach this endpoint. See docs/ELEVENLABS_MIGRATION.md.
"""

import hashlib
import hmac
import json
import time
from collections.abc import Iterator

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.routes.twilio import _NO_PATTERN, _YES_PATTERN, CallSession, _post_consent_turn
from app.safety.consent import CONSENT_DISCLOSURE, handle_consent_answer
from app.safety.handoff import run_call_turn, trigger_handoff
from app.safety.safe_response import SafeResponse, speak

router = APIRouter(prefix="/elevenlabs")

# Per-conversation state, keyed by the ElevenLabs conversation id (in-memory
# for the demo, mirroring the ConversationRelay handler's approach).
SESSIONS: dict[str, CallSession] = {}

CONSENT_GREETING = "Thank you. How can I help you today?"
SIGNATURE_MAX_AGE_SECONDS = 30 * 60
COMPLETION_MODEL_NAME = "intakeai-safety-gated"


def _require_bearer(authorization: str | None) -> None:
    """Fail closed: reject when the token is unconfigured or does not match."""
    expected = get_settings().elevenlabs_custom_llm_token
    provided = ""
    if authorization and authorization.startswith("Bearer "):
        provided = authorization.removeprefix("Bearer ")
    if not expected or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="invalid bearer token")


def verify_elevenlabs_signature(
    raw_body: bytes, signature_header: str, secret: str, *, now: int | None = None
) -> bool:
    """Validate the ElevenLabs-Signature header: 't=<ts>,v0=<hmac-sha256 hex>'.

    The signed payload is '{timestamp}.{raw_body}'. Stale timestamps are
    rejected to block replay.
    """
    parts = dict(
        part.split("=", 1) for part in signature_header.split(",") if "=" in part
    )
    timestamp, signature = parts.get("t"), parts.get("v0")
    if not timestamp or not signature or not timestamp.isdigit():
        return False
    current = int(time.time()) if now is None else now
    if abs(current - int(timestamp)) > SIGNATURE_MAX_AGE_SECONDS:
        return False
    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _conversation_id(body: dict) -> str:
    extra = body.get("elevenlabs_extra_body") or {}
    conversation_id = extra.get("conversation_id") or body.get("user")
    if not conversation_id:
        raise HTTPException(
            status_code=400,
            detail="missing conversation id (elevenlabs_extra_body.conversation_id or user)",
        )
    return str(conversation_id)


def _last_user_message(body: dict) -> str:
    for message in reversed(body.get("messages") or []):
        if message.get("role") == "user":
            return message.get("content") or ""
    return ""


def _run_turn(session: CallSession, utterance: str) -> tuple[str, bool]:
    """One safety-gated turn; returns (spoken_text, call_ended).

    Mirrors the ConversationRelay loop: the ElevenLabs agent speaks
    CONSENT_DISCLOSURE as its configured first message, and this gate
    re-enforces it server-side — no data collection before an explicit yes.
    """
    session.consent_asked = True
    if not session.record.consent_given:
        if _YES_PATTERN.search(utterance):
            session.record = handle_consent_answer(session.record, answer_is_yes=True)
            return speak(SafeResponse(CONSENT_GREETING)), False
        if _NO_PATTERN.search(utterance):
            session.record = handle_consent_answer(session.record, answer_is_yes=False)
            result = trigger_handoff(session.record, "consent declined")
            return result.spoken_text, True
        return speak(SafeResponse(CONSENT_DISCLOSURE)), False
    result = run_call_turn(
        session.record,
        lambda call: _post_consent_turn(session, utterance),
        clarification_attempts=session.clarification_attempts,
    )
    return result.spoken_text, result.handoff


def _completion_json(text: str, conversation_id: str, turn: int) -> dict:
    return {
        "id": f"chatcmpl-{conversation_id}-{turn}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": COMPLETION_MODEL_NAME,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
    }


def _sse_single_chunk(text: str, conversation_id: str, turn: int) -> Iterator[str]:
    chunk = {
        "id": f"chatcmpl-{conversation_id}-{turn}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": COMPLETION_MODEL_NAME,
        "choices": [
            {"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}
        ],
    }
    finish = {
        "id": chunk["id"],
        "object": "chat.completion.chunk",
        "created": chunk["created"],
        "model": COMPLETION_MODEL_NAME,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(chunk)}\n\n"
    yield f"data: {json.dumps(finish)}\n\n"
    yield "data: [DONE]\n\n"


@router.post("/custom-llm/v1/chat/completions")
async def custom_llm_completions(
    request: Request, authorization: str | None = Header(default=None)
):
    _require_bearer(authorization)
    body = await request.json()
    conversation_id = _conversation_id(body)
    utterance = _last_user_message(body)
    session = SESSIONS.setdefault(conversation_id, CallSession(call_sid=conversation_id))
    text, ended = _run_turn(session, utterance)
    turn = session.turn_count
    if ended:
        SESSIONS.pop(conversation_id, None)
    if body.get("stream"):
        return StreamingResponse(
            _sse_single_chunk(text, conversation_id, turn),
            media_type="text/event-stream",
        )
    return _completion_json(text, conversation_id, turn)


@router.post("/webhooks/post-call")
async def post_call_webhook(
    request: Request,
    elevenlabs_signature: str | None = Header(default=None, alias="ElevenLabs-Signature"),
) -> dict:
    """HMAC-validated post-call webhook (transcript/analysis ingestion)."""
    secret = get_settings().elevenlabs_webhook_secret
    raw_body = await request.body()
    if (
        not secret
        or not elevenlabs_signature
        or not verify_elevenlabs_signature(raw_body, elevenlabs_signature, secret)
    ):
        raise HTTPException(status_code=403, detail="invalid webhook signature")
    return {"ok": True}
