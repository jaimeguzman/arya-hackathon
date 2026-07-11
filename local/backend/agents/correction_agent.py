"""Correction agent — Gemini + guardrail correction confidence bands."""

from __future__ import annotations

import json
from typing import Any

from backend.prompts import load_prompt
from backend.services.guardrail_service import GuardrailService


def correct_field(
    field: str,
    value: Any,
    error: str,
    gemini,
    guardrails: GuardrailService,
    *,
    context: str = "",
    max_retries: int = 2,
) -> dict[str, Any]:
    prompt_base = load_prompt("correction")
    attempts = 0
    last: dict[str, Any] = {
        "original_value": value,
        "corrected_value": None,
        "confidence": 0.0,
        "accepted": False,
        "flagged": False,
    }
    while attempts < max_retries:
        attempts += 1
        prompt = (
            f"{prompt_base}\nField: {field}\nValue: {value}\nError: {error}\n"
            f"Context: {context}\nAttempt: {attempts}"
        )
        resp = gemini.generate_text(prompt)
        try:
            data = json.loads(resp)
        except json.JSONDecodeError:
            data = {"corrected_value": None, "confidence": 0.0}
        conf = float(data.get("confidence") or 0.0)
        corrected = data.get("corrected_value")
        band = guardrails.check_correction_confidence(conf)
        last = {
            "original_value": value,
            "corrected_value": corrected,
            "confidence": conf,
            "attempts": attempts,
            "band": band,
            "accepted": band in ("ACCEPT", "FLAG"),
            "flagged": band == "FLAG",
        }
        if band == "ACCEPT":
            return last
        if band == "FLAG":
            return last
        # RETRY
        context = f"{context}\nPrevious attempt low confidence: {data}"
    last["accepted"] = False
    return last
