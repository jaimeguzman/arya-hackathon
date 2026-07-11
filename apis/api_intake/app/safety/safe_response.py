"""Guarantee 5: banned-phrase filter via SafeResponse before TTS.

speak() only accepts a SafeResponse, which filters banned phrases on
construction — the type system blocks any bypass.
"""

import re

BANNED_PHRASES = (
    "guarantee",
    "promise",
    "definitely will",
    "100%",
    "for sure",
    "confirmed appointment at",
)

BANNED_PHRASE_REPLACEMENT = "we will do our best"


class SafeResponse:
    """Text safe for TTS. Banned phrases are filtered at construction time."""

    __slots__ = ("text",)

    def __init__(self, draft: str) -> None:
        filtered = draft
        for phrase in BANNED_PHRASES:
            filtered = re.sub(re.escape(phrase), BANNED_PHRASE_REPLACEMENT, filtered, flags=re.IGNORECASE)
        self.text = filtered


def speak(response: SafeResponse) -> str:
    """The only path to TTS. Accepts SafeResponse exclusively."""
    if not isinstance(response, SafeResponse):
        raise TypeError("speak() only accepts a SafeResponse — no raw text may reach TTS.")
    return response.text
