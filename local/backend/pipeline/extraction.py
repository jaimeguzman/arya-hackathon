# ponytail: regex Path B — ceiling: no Docling; upgrade: Docling when needed
"""Layers 3–4 — OCR router (rules|vision) + normalization."""

from __future__ import annotations

import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.prompts import load_prompt

_LOCAL = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _patterns() -> dict[str, Any]:
    return json.loads((_LOCAL / "data" / "extraction_patterns.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _norms() -> dict[str, Any]:
    return json.loads(
        (_LOCAL / "data" / "extraction_normalization.json").read_text(encoding="utf-8")
    )


def _meaningful_count(fields: dict[str, Any]) -> int:
    n = 0
    for v in fields.values():
        if v is None:
            continue
        if isinstance(v, str) and v.strip():
            n += 1
        elif isinstance(v, list) and v:
            n += 1
        elif isinstance(v, dict) and v.get("value"):
            n += 1
    return n


def path_b_extract(raw_text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field, cfg in _patterns().items():
        pat = cfg.get("pattern")
        if not pat:
            continue
        m = re.search(pat, raw_text)
        if not m:
            continue
        val = m.group(1) if m.lastindex else m.group(0)
        if field == "icd_codes":
            codes = re.findall(pat, raw_text)
            out[field] = list(dict.fromkeys(codes))
        else:
            out[field] = val.strip()
    return out


def path_c_extract(page: dict[str, Any], gemini) -> dict[str, Any]:
    prompt = load_prompt("extraction") + f"\nPage classification: {page.get('classification')}"
    img = Path(page["file_path"]).read_bytes()
    resp = gemini.generate_vision(img, prompt)
    try:
        data = json.loads(resp)
    except json.JSONDecodeError:
        return {}
    fields = data.get("fields", data)
    flat: dict[str, Any] = {}
    for k, v in fields.items():
        if isinstance(v, dict) and "value" in v:
            flat[k] = v["value"]
        else:
            flat[k] = v
    return flat


def normalize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    norms = _norms()
    out: dict[str, Any] = {}
    for k, v in fields.items():
        if v is None:
            continue
        if k == "patient_name" and isinstance(v, str):
            out[k] = _norm_name(v)
        elif k in ("date_of_birth", "discharge_date") and isinstance(v, str):
            out[k] = _norm_date(v)
        elif k == "icd_codes":
            codes = v if isinstance(v, list) else [v]
            out[k] = [re.sub(r"\s+", "", str(c)).upper() for c in codes]
        elif k == "zip_code" and isinstance(v, str):
            m = re.search(r"\d{5}", v)
            out[k] = m.group(0) if m else v
        elif k == "payer_name" and isinstance(v, str):
            key = v.strip().casefold()
            out[k] = norms["payer_aliases"].get(key, v.strip())
        elif k == "patient_phone" and isinstance(v, str):
            digits = re.sub(r"\D", "", v)
            if len(digits) == 10:
                out[k] = f"+1{digits}"
            elif len(digits) == 11 and digits.startswith("1"):
                out[k] = f"+{digits}"
            else:
                out[k] = v
        else:
            out[k] = v
    return out


def _norm_name(name: str) -> str:
    name = name.strip()
    if "," in name:
        last, first = [p.strip() for p in name.split(",", 1)]
        name = f"{first} {last}"
    parts = [p.capitalize() for p in name.split() if p]
    return " ".join(parts)


def _norm_date(s: str) -> str:
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return s


def extract_and_normalize(pages: list[dict[str, Any]], gemini) -> list[dict[str, Any]]:
    for p in pages:
        if p.get("classification") == "cover_sheet":
            p["extraction_path"] = None
            p["raw_extraction"] = {}
            p["normalized"] = {}
            continue
        raw = p.get("raw_text") or ""
        fields: dict[str, Any] = {}
        path = "vision"
        if p.get("is_digital"):
            fields = path_b_extract(raw)
            if _meaningful_count(fields) >= 3:
                path = "rules"
            else:
                fields = path_c_extract(p, gemini)
                path = "vision"
        else:
            fields = path_c_extract(p, gemini)
            path = "vision"
        p["extraction_path"] = path
        p["raw_extraction"] = fields
        p["normalized"] = normalize_fields(fields)
    return pages
