"""Twilio voice entry points.

- POST /twilio/voice: incoming-call webhook. Returns TwiML that connects the
  call to the ConversationRelay WebSocket below.
- WS /twilio/conversation-relay: the safety-gated conversation loop.

Safety-gated flow (must-have.md, enforced here):
consent gather FIRST -> data extraction -> deterministic eligibility ->
banned-phrase filter (SafeResponse) on every spoken response -> any failure
degrades to human handoff (run_call_turn), never a silent drop.

The turn logic below is deterministic extraction (zip / plan / service) so the
full loop works end-to-end without an LLM key. The LLM upgrade path is a drop-in
replacement of `_provider_turn` with a function that calls
`app.safety.llm_gateway.call_llm` — the safety gates stay identical.
"""

import re
from xml.sax.saxutils import quoteattr

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from app.agents.eligibility_agent import EligibilityRequest, decide, find_plan_in_text
from app.config import get_settings
from app.safety.consent import CONSENT_DISCLOSURE, CallRecord, handle_consent_answer
from app.safety.handoff import run_call_turn, trigger_handoff
from app.safety.safe_response import SafeResponse, speak

router = APIRouter()

GREETING = "Thank you for calling ABC Home Health."
SERVICE_UNAVAILABLE_MESSAGE = (
    "We are unable to take your call right now. Please call back shortly."
)
COORDINATOR_REVIEW_NOTE = "A human coordinator will review this decision."

_ZIP_PATTERN = re.compile(r"\b(\d{5})\b")
_YES_PATTERN = re.compile(r"\b(yes|yeah|yep|sure|of course|go ahead|okay|ok)\b", re.IGNORECASE)
_NO_PATTERN = re.compile(r"\b(no|nope|do not|don't)\b", re.IGNORECASE)

# Spoken service phrases -> canonical service types (agency_configuration.json).
_SERVICE_KEYWORDS = {
    "skilled nursing": "skilled_nursing",
    "nurse": "skilled_nursing",
    "nursing": "skilled_nursing",
    "physical therapy": "physical_therapy",
    "occupational therapy": "occupational_therapy",
    "speech": "speech_therapy",
    "home health aide": "home_health_aide",
    "aide": "home_health_aide",
}


class CallSession:
    """Per-call state for the ConversationRelay loop (in-memory for the demo)."""

    def __init__(self, call_sid: str) -> None:
        self.record = CallRecord(call_sid=call_sid)
        self.consent_asked = False
        self.patient_zip: str | None = None
        self.insurance_plan: str | None = None
        self.service_type: str | None = None
        self.decision_spoken = False
        self.clarification_attempts = 0


def _extract_fields(session: CallSession, utterance: str) -> bool:
    """Extract known fields from the utterance. Returns True on any progress."""
    progressed = False
    if session.patient_zip is None:
        zip_match = _ZIP_PATTERN.search(utterance)
        if zip_match:
            session.patient_zip = zip_match.group(1)
            progressed = True
    if session.service_type is None:
        lowered = utterance.lower()
        for phrase, service in _SERVICE_KEYWORDS.items():
            if phrase in lowered:
                session.service_type = service
                progressed = True
                break
    if session.insurance_plan is None:
        plan = find_plan_in_text(utterance)
        if plan:
            session.insurance_plan = plan["plan"]
            progressed = True
    return progressed


def _missing_field_question(session: CallSession) -> str:
    if session.patient_zip is None:
        return "What is the patient's zip code?"
    if session.insurance_plan is None:
        return "What insurance does the patient have?"
    return "What type of care was ordered — for example skilled nursing or physical therapy?"


