# ponytail: voice stubs only — ceiling: no Gemini; upgrade: Phase 5 ConversationRelay handler
"""Twilio voice webhook + WebSocket stubs."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from backend.config import get_settings
from backend.models.schemas import (
    VoiceOutboundRequest,
    VoiceTestRequest,
    VoiceTestResponse,
)

router = APIRouter(prefix="/voice", tags=["voice"])
logger = logging.getLogger(__name__)

# ponytail: in-memory test sessions — ceiling: lost on restart; upgrade: Redis
_TEST_SESSIONS: dict[str, list[dict[str, str]]] = {}


def _conversation_relay_twiml() -> str:
    settings = get_settings()
    host = (settings.ngrok_url or "localhost").strip().removeprefix("https://").removeprefix("http://")
    url = f"wss://{host}/voice/stream"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response><Connect>"
        f'<ConversationRelay url="{url}" '
        'welcomeGreeting="Thank you for calling ABC Home Health. How can I help you today?" '
        'ttsProvider="google" '
        'transcriptionProvider="deepgram" />'
        "</Connect></Response>"
    )


@router.post("/inbound")
async def inbound_webhook(request: Request) -> Response:
    return Response(content=_conversation_relay_twiml(), media_type="application/xml")


@router.websocket("/stream")
async def voice_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                msg = {"type": "prompt"}
            event_type = msg.get("type") or msg.get("event")
            if event_type in ("prompt", "setup", None) or "voicePrompt" in msg:
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "text",
                            "token": (
                                "Thank you for calling. Our system is currently being set up. "
                                "Please call back shortly."
                            ),
                            "last": True,
                        }
                    )
                )
            if event_type == "end":
                break
    except WebSocketDisconnect:
        logger.info("voice stream disconnected")


@router.post("/test", response_model=VoiceTestResponse)
async def voice_test(body: VoiceTestRequest) -> VoiceTestResponse:
    history = _TEST_SESSIONS.setdefault(body.session_id, [])
    history.append({"role": "user", "content": body.message})
    reply = (
        "Thank you for calling. Our system is currently being set up. Please call back shortly."
    )
    history.append({"role": "assistant", "content": reply})
    return VoiceTestResponse(session_id=body.session_id, reply=reply)


@router.post("/outbound")
async def voice_outbound(body: VoiceOutboundRequest) -> dict[str, Any]:
    settings = get_settings()
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        return {"status": "stubbed", "reason": "missing_twilio_credentials", "mission": body.mission}
    try:
        from twilio.rest import Client

        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        call = client.calls.create(
            to=body.to,
            from_=settings.twilio_phone_number,
            twiml=_conversation_relay_twiml(),
        )
        return {"status": "queued", "sid": call.sid, "mission": body.mission}
    except Exception as exc:
        logger.warning("outbound call failed: %s", exc)
        return {"status": "stubbed", "reason": str(exc), "mission": body.mission}
