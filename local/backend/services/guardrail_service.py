# ponytail: one class — ceiling: new guardrail types need code; upgrade: plugin hooks
"""Hard guardrails: regex, thresholds, escalation, merge — config only, no Gemini/DB."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_LOCAL_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_RULES = _LOCAL_ROOT / "data" / "guardrail_rules.json"


class GuardrailService:
    def __init__(self, rules_path: Path | str | None = None) -> None:
        path = Path(rules_path) if rules_path else _DEFAULT_RULES
        with path.open(encoding="utf-8") as f:
            self._rules = json.load(f)

        self._patterns: list[dict[str, Any]] = []
        for item in self._rules["blocked_patterns"]:
            compiled = dict(item)
            compiled["regex"] = re.compile(item["pattern"])
            self._patterns.append(compiled)

        self._thresholds = self._rules["confidence_thresholds"]
        self._escalations = self._rules["escalation_triggers"]
        self._merge_rules = self._rules["merge_rules"]
        self._critical_fields = set(self._thresholds.get("critical_fields", []))

    def check_outgoing_message(self, text: str, mode: str) -> dict[str, Any]:
        violations: list[dict[str, Any]] = []
        for p in self._patterns:
            modes = p.get("modes")
            if modes and mode not in modes:
                continue
            m = p["regex"].search(text)
            if not m:
                continue
            violations.append(
                {
                    "name": p["name"],
                    "reason": p["reason"],
                    "matched": m.group(0),
                    "replacement": p["replacement"],
                    "severity": p["severity"],
                }
            )

        if not violations:
            return {"status": "PASS", "violations": []}

        if any(v["severity"] == "critical" for v in violations):
            status = "BLOCKED"
        else:
            status = "PASS_WITH_WARNINGS"

        return {
            "status": status,
            "violations": violations,
            "suggested_replacement": violations[0]["replacement"],
        }

    def check_confidence(self, field: str, score: float) -> str:
        auto = self._thresholds["field_auto_populate_threshold"]
        reject = self._thresholds["field_reject_threshold"]
        if score < reject:
            return "REJECT"
        if score >= auto:
            return "AUTO_POPULATE"
        if field in self._critical_fields:
            return "CONFIRM_WITH_CALLER"
        return "FLAG_FOR_REVIEW"

    def check_correction_confidence(self, score: float) -> str:
        # Mid-band reuses field_auto_populate_threshold (plan lock #5)
        accept = self._thresholds["correction_accept_threshold"]
        mid = self._thresholds["field_auto_populate_threshold"]
        if score >= accept:
            return "ACCEPT"
        if score >= mid:
            return "FLAG"
        return "RETRY"

    def check_caller_identification_confidence(self, score: float) -> str:
        if score >= self._thresholds["caller_identification_threshold"]:
            return "COMMIT_MODE"
        return "ASK_CLARIFY"

    def check_eligibility_confidence(self, result: dict[str, Any]) -> str:
        thresh = self._thresholds["eligibility_confirm_threshold"]
        warn_days = self._thresholds["cert_expiry_warn_days"]
        confidence = float(result.get("confidence", 0.0))
        exact = bool(result.get("exact_plan_match", False))
        cert_days = result.get("caregiver_cert_days_remaining")
        near_cap = bool(result.get("caregiver_near_capacity", False))

        if confidence < thresh:
            return "DEFER"

        cert_ok = cert_days is None or int(cert_days) > warn_days
        if exact and cert_ok and not near_cap:
            return "CONFIRM"
        return "HEDGE"

    def check_escalation(self, state: dict[str, Any]) -> dict[str, Any] | str:
        fired: list[dict[str, Any]] = []

        for trigger in self._escalations:
            name = trigger["name"]
            hit = self._eval_trigger(trigger, state)
            if hit is None:
                continue
            fired.append(hit)

        if not fired:
            return "NO_ESCALATION"

        # Lowest priority_rank wins; ties keep config array order (stable sort)
        fired.sort(key=lambda x: x["priority_rank"])
        return fired[0]

    def _eval_trigger(
        self, trigger: dict[str, Any], state: dict[str, Any]
    ) -> dict[str, Any] | None:
        name = trigger["name"]

        if name == "human_request":
            text = (state.get("caller_text") or "").lower()
            for kw in trigger.get("keywords", []):
                if kw.lower() in text:
                    return self._escalation_hit(trigger, "ESCALATE")
            return None

        if name == "caller_distress":
            if state.get(trigger.get("state_flag", "caller_distress")):
                return self._escalation_hit(trigger, "ESCALATE")
            return None

        if name == "clinical_question":
            if state.get(trigger.get("state_flag", "clinical_question")):
                return self._escalation_hit(trigger, "ESCALATE")
            return None

        if name == "data_conflict_unresolvable":
            if state.get(trigger.get("state_flag", "unresolvable_conflict")):
                return self._escalation_hit(trigger, "ESCALATE")
            return None

        if name in ("repeated_misunderstanding", "off_topic_persistent"):
            key = trigger.get("state_key", "")
            count = int(state.get(key, 0) or 0)
            if count >= int(trigger.get("threshold_count", 3)):
                return self._escalation_hit(trigger, "ESCALATE")
            return None

        if name == "max_call_duration":
            duration = float(state.get("duration_minutes", 0) or 0)
            wrap = float(trigger.get("wrap_up_minutes", 12))
            maximum = float(trigger.get("max_minutes", 15))
            if duration >= maximum:
                return {
                    "trigger": name,
                    "outcome": "END_CALL",
                    "action": trigger["action"],
                    "priority_rank": int(
                        trigger.get("end_call_priority_rank", trigger["priority_rank"])
                    ),
                }
            if duration >= wrap:
                return {
                    "trigger": name,
                    "outcome": "WRAP_UP",
                    "action": trigger["action"],
                    "priority_rank": int(
                        trigger.get(
                            "wrap_up_priority_rank",
                            trigger["priority_rank"] + 1,
                        )
                    ),
                }
            return None

        return None

    @staticmethod
    def _escalation_hit(trigger: dict[str, Any], outcome: str) -> dict[str, Any]:
        return {
            "trigger": trigger["name"],
            "outcome": outcome,
            "action": trigger["action"],
            "priority_rank": int(trigger["priority_rank"]),
        }

    def resolve_merge_conflict(
        self, field: str, fax_value: Any, caller_value: Any
    ) -> dict[str, Any]:
        rule = self._find_merge_rule(field)
        winner_policy = rule["winner"]
        action = rule["action"]

        if winner_policy == "caller":
            winner, loser = caller_value, fax_value
        elif winner_policy == "fax":
            winner, loser = fax_value, caller_value
        elif winner_policy == "more_complete":
            winner, loser = self._more_complete(fax_value, caller_value)
            action = "flag_for_review"
        else:
            # flag / default — keep both
            winner, loser = None, None
            action = "keep_both"

        audit = {
            "field": field,
            "fax_value": fax_value,
            "caller_value": caller_value,
            "winner": winner,
            "action": action,
            "reason": rule["reason"],
            "rule": rule["name"],
        }
        return {
            "winner": winner,
            "loser": loser,
            "action": action,
            "reason": rule["reason"],
            "audit": audit,
        }

    def _find_merge_rule(self, field: str) -> dict[str, Any]:
        default = None
        for rule in self._merge_rules:
            fields = rule["fields"]
            if fields == ["*"]:
                default = rule
                continue
            if field in fields:
                return rule
        assert default is not None
        return default

    @staticmethod
    def _more_complete(fax_value: Any, caller_value: Any) -> tuple[Any, Any]:
        fax_s = "" if fax_value is None else str(fax_value)
        caller_s = "" if caller_value is None else str(caller_value)
        if len(caller_s) > len(fax_s):
            return caller_value, fax_value
        if len(fax_s) > len(caller_s):
            return fax_value, caller_value
        # tie — prefer caller (more recent) but still flag
        return caller_value, fax_value

    def format_guardrail_feedback(self, violations: list[dict[str, Any]]) -> str:
        if not violations:
            return "[GUARDRAIL] Your response was blocked. Rephrase."
        reasons = "; ".join(v.get("reason", v.get("name", "")) for v in violations)
        names = ", ".join(v.get("name", "violation") for v in violations)
        return (
            f"[GUARDRAIL] Your response was blocked. Reason: {reasons}. "
            f"Rephrase without {names}. "
            "Do not acknowledge the correction to the caller."
        )
