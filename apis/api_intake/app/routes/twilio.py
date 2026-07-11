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

import logging
import re
from datetime import datetime
from xml.sax.saxutils import quoteattr

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from app.agents.eligibility_agent import decide, find_plan_in_text
from app.agents.mode_router import (
    CAUTIOUS_DEFAULT_MODE,
    MODE_CLARIFYING_QUESTION,
    MODE_CONFIDENCE_THRESHOLD,
    INBOUND_MODES,
    CallerMode,
    CallModeStore,
    ModeTransition,
    classify_utterance,
    load_mode_prompt,
)
from app.agents.family_intake import (
    CALLBACK_NUMBER_QUESTION,
    FAMILY_CLOSING_WORDING,
    FamilyWrapup,
    create_family_wrapup,
    family_eligibility_wording,
)
from app.agents.provider_intake import (
    PROVIDER_FIELD_QUESTIONS,
    build_eligibility_request,
    extract_diagnosis,
    extract_dob,
    extract_patient_name,
)
from app.config import get_settings
from app.safety.consent import CONSENT_DISCLOSURE, CallRecord, handle_consent_answer
from app.safety.handoff import run_call_turn, trigger_handoff
from app.safety.safe_response import SafeResponse, speak

logger = logging.getLogger(__name__)

router = APIRouter()

GREETING = "Thank you for calling ABC Home Health."
SERVICE_UNAVAILABLE_MESSAGE = (
    "We are unable to take your call right now. Please call back shortly."
)
COORDINATOR_REVIEW_NOTE = "A human coordinator will review this decision."

_ZIP_PATTERN = re.compile(r"\b(\d{5})\b")
_PHONE_PATTERN = re.compile(r"\b(\d{3})[-.\s]?(\d{3})[-.\s]?(\d{4})\b")
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
        # Provider-mode clinical fields (feature 45). Name and DOB are
        # identifiers: backend-only, never part of an eligibility request.
        self.patient_name: str | None = None
        self.patient_dob: str | None = None
        self.diagnosis_code: str | None = None
        self.decision_spoken = False
        self.clarification_attempts = 0
        self.mode: CallerMode | None = None
        self.mode_prompt: str | None = None
        self.mode_clarification_asked = False
        self.turn_count = 0
        self.mode_transitions: list[ModeTransition] = []
        # Family-mode wrap-up state (feature 46).
        self.callback_number: str | None = None
        self.wrapup: FamilyWrapup | None = None


# SMS confirmations queued for sending via Twilio (in-memory for the demo,
# like CallSession). The sender worker drains this outbox.
SMS_OUTBOX: list = []


def _now() -> datetime:
    """Current wall-clock time; tests monkeypatch this for simulated calls."""
    return datetime.now()


def get_mode_store() -> CallModeStore | None:
    """Redis-backed call.mode persistence; None when REDIS_URL is not set.

    Tests monkeypatch this to inject a fake Redis client.
    """
    settings = get_settings()
    if not settings.redis_url:
        return None
    import redis

    return CallModeStore(redis.Redis.from_url(settings.redis_url))


def _set_mode(session: CallSession, mode: CallerMode) -> None:
    session.mode = mode
    session.mode_prompt = load_mode_prompt(mode)
    store = get_mode_store()
    if store is not None:
        store.set_mode(session.record.call_sid, mode)


def _assign_mode(
    session: CallSession, utterance: str, made_progress: bool = False
) -> str | None:
    """Early-turn caller-type detection (WORKFLOW Path A Step 3).

    Runs only after consent (callers reach here through the consent gate).
    Only inbound modes are ever assigned — never OUTBOUND, which is reserved
    for agency-initiated calls carrying a mission parameter.

    Ambiguous / low-confidence handling: the classification confidence is
    recorded on the call record every detection turn. A confident match
    assigns its mode. A low-confidence match keeps the cautious default
    (Family) instead of guessing. A fully ambiguous opening asks ONE neutral
    clarifying question (returned to be spoken); if the caller type is still
    unresolved on the next turn, the cautious default applies. Each
    unresolved turn increments clarification_attempts, so repeated failure
    reaches the human handoff path (guarantee 6) via run_call_turn.
    """
    classification = classify_utterance(utterance)
    session.record = session.record.model_copy(
        update={"mode_confidence": classification.confidence}
    )
    if (
        classification.mode in INBOUND_MODES
        and classification.confidence >= MODE_CONFIDENCE_THRESHOLD
    ):
        _set_mode(session, classification.mode)
        return None
    if made_progress:
        # A data-bearing turn is never interrupted with a clarifying
        # question — the unresolved caller type takes the cautious default.
        _set_mode(session, CAUTIOUS_DEFAULT_MODE)
        return None
    if classification.mode is None and not session.mode_clarification_asked:
        # Ambiguous opening: ask one neutral clarifying question, no guess.
        # This turn bypasses _provider_turn, so it counts its own
        # clarification attempt; every other zero-progress turn is counted
        # by _provider_turn (one increment per turn, never two).
        session.mode_clarification_asked = True
        session.clarification_attempts += 1
        return MODE_CLARIFYING_QUESTION
    # Still unresolved (or resolved only at low confidence): cautious default.
    _set_mode(session, CAUTIOUS_DEFAULT_MODE)
    return None


