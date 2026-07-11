"""Safety pipeline: tokenize -> call_llm -> rehydrate -> filter_response -> speak.

Implements must-have.md guarantees #2 (tokenize/rehydrate wrapper) and #5
(banned-phrase filter). This is the ONLY module in the codebase allowed to
import the Gemini SDK — no other file may call the LLM directly.
"""

from __future__ import annotations

import logging
import re

from google import genai

from backend.config import get_settings

logger = logging.getLogger(__name__)

# must-have.md #2 — fail-closed backstop. tokenize() is the primary defense;
# this catches anything that slips through (e.g. a tokenize() bug).
PHI_PATTERNS = [
    r"\b\d{3}-\d{2}-\d{4}\b",       # SSN shape
    r"\b\d{10}\b",                   # bare 10-digit phone/NPI-shaped number
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",  # date shape (DOB)
]

# must-have.md #5
BANNED_PHRASES = [
    "guarantee", "guaranteed", "promise", "definitely will",
    "100%", "for sure", "confirmed appointment at",
    "you are accepted", "you are admitted", "you are approved",
]

SAFE_FALLBACK_RESPONSE = "A coordinator will confirm this shortly."

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY not set — cannot call the LLM")
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def tokenize(text: str, known_fields: dict[str, str]) -> str:
    """Replace previously-extracted identifier values with placeholders.

    Only redacts values already known from earlier in this call — the
    caller's brand-new utterance still has to reach the LLM once so a field
    can be extracted from it in the first place. This closes off
    re-exposure of already-known identifiers across turns, which is what
    must-have.md #2 is actually protecting against in a live conversation
    (the LLM never accumulates a growing store of raw PII in context).
    """
    tokenized = text
    for field_name, value in known_fields.items():
        if value and str(value) in tokenized:
            tokenized = tokenized.replace(str(value), f"{{{{{field_name.upper()}}}}}")
    return tokenized


def rehydrate(text: str, known_fields: dict[str, str]) -> str:
    """Replace placeholders back with real values — inside the backend only, never re-sent to the LLM."""
    rehydrated = text
    for field_name, value in known_fields.items():
        if value:
            rehydrated = rehydrated.replace(f"{{{{{field_name.upper()}}}}}", str(value))
    return rehydrated


def call_llm(tokenized_text: str, system_prompt: str) -> str:
    """The ONE function in the codebase allowed to call the LLM API."""
    for pattern in PHI_PATTERNS:
        if re.search(pattern, tokenized_text):
            raise ValueError("Refusing LLM call: raw identifier pattern detected in payload")

    client = _get_client()
    settings = get_settings()
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=tokenized_text,
        config=genai.types.GenerateContentConfig(system_instruction=system_prompt),
    )
    return response.text


def filter_response(text: str) -> str:
    lowered = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lowered:
            logger.warning("Blocked banned phrase %r in response", phrase)
            return SAFE_FALLBACK_RESPONSE
    return text


class SafeResponse:
    """Wraps text that has passed through filter_response(). speak() only accepts this type."""

    def __init__(self, text: str):
        self.text = filter_response(text)


def speak(response: SafeResponse) -> str:
    if not isinstance(response, SafeResponse):
        raise TypeError("Refusing to speak: response was not passed through filter_response()")
    return response.text
