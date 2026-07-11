"""Per-turn conversation orchestration + must-have.md #6 failure-handoff wrapper.

handle_turn() is the single entry point the WebSocket route calls for every
post-consent turn. It never lets an exception escape — any failure, or too
many consecutive misunderstandings, routes to the same handoff message a
consent "no" would get. No call path is allowed to end in silence.
"""

from __future__ import annotations

import json
import logging

from backend.voice import guardrails, prompts
from backend.voice.session import CallSession

logger = logging.getLogger(__name__)

FALLBACK_MESSAGE = (
    "I'm having trouble processing that. Let me connect you with a coordinator "
    "who can help right now."
)
MAX_CLARIFICATION_ATTEMPTS = 2

_MODE_PROMPTS = {
    "provider": prompts.PROVIDER_SYSTEM_PROMPT,
    "family": prompts.FAMILY_SYSTEM_PROMPT,
    "outbound": prompts.OUTBOUND_SYSTEM_PROMPT,
}

_PROVIDER_WORDS = {"discharge", "planner", "physician", "referral", "hospital", "nurse", "snf", "doctor"}


def detect_mode(first_utterance: str) -> str:
    """Deterministic keyword classification — a binary-ish choice, no LLM call needed."""
    normalized = first_utterance.lower()
    if any(word in normalized for word in _PROVIDER_WORDS):
        return "provider"
    # ponytail: default to the gentler mode when ambiguous — never assume
    # clinical fluency the caller might not have. Upgrade: LLM-based
    # classification with caller_identification confidence if this proves
    # too coarse during real testing.
    return "family"


def handle_turn(session: CallSession, caller_text: str) -> str:
    try:
        if session.mode is None:
            session.mode = detect_mode(caller_text)
            logger.info("call %s detected mode=%s", session.call_sid, session.mode)

        system_prompt = _MODE_PROMPTS[session.mode]
        tokenized = guardrails.tokenize(caller_text, session.known_fields)
        contents = _build_contents(session, tokenized)
        raw_reply = guardrails.call_llm(contents, system_prompt)

        parsed = _parse_llm_json(raw_reply)
        session.known_fields.update(parsed.get("extracted", {}))
        rehydrated = guardrails.rehydrate(parsed.get("say", raw_reply), session.known_fields)

        safe = guardrails.SafeResponse(rehydrated)
        session.clarification_attempts = 0
        return guardrails.speak(safe)

    except Exception:
        logger.exception("call %s: turn failed, routing to failure handoff", session.call_sid)
        session.clarification_attempts += 1
        return _failure_handoff(session)


def _failure_handoff(session: CallSession) -> str:
    logger.warning(
        "call %s: failure handoff triggered (attempt %d)",
        session.call_sid,
        session.clarification_attempts,
    )
    # ponytail: no live human-transfer number wired up yet — speaks the
    # handoff message and the WS route closes the connection gracefully.
    # Upgrade: TwiML <Dial> to a real coordinator queue once one exists.
    return FALLBACK_MESSAGE


def _parse_llm_json(raw: str) -> dict:
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        return json.loads(cleaned.strip())
    except (json.JSONDecodeError, AttributeError):
        return {"say": raw, "extracted": {}}
