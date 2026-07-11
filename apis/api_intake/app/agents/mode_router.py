"""Caller-type detection for inbound calls (WORKFLOW Path A Step 3).

Classifies the caller as PROVIDER, FAMILY, or PATIENT from early-turn
statements and selects the corresponding static system prompt (Layer 1
control). OUTBOUND is never assigned here — it is reserved for
agency-initiated calls carrying a mission parameter.

Detection is only invoked after consent_given is True (enforced by the
@requires_consent decorator and by the call-flow wiring in routes/twilio.py).
"""

import json
import re
from enum import Enum
from pathlib import Path

from pydantic import BaseModel

from app.safety.consent import requires_consent


class CallerMode(str, Enum):
    PROVIDER = "provider"
    FAMILY = "family"
    PATIENT = "patient"
    OUTBOUND = "outbound"


# Modes an inbound caller may ever be routed to. OUTBOUND is excluded by
# design: it requires an agency-initiated call with a mission parameter.
INBOUND_MODES = frozenset({CallerMode.PROVIDER, CallerMode.FAMILY, CallerMode.PATIENT})

# Static system prompts per mode (Layer 1 control), owned by ai-agents/.
# Per ai-agents/voice-agent/family-mode.md, the family prompt covers "a family
# member or the patient themselves" — patient mode uses that cautious,
# plain-language profile until a dedicated patient prompt lands (feature #47).
_PROMPTS_DIR = Path(__file__).resolve().parents[4] / "ai-agents" / "voice-agent"
MODE_PROMPT_FILES = {
    CallerMode.PROVIDER: "provider-mode.md",
    CallerMode.FAMILY: "family-mode.md",
    CallerMode.PATIENT: "family-mode.md",
    CallerMode.OUTBOUND: "outbound-mode.md",
}

# Ambiguity handling (feature: ambiguous / low-confidence classification).
# The most cautious profile is Family: plain-language, never-promise — safe
# for any caller type until the true one is resolved.
CAUTIOUS_DEFAULT_MODE = CallerMode.FAMILY
# confidence = winning-mode matches / total matches across all modes. Below
# this share the evidence is mixed enough that guessing is unsafe, so the
# cautious default applies instead of the classified mode.
MODE_CONFIDENCE_THRESHOLD = 0.7
# One neutral clarifying question — names no mode as a guess.
MODE_CLARIFYING_QUESTION = (
    "To make sure I help you the right way — are you calling from a "
    "provider's office, or about care for yourself or a family member?"
)

# Phrase evidence per inbound mode. Order within a mode does not matter; the
# mode with the most distinct matches wins. Ties or zero matches -> no mode.
_MODE_PHRASES: dict[CallerMode, tuple[str, ...]] = {
    CallerMode.PROVIDER: (
        "discharge planner",
        "case manager",
        "social worker",
        "physician office",
        "doctor's office",
        "calling from the hospital",
        "calling from st",
        "calling from mercy",
        "we have a patient",
        "i have a referral",
        "sending a referral",
        "referral for a patient",
        "i'm a nurse",
        "care coordinator at",
    ),
    CallerMode.FAMILY: (
        "my mother",
        "my mom",
        "my father",
        "my dad",
        "my husband",
        "my wife",
        "my son",
        "my daughter",
        "my grandmother",
        "my grandfather",
        "his daughter",
        "her daughter",
        "his son",
        "her son",
        "his wife",
        "her husband",
        "i'm the daughter",
        "i'm the son",
        "for my parent",
        "family member",
    ),
    CallerMode.PATIENT: (
        "for myself",
        "care for myself",
        "i need care",
        "i was discharged",
        "i just got out of the hospital",
        "i'm the patient",
        "i am the patient",
        "my doctor told me",
        "my doctor said",
        "help for me",
    ),
}


class ModeTransition(BaseModel):
    """One mid-call mode switch, logged for dashboard visibility."""

    old_mode: CallerMode
    new_mode: CallerMode
    turn: int


class ModeClassification(BaseModel):
    """Result of early-turn caller-type detection."""

    mode: CallerMode | None
    confidence: float
    matched_phrases: list[str]


def _match_phrases(utterance: str) -> dict[CallerMode, list[str]]:
    lowered = re.sub(r"\s+", " ", utterance.lower())
    return {
        mode: [phrase for phrase in phrases if phrase in lowered]
        for mode, phrases in _MODE_PHRASES.items()
    }


def classify_utterance(utterance: str) -> ModeClassification:
    """Pure classification: strongest phrase evidence wins; ties are ambiguous.

    Only ever returns an inbound mode (or None) — never OUTBOUND.
    """
    matches = _match_phrases(utterance)
    scores = {mode: len(found) for mode, found in matches.items()}
    total = sum(scores.values())
    if total == 0:
        return ModeClassification(mode=None, confidence=0.0, matched_phrases=[])
    best = max(scores, key=lambda mode: scores[mode])
    tied = [mode for mode, score in scores.items() if score == scores[best]]
    if len(tied) > 1:
        return ModeClassification(mode=None, confidence=0.0, matched_phrases=[])
    assert best in INBOUND_MODES
    return ModeClassification(
        mode=best,
        confidence=scores[best] / total,
        matched_phrases=matches[best],
    )


@requires_consent
def detect_caller_mode(call, utterance: str) -> ModeClassification:
    """Consent-gated entry point: refuses to classify before consent_given."""
    return classify_utterance(utterance)


def load_mode_prompt(mode: CallerMode) -> str:
    """Load the static system prompt (Layer 1) for the assigned mode."""
    return (_PROMPTS_DIR / MODE_PROMPT_FILES[mode]).read_text(encoding="utf-8")


class CallModeStore:
    """Persists call.mode in Redis (key: call:{sid}, field: mode).

    Takes any Redis-compatible client (redis.Redis in production; a fake in
    tests) so the persistence contract is testable without a running server.
    """

    def __init__(self, client) -> None:
        self._client = client

    def set_mode(self, call_sid: str, mode: CallerMode) -> None:
        self._client.hset(f"call:{call_sid}", "mode", mode.value)

    def get_mode(self, call_sid: str) -> CallerMode | None:
        raw = self._client.hget(f"call:{call_sid}", "mode")
        if raw is None:
            return None
        value = raw.decode() if isinstance(raw, bytes) else raw
        return CallerMode(value)

    def log_transition(self, call_sid: str, transition: ModeTransition) -> None:
        self._client.rpush(
            f"call:{call_sid}:mode_transitions", transition.model_dump_json()
        )

    def get_transitions(self, call_sid: str) -> list[ModeTransition]:
        raw_items = self._client.lrange(f"call:{call_sid}:mode_transitions", 0, -1)
        return [
            ModeTransition(**json.loads(item.decode() if isinstance(item, bytes) else item))
            for item in raw_items
        ]
