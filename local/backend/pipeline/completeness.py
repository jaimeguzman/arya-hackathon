"""Layer 6 — completeness / gap list from intake_requirements.json."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_LOCAL = Path(__file__).resolve().parents[2]
F2F_ACTION = "Call referring provider to request F2F documentation."


@lru_cache(maxsize=1)
def _reqs() -> dict[str, Any]:
    return json.loads((_LOCAL / "data" / "intake_requirements.json").read_text(encoding="utf-8"))


def _present(fields: dict[str, Any], logical: str, aliases: dict[str, list[str]]) -> bool:
    keys = aliases.get(logical, [logical])
    for k in keys:
        v = fields.get(k)
        if v is None or v == "" or v == []:
            continue
        return True
    # special: diagnosis_or_icd
    if logical == "diagnosis_or_icd":
        return bool(fields.get("icd_codes") or fields.get("primary_diagnosis") or fields.get("diagnosis"))
    return False


def is_medicare(fields: dict[str, Any]) -> bool:
    payer = str(fields.get("payer_name") or "").casefold()
    plan_type = str(fields.get("plan_type") or "").casefold()
    return payer.startswith("medicare") or plan_type in {
        "medicare",
        "medicare_advantage",
    }


def check_completeness(fields: dict[str, Any]) -> list[dict[str, Any]]:
    reqs = _reqs()
    aliases = reqs.get("field_aliases", {})
    actions = reqs.get("gap_actions", {})
    gaps: list[dict[str, Any]] = []

    needed = list(reqs.get("required_all", []))
    if is_medicare(fields):
        needed.extend(reqs.get("required_medicare", []))

    for logical in needed:
        if _present(fields, logical, aliases):
            continue
        action = actions.get(logical) or actions.get("default") or "Collect via phone call."
        if logical == "f2f_encounter":
            action = F2F_ACTION
        gaps.append(
            {
                "field_name": logical,
                "reason": f"Required field missing: {logical}",
                "priority": "high",
                "suggested_action": action,
            }
        )
    return gaps
