"""Layer 2 — page classification via Gemini vision."""

from __future__ import annotations

import json
import re
from typing import Any

from backend.prompts import load_prompt

CATEGORIES = {
    "discharge_summary",
    "physician_order",
    "f2f_note",
    "insurance_card",
    "medication_list",
    "lab_results",
    "consent_form",
    "cover_sheet",
    "other",
}


def _parse_class(text: str) -> str:
    try:
        data = json.loads(text)
        c = data.get("classification", "other")
        if c in CATEGORIES:
            return c
    except json.JSONDecodeError:
        pass
    m = re.search(
        r"discharge_summary|physician_order|f2f_note|insurance_card|"
        r"medication_list|lab_results|consent_form|cover_sheet|other",
        text,
    )
    return m.group(0) if m else "other"


def classify_pages(pages: list[dict[str, Any]], gemini) -> list[dict[str, Any]]:
    prompt = load_prompt("classification")
    for p in pages:
        # Heuristic boost for digital text samples
        raw = (p.get("raw_text") or "").lower()
        if "face-to-face" in raw or "f2f" in raw:
            p["classification"] = "f2f_note"
            continue
        if "cover" in raw and "fax" in raw:
            p["classification"] = "cover_sheet"
            continue
        if p.get("is_digital") and "patient name" in raw:
            p["classification"] = "discharge_summary"
            continue
        from pathlib import Path

        img = Path(p["file_path"]).read_bytes()
        resp = gemini.generate_vision(img, prompt)
        p["classification"] = _parse_class(resp)
    return pages
