# ponytail: thin routes — VoiceAgent owns conversation logic
"""Twilio voice webhook + ConversationRelay WebSocket + text test."""

from __future__ import annotations

import json
import logging
from typing import Any
from xml.sax.saxutils import escape

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from backend.agents.voice_agent import get_voice_agent
from backend.config import get_settings
from backend.models.schemas import VoiceOutboundRequest, VoiceTestRequest, VoiceTestResponse

router = APIRouter(prefix="/voice", tags=["voice"])
logger = logging.getLogger(__name__)


def _conversation_relay_twiml(params: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    host = (
        (settings.ngrok_url or "localhost")
        .strip()
        .removeprefix("https://")
        .removeprefix("http://")
    )
    url = f"wss://{host}/voice/stream"
    param_xml = ""
    if params:
        for k, v in params.items():
            if v is None:
                continue
            val = v if isinstance(v, str) else json.dumps(v)
            param_xml += f'<Parameter name="{escape(str(k))}" value="{escape(val)}" />'
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response><Connect>"
        f'<ConversationRelay url="{url}" '
        'welcomeGreeting="Thank you for calling ABC Home Health. How can I help you today?" '
        'ttsProvider="google" '
        'transcriptionProvider="deepgram">'
        f"{param_xml}"
        "</ConversationRelay>"
        "</Connect></Response>"
    )


@router.post("/inbound")
async def inbound_webhook(request: Request) -> Response:
    return Response(content=_conversation_relay_twiml(), media_type="application/xml")


@router.websocket("/stream")
async def voice_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    agent = get_voice_agent()
    call_sid: str | None = None
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                msg = {"type": "prompt", "voicePrompt": raw}
            event_type = msg.get("type") or msg.get("event")
            if event_type == "setup":
                session = await agent.on_setup(msg)
                call_sid = session.call_sid
                if session.voicemail:
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "text",
                                "token": (
                                    "Hello, this is ABC Home Health calling about a referral. "
                                    "Please call us back or send the requested documentation by fax. "
                                    "Thank you."
                                ),
                                "last": True,
                            }
                        )
                    )
                continue
            if event_type == "interrupt":
                if call_sid:
                    await agent.interrupt(call_sid)
                continue
            if event_type in ("prompt", None) or "voicePrompt" in msg:
                text = (
                    msg.get("voicePrompt")
                    or msg.get("prompt")
                    or msg.get("text")
                    or ""
                )
                last = msg.get("last", True)
                if last is False:
                    continue
                sid = call_sid or msg.get("callSid") or "unknown"
                call_sid = sid
                result = await agent.handle_turn(sid, text)
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "text",
                            "token": result["response"],
                            "last": True,
                        }
                    )
                )
            if event_type == "end":
                break
    except WebSocketDisconnect:
        logger.info("voice stream disconnected")
    finally:
        if call_sid:
            await agent.on_disconnect(call_sid)


@router.post("/test", response_model=VoiceTestResponse)
async def voice_test(body: VoiceTestRequest) -> VoiceTestResponse:
    agent = get_voice_agent()
    if agent.get_session(body.session_id) is None:
        await agent.on_setup({"callSid": body.session_id, "from": "+10000000000"})
    result = await agent.handle_turn(body.session_id, body.message)
    return VoiceTestResponse(
        session_id=body.session_id,
        response=result["response"],
        extracted=result.get("extracted") or {},
        accumulated_data=result.get("accumulated_data") or {},
        ready_for_eligibility=bool(result.get("ready_for_eligibility")),
        eligibility_result=result.get("eligibility_result"),
        guardrail_violations=result.get("guardrail_violations") or [],
        conversation_mode=result.get("conversation_mode"),
    )


@router.post("/outbound")
async def voice_outbound(body: VoiceOutboundRequest) -> dict[str, Any]:
    settings = get_settings()
    params = {
        "mission": body.mission,
        "person_name": body.person_name,
        "role": body.role,
        "facility_name": body.facility_name,
        "patient_name": body.patient_name,
        "known_data": body.known_data,
        "gaps": body.gaps,
        "intake_record_id": str(body.intake_record_id) if body.intake_record_id else None,
        "callback_number": body.callback_number or settings.twilio_phone_number,
    }
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        return {"status": "stubbed", "reason": "missing_twilio_credentials", "params": params}
    try:
        from twilio.rest import Client

        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        call = client.calls.create(
            to=body.to,
            from_=settings.twilio_phone_number,
            twiml=_conversation_relay_twiml(params),
        )
        return {"status": "queued", "sid": call.sid, "mission": body.mission}
    except Exception as exc:
        logger.warning("outbound call failed: %s", exc)
        return {"status": "stubbed", "reason": str(exc), "mission": body.mission}