def _maybe_switch_mode(session: CallSession, utterance: str) -> None:
    """Mid-call mode switch when the caller type becomes clearer (feature 44).

    Re-runs classification on later turns. A confident classification that
    differs from the current mode re-assigns call.mode and swaps the system
    prompt. Collected structured fields live on the session and are untouched
    by the switch. Every transition is recorded with old_mode, new_mode, and
    the triggering turn — on the session, in the app log, and (when Redis is
    configured) in the mode store for dashboard visibility. This runs inside
    run_call_turn's safety boundary, so a switch never bypasses the 4 gates.
    """
    classification = classify_utterance(utterance)
    if (
        classification.mode not in INBOUND_MODES
        or classification.confidence < MODE_CONFIDENCE_THRESHOLD
        or classification.mode is session.mode
    ):
        return
    session.record = session.record.model_copy(
        update={"mode_confidence": classification.confidence}
    )
    transition = ModeTransition(
        old_mode=session.mode,
        new_mode=classification.mode,
        turn=session.turn_count,
    )
    session.mode_transitions.append(transition)
    logger.info(
        "mode switch call_sid=%s old_mode=%s new_mode=%s turn=%d",
        session.record.call_sid,
        transition.old_mode.value,
        transition.new_mode.value,
        transition.turn,
    )
    _set_mode(session, classification.mode)
    store = get_mode_store()
    if store is not None:
        store.log_transition(session.record.call_sid, transition)


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
    # Provider-mode clinical fields (feature 45) — extracted on every turn so
    # volunteered details accumulate in the call state regardless of ordering.
    if session.patient_name is None:
        name = extract_patient_name(utterance)
        if name:
            session.patient_name = name
            progressed = True
    if session.patient_dob is None:
        dob = extract_dob(utterance)
        if dob:
            session.patient_dob = dob
            progressed = True
    if session.diagnosis_code is None:
        diagnosis = extract_diagnosis(utterance)
        if diagnosis:
            session.diagnosis_code = diagnosis
            progressed = True
    return progressed


def _missing_field_question(session: CallSession) -> str:
    if session.patient_zip is None:
        return "What is the patient's zip code?"
    if session.insurance_plan is None:
        return "What insurance does the patient have?"
    return "What type of care was ordered — for example skilled nursing or physical therapy?"


def _eligibility_wording(session: CallSession) -> str:
    # Tokenization boundary (guarantee 2 / feature 45 step 6): the eligibility
    # loop receives only structured non-identifying fields — never name or DOB.
    decision = decide(
        build_eligibility_request(
            patient_zip=session.patient_zip,
            insurance_plan=session.insurance_plan,
            service_type=session.service_type,
            diagnosis_code=session.diagnosis_code,
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


def _post_consent_turn(session: CallSession, utterance: str) -> str:
    """One full post-consent turn: extraction, caller-type detection, reply.

    Runs entirely inside run_call_turn's safety boundary. Caller-type
    detection happens on early turns; an ambiguous, zero-progress opening
    yields the one neutral clarifying question instead of the intake reply.
    """
    session.turn_count += 1
    progressed = _extract_fields(session, utterance)
    if session.mode is None:
        clarifying_question = _assign_mode(session, utterance, made_progress=progressed)
        if clarifying_question is not None:
            return clarifying_question
    else:
        _maybe_switch_mode(session, utterance)
    return _provider_turn(session, progressed)


def _eligibility_ready(session: CallSession) -> bool:
    """Zip + insurance + a service path (stated, or derivable from diagnosis)."""
    return bool(
        session.patient_zip
        and session.insurance_plan
        and (session.service_type or session.diagnosis_code)
    )


def _provider_structured_question(session: CallSession) -> str | None:
    """Next question in the provider-mode structured order (feature 45)."""
    for field, question in PROVIDER_FIELD_QUESTIONS:
        if getattr(session, field) is None:
            return question
    return None


def _provider_turn(session: CallSession, progressed: bool) -> str:
    """Deterministic intake turn. Swap point for the LLM gateway.

    Provider mode (feature 45) runs the structured clinical flow: name, DOB,
    diagnosis, insurance, zip — with the real-time eligibility decision spoken
    mid-call the moment the tokenized fields it needs are complete (Layer 2
    dynamic control). Other modes keep the generic zip/insurance/service flow.
    """
    if _eligibility_ready(session):
        return _eligibility_wording(session)
    if progressed:
        session.clarification_attempts = 0
    else:
        # Only turns with zero extraction progress count as clarifications.
        session.clarification_attempts += 1
    if session.mode is CallerMode.PROVIDER:
        question = _provider_structured_question(session)
        if question is not None:
            return question
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

            # Consent granted: detect caller type on early turns, then run
            # the turn inside the safety boundary.
            result = run_call_turn(
                session.record,
                lambda call: _post_consent_turn(session, utterance),
                clarification_attempts=session.clarification_attempts,
            )
            await _send_text(websocket, result.spoken_text)
            if result.handoff:
                await websocket.send_json({"type": "end"})
                break
    except WebSocketDisconnect:
        return
