"""Consent gather — must-have.md guarantee #4.

Every call opens with this question before any patient data collection
begins. Yes/no detection is deterministic keyword matching, not an LLM
call — this is a binary gate, not a conversation.
"""

from __future__ import annotations

import re

CONSENT_QUESTION = (
    "Hi, this is Arya Health's automated assistant. This call may be "
    "recorded and is handled by an AI system to help coordinate care. "
    "Is that okay with you?"
)

_YES_WORDS = {"yes", "yeah", "yep", "sure", "okay", "ok", "fine", "alright", "correct"}
_NO_WORDS = {"no", "nope", "nah", "don't", "do not", "not okay", "not ok"}


def _contains_word(text: str, words: set[str]) -> bool:
    """Word-boundary match, not substring — "know" must never match "no"."""
    normalized = text.strip().lower()
    return any(re.search(rf"\b{re.escape(word)}\b", normalized) for word in words)


def is_affirmative(text: str) -> bool:
    return _contains_word(text, _YES_WORDS) and not is_negative(text)


def is_negative(text: str) -> bool:
    return _contains_word(text, _NO_WORDS)


def collect_patient_data(call_sid: str, consent_given: bool) -> None:
    """Guard called by every function that touches patient data.

    Refuses to run without consent_given=True — matches must-have.md #4's
    code-enforced pattern exactly.
    """
    assert consent_given, f"Refusing to collect data on call {call_sid}: consent not confirmed"
