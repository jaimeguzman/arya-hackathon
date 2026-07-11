# ponytail: thin wrapper — ceiling: no retry/backoff; upgrade: tenacity + streaming
"""Gemini Flash client with injectable FakeGeminiClient for tests."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from backend.config import get_settings

logger = logging.getLogger(__name__)
MODEL_ID = "gemini-2.0-flash"


class FakeGeminiClient:
    """Scripted responses — no network."""

    def __init__(self, scripted: dict[str, str] | list[str] | None = None) -> None:
        self.scripted = scripted or {}
        self.calls: list[str] = []
        self._list_i = 0

    def generate_text(self, prompt: str) -> str:
        self.calls.append(prompt[:200])
        if isinstance(self.scripted, list):
            if self._list_i < len(self.scripted):
                out = self.scripted[self._list_i]
                self._list_i += 1
                return out
            return "{}"
        for key, val in self.scripted.items():
            if key.lower() in prompt.lower():
                return val
        pl = prompt.lower()
        # extraction prompts append "Page classification:" — match extract first
        if "extract" in pl or "page classification:" in pl:
            return json.dumps(
                {
                    "fields": {
                        "patient_name": {"value": "Maria Johnson", "confidence": 0.7},
                        "icd_codes": {"value": "Z96.641", "confidence": 0.7},
                        "zip_code": {"value": "11201", "confidence": 0.7},
                        "payer_name": {"value": "Medicare", "confidence": 0.7},
                    }
                }
            )
        if "classif" in pl:
            return json.dumps({"classification": "discharge_summary"})
        if "correct" in pl:
            return json.dumps(
                {
                    "corrected_value": "Z96.641",
                    "confidence": 0.9,
                    "reasoning": "OCR fix",
                    "can_correct": True,
                }
            )
        return "{}"

    def generate_vision(
        self, image_bytes: bytes, prompt: str, mime: str = "image/png"
    ) -> str:
        return self.generate_text(prompt)


class GeminiClient:
    def __init__(
        self, api_key: str | None = None, client: Any | None = None
    ) -> None:
        self._injected = client
        self._model = None
        if client is not None:
            return
        key = api_key if api_key is not None else get_settings().gemini_api_key
        if not key:
            raise RuntimeError("GEMINI_API_KEY missing")
        import google.generativeai as genai

        genai.configure(api_key=key)
        self._model = genai.GenerativeModel(MODEL_ID)

    def generate_text(self, prompt: str) -> str:
        if self._injected is not None:
            return self._injected.generate_text(prompt)
        resp = self._model.generate_content(prompt)
        return getattr(resp, "text", None) or str(resp)

    def generate_vision(
        self, image_bytes: bytes, prompt: str, mime: str = "image/png"
    ) -> str:
        if self._injected is not None:
            return self._injected.generate_vision(image_bytes, prompt, mime)
        resp = self._model.generate_content(
            [{"mime_type": mime, "data": image_bytes}, prompt]
        )
        return getattr(resp, "text", None) or str(resp)


def get_default_gemini() -> GeminiClient | FakeGeminiClient:
    """Prefer real client; fall back to Fake when key absent (dev/tests)."""
    key = get_settings().gemini_api_key
    if not key:
        logger.warning("GEMINI_API_KEY missing — using FakeGeminiClient")
        return FakeGeminiClient()
    try:
        return GeminiClient(api_key=key)
    except Exception as exc:
        logger.warning("Gemini init failed (%s) — using FakeGeminiClient", exc)
        return FakeGeminiClient()