def _eligibility_wording(session: CallSession) -> str:
    decision = decide(
        EligibilityRequest(
            patient_zip=session.patient_zip,
            insurance_plan=session.insurance_plan,
            service_type=session.service_type,
        )
    )
    session.decision_spoken = True
    if decision.status == "ACCEPT":
        docs = (
            f" We will need the {', and the '.join(decision.required_documentation)} — "
            "you can send those to our fax."
            if decision.required_documentation
            else ""
        )
        return (
            "Good news — we can take this referral. We have a caregiver available "
            f"in that area within 48 hours.{docs} {COORDINATOR_REVIEW_NOTE}"
        )
    if decision.status == "DECLINE":
        return (
            "Unfortunately we are not able to take this referral: "
            f"{'; '.join(decision.reasons)}. Thank you for thinking of us."
        )
    return f"We need a bit more information before we can decide: {'; '.join(decision.reasons)}."


def _provider_turn(session: CallSession, utterance: str) -> str:
    """Deterministic provider-mode turn. Swap point for the LLM gateway."""
    progressed = _extract_fields(session, utterance)
    if session.patient_zip and session.insurance_plan and session.service_type:
        return _eligibility_wording(session)
    if progressed:
        session.clarification_attempts = 0
    else:
        # Only turns with zero extraction progress count as clarifications.
        session.clarification_attempts += 1
    return _missing_field_question(session)


@router.post("/twilio/voice")
def twilio_voice() -> Response:
    """Incoming-call webhook: TwiML connecting the call to ConversationRelay."""
    settings = get_settings()
    if not settings.public_base_url:
        # Degrade gracefully — never a silent failure (guarantee 6).
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"<Response><Say>{SERVICE_UNAVAILABLE_MESSAGE}</Say><Hangup/></Response>"
        )
        return Response(content=twiml, media_type="application/xml")

    ws_base = settings.public_base_url.replace("https://", "wss://").replace(
        "http://", "ws://"
    )
    relay_url = quoteattr(f"{ws_base}/twilio/conversation-relay")
    greeting = quoteattr(GREETING)
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response><Connect>"
        f"<ConversationRelay url={relay_url} welcomeGreeting={greeting}/>"
        "</Connect></Response>"
    )
    return Response(content=twiml, media_type="application/xml")


async def _send_text(websocket: WebSocket, text: str) -> None:
    await websocket.send_json({"type": "text", "token": text, "last": True})


@router.websocket("/twilio/conversation-relay")
async def conversation_relay(websocket: WebSocket) -> None:
    """The safety-gated conversation loop over Twilio ConversationRelay."""
    await websocket.accept()
    session: CallSession | None = None
    try:
        while True:
            message = await websocket.receive_json()
            message_type = message.get("type")

            if message_type == "setup":
                session = CallSession(call_sid=message.get("callSid", "unknown"))
                # Guarantee 4: consent gather is the FIRST node — before any
                # data collection.
                session.consent_asked = True
                await _send_text(websocket, speak(SafeResponse(CONSENT_DISCLOSURE)))
                continue

            if message_type != "prompt" or session is None:
                continue

            utterance = message.get("voicePrompt", "")

            if not session.record.consent_given:
                if _YES_PATTERN.search(utterance):
                    session.record = handle_consent_answer(session.record, answer_is_yes=True)
                    await _send_text(
                        websocket,
                        speak(SafeResponse("Thank you. How can I help you today?")),
                    )
                elif _NO_PATTERN.search(utterance):
                    session.record = handle_consent_answer(session.record, answer_is_yes=False)
                    result = trigger_handoff(session.record, "consent declined")
                    await _send_text(websocket, result.spoken_text)
                    await websocket.send_json({"type": "end"})
                    break
                else:
                    await _send_text(websocket, speak(SafeResponse(CONSENT_DISCLOSURE)))
                continue

            # Consent granted: run the turn inside the safety boundary.
            result = run_call_turn(
                session.record,
                lambda call: _provider_turn(session, utterance),
                clarification_attempts=session.clarification_attempts,
            )
            await _send_text(websocket, result.spoken_text)
            if result.handoff:
                await websocket.send_json({"type": "end"})
                break
    except WebSocketDisconnect:
        return
