"""Validation agent — deterministic checks + optional Gemini soft checks."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional


def luhn_npi(npi: str) -> bool:
    digits = re.sub(r"\D", "", npi)
    if len(digits) != 10:
        return False
    # NPI Luhn with prefix 80840
    payload = "80840" + digits
    total = 0
    reverse = payload[::-1]
    for i, ch in enumerate(reverse):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def validate_fields(
    fields: dict[str, Any],
    *,
    known_icds: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    known_icds = known_icds or set()

    for field, value in fields.items():
        entry = {
            "field": field,
            "extracted_value": value,
            "valid": True,
            "error": None,
            "severity": None,
        }
        if field == "icd_codes":
            codes = value if isinstance(value, list) else [value]
            bad = [c for c in codes if known_icds and c not in known_icds]
            # if no known set loaded, accept format-only
            if not known_icds:
                bad = [c for c in codes if not re.match(r"^[A-TV-Z][0-9][0-9A-Z.]+$", str(c))]
            if bad:
                entry["valid"] = False
                entry["error"] = f"invalid ICD: {bad}"
                entry["severity"] = "critical"
        elif field == "physician_npi":
            if not luhn_npi(str(value)):
                entry["valid"] = False
                entry["error"] = "NPI Luhn check failed"
                entry["severity"] = "critical"
        elif field == "zip_code":
            if not re.fullmatch(r"\d{5}", str(value)):
                entry["valid"] = False
                entry["error"] = "zip must be 5 digits"
                entry["severity"] = "warning"
        elif field in ("date_of_birth", "discharge_date"):
            try:
                d = date.fromisoformat(str(value)[:10])
                if d > date.today():
                    entry["valid"] = False
                    entry["error"] = "date in future"
                    entry["severity"] = "warning"
                if field == "date_of_birth":
                    age = (date.today() - d).days / 365.25
                    if age < 0 or age > 120:
                        entry["valid"] = False
                        entry["error"] = "unreasonable age"
                        entry["severity"] = "critical"
            except ValueError:
                entry["valid"] = False
                entry["error"] = "bad date format"
                entry["severity"] = "warning"
        results.append(entry)
    return results
