"""Guarantee 2: tokenize -> LLM -> rehydrate.

This module holds the SINGLE function allowed to call the Gemini API
(`call_llm`). It tokenizes identifiers before building the payload,
regex-scans the outgoing payload and refuses to send on any identifier
match, and rehydrates placeholders only after the LLM responds.

Token maps live per-request in backend memory (or Redis) and are never
sent to the LLM.
"""

import logging
import re
from collections.abc import Callable

logger = logging.getLogger("intakeai.safety.llm_gateway")

# Identifier fields tokenized before any payload is built. Vision-path
# document prompts go through the same tokenization for accompanying text.
IDENTIFIER_PLACEHOLDERS = {
    "name": "{{PATIENT_NAME}}",
    "dob": "{{PATIENT_DOB}}",
    "phone": "{{PATIENT_PHONE}}",
    "address": "{{PATIENT_ADDRESS}}",
    "member_id": "{{MEMBER_ID}}",
}

# Outgoing payload scan: refuse to send if any of these match.
IDENTIFIER_PATTERNS: dict[str, re.Pattern] = {
    "phone": re.compile(r"(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}"),
    "dob": re.compile(
        r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{1,2}-\d{1,2}-\d{4})\b"
    ),
    "member_id": re.compile(r"\b[A-Z]{2,4}\d{6,12}\b"),
    "address": re.compile(
        r"\b\d{1,6}\s+\w+(\s\w+)*\s(St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Ln|Lane|Dr|Drive)\b",
        re.IGNORECASE,
    ),
}


class IdentifierLeakError(RuntimeError):
    """Raised when an outgoing LLM payload contains a raw identifier."""


def tokenize(record: dict) -> tuple[dict, dict[str, str]]:
    """Replace identifier fields with placeholders. Returns (tokenized, token_map)."""
    tokenized = dict(record)
    token_map: dict[str, str] = {}
    for field, placeholder in IDENTIFIER_PLACEHOLDERS.items():
        value = tokenized.get(field)
        if value:
            token_map[placeholder] = str(value)
            tokenized[field] = placeholder
    return tokenized, token_map


def rehydrate(text: str, token_map: dict[str, str]) -> str:
    """Replace placeholders with original values — backend-side only."""
    for placeholder, value in token_map.items():
        text = text.replace(placeholder, value)
    return text


def scan_for_identifiers(payload: str) -> list[str]:
    """Return the names of identifier patterns found in the payload."""
    return [name for name, pattern in IDENTIFIER_PATTERNS.items() if pattern.search(payload)]


def _default_transport(payload: str) -> str:
    """The only place the Gemini SDK may be touched. Imported lazily so the
    safety layer works (and is testable) without the SDK installed."""
    from google import genai  # noqa: PLC0415 — single sanctioned import site

    from app.config import get_settings

    client = genai.Client(api_key=get_settings().gemini_api_key)
    response = client.models.generate_content(
        model="gemini-2.0-flash", contents=payload
    )
    return response.text


def call_llm(
    payload: str,
    token_map: dict[str, str] | None = None,
    transport: Callable[[str], str] = _default_transport,
) -> str:
    """The single sanctioned LLM entry point.

    Scans the outgoing payload; refuses to send on identifier match and logs
    a redacted audit event. Rehydrates the response inside the backend.
    """
    hits = scan_for_identifiers(payload)
    if hits:
        logger.warning(
            "safety.llm_gateway.blocked_payload",
            extra={"identifier_types": hits, "payload_length": len(payload)},
        )
        raise IdentifierLeakError(
            f"Refusing to send LLM payload: raw identifier patterns detected {hits}."
        )
    response = transport(payload)
    return rehydrate(response, token_map or {})
