"""Unit tests for GuardrailService — no DB, Gemini, or Twilio."""

from __future__ import annotations

import unittest
from pathlib import Path

from backend.prompts import load_prompt
from backend.services.guardrail_service import GuardrailService

_RULES = Path(__file__).resolve().parents[2] / "data" / "guardrail_rules.json"


class TestBlockedPatterns(unittest.TestCase):
    def setUp(self) -> None:
        self.gs = GuardrailService(_RULES)

    def test_you_are_accepted_blocked(self) -> None:
        r = self.gs.check_outgoing_message("you are accepted into care", "provider")
        self.assertEqual(r["status"], "BLOCKED")

    def test_you_are_admitted_blocked(self) -> None:
        r = self.gs.check_outgoing_message(
            "you are admitted to our program", "provider"
        )
        self.assertEqual(r["status"], "BLOCKED")

    def test_should_be_able_to_help_passes(self) -> None:
        r = self.gs.check_outgoing_message(
            "Based on our review, we should be able to help", "provider"
        )
        self.assertEqual(r["status"], "PASS")

    def test_guarantee_blocked(self) -> None:
        r = self.gs.check_outgoing_message("I guarantee we can help", "provider")
        self.assertEqual(r["status"], "BLOCKED")

    def test_nurse_name_promise_blocked(self) -> None:
        r = self.gs.check_outgoing_message(
            "your nurse will be Maria", "provider"
        )
        self.assertEqual(r["status"], "BLOCKED")

    def test_match_qualified_nurse_passes(self) -> None:
        r = self.gs.check_outgoing_message(
            "we'll match you with a qualified nurse", "provider"
        )
        self.assertEqual(r["status"], "PASS")

    def test_medical_advice_blocked(self) -> None:
        r = self.gs.check_outgoing_message(
            "you should take Lisinopril", "provider"
        )
        self.assertEqual(r["status"], "BLOCKED")

    def test_doctor_discuss_meds_passes(self) -> None:
        r = self.gs.check_outgoing_message(
            "your doctor can discuss medication options", "provider"
        )
        self.assertEqual(r["status"], "PASS")

    def test_ssn_blocked(self) -> None:
        r = self.gs.check_outgoing_message(
            "The SSN on file is 123-45-6789", "provider"
        )
        self.assertEqual(r["status"], "BLOCKED")

    def test_member_id_last4_passes(self) -> None:
        r = self.gs.check_outgoing_message(
            "I have a member ID ending in 6789", "provider"
        )
        self.assertEqual(r["status"], "PASS")

    def test_family_jargon_icd10_warning(self) -> None:
        r = self.gs.check_outgoing_message(
            "We noted the ICD-10 on the form", "family"
        )
        self.assertEqual(r["status"], "PASS_WITH_WARNINGS")
        self.assertTrue(any("icd" in v["name"] for v in r["violations"]))

    def test_family_jargon_npi_warning(self) -> None:
        r = self.gs.check_outgoing_message("What is the NPI for the doctor?", "family")
        self.assertEqual(r["status"], "PASS_WITH_WARNINGS")

    def test_provider_mode_allows_icd10(self) -> None:
        r = self.gs.check_outgoing_message(
            "Please confirm the ICD-10 code", "provider"
        )
        self.assertEqual(r["status"], "PASS")


class TestConfidence(unittest.TestCase):
    def setUp(self) -> None:
        self.gs = GuardrailService(_RULES)

    def test_auto_populate(self) -> None:
        self.assertEqual(self.gs.check_confidence("zip_code", 0.9), "AUTO_POPULATE")

    def test_flag_for_review(self) -> None:
        # Mid-band: reject (0.3) <= score < auto_populate (0.5)
        self.assertEqual(self.gs.check_confidence("zip_code", 0.4), "FLAG_FOR_REVIEW")

    def test_reject(self) -> None:
        self.assertEqual(self.gs.check_confidence("zip_code", 0.2), "REJECT")

    def test_critical_confirm(self) -> None:
        self.assertEqual(
            self.gs.check_confidence("insurance_member_id", 0.4),
            "CONFIRM_WITH_CALLER",
        )

    def test_correction_bands(self) -> None:
        self.assertEqual(self.gs.check_correction_confidence(0.9), "ACCEPT")
        self.assertEqual(self.gs.check_correction_confidence(0.6), "FLAG")
        self.assertEqual(self.gs.check_correction_confidence(0.4), "RETRY")

    def test_caller_identification(self) -> None:
        self.assertEqual(
            self.gs.check_caller_identification_confidence(0.9), "COMMIT_MODE"
        )
        self.assertEqual(
            self.gs.check_caller_identification_confidence(0.5), "ASK_CLARIFY"
        )


class TestEligibility(unittest.TestCase):
    def setUp(self) -> None:
        self.gs = GuardrailService(_RULES)

    def test_confirm(self) -> None:
        self.assertEqual(
            self.gs.check_eligibility_confidence(
                {
                    "confidence": 0.9,
                    "exact_plan_match": True,
                    "caregiver_cert_days_remaining": 30,
                    "caregiver_near_capacity": False,
                }
            ),
            "CONFIRM",
        )

    def test_hedge_fuzzy(self) -> None:
        self.assertEqual(
            self.gs.check_eligibility_confidence(
                {
                    "confidence": 0.85,
                    "exact_plan_match": False,
                    "caregiver_cert_days_remaining": 30,
                    "caregiver_near_capacity": False,
                }
            ),
            "HEDGE",
        )

    def test_hedge_near_capacity(self) -> None:
        self.assertEqual(
            self.gs.check_eligibility_confidence(
                {
                    "confidence": 0.9,
                    "exact_plan_match": True,
                    "caregiver_cert_days_remaining": 30,
                    "caregiver_near_capacity": True,
                }
            ),
            "HEDGE",
        )

    def test_hedge_cert_expiring(self) -> None:
        self.assertEqual(
            self.gs.check_eligibility_confidence(
                {
                    "confidence": 0.9,
                    "exact_plan_match": True,
                    "caregiver_cert_days_remaining": 5,
                    "caregiver_near_capacity": False,
                }
            ),
            "HEDGE",
        )

    def test_defer_low_confidence(self) -> None:
        self.assertEqual(
            self.gs.check_eligibility_confidence(
                {
                    "confidence": 0.4,
                    "exact_plan_match": True,
                    "caregiver_cert_days_remaining": 30,
                    "caregiver_near_capacity": False,
                }
            ),
            "DEFER",
        )


class TestMerge(unittest.TestCase):
    def setUp(self) -> None:
        self.gs = GuardrailService(_RULES)

    def test_phone_caller_wins(self) -> None:
        r = self.gs.resolve_merge_conflict("patient_phone", "111", "222")
        self.assertEqual(r["winner"], "222")
        self.assertEqual(r["action"], "overwrite")

    def test_icd_fax_wins(self) -> None:
        r = self.gs.resolve_merge_conflict("icd_codes", "Z96.641", "hip surgery")
        self.assertEqual(r["winner"], "Z96.641")
        self.assertEqual(r["action"], "overwrite")

    def test_insurance_flag(self) -> None:
        r = self.gs.resolve_merge_conflict("member_id", "AAA", "BBB")
        self.assertEqual(r["action"], "keep_both")
        self.assertIsNone(r["winner"])

    def test_patient_name_more_complete(self) -> None:
        r = self.gs.resolve_merge_conflict(
            "patient_name", "Maria Johnson", "Maria L. Johnson-Smith"
        )
        self.assertEqual(r["winner"], "Maria L. Johnson-Smith")
        self.assertEqual(r["action"], "flag_for_review")

    def test_unknown_field_default(self) -> None:
        r = self.gs.resolve_merge_conflict("favorite_color", "blue", "green")
        self.assertEqual(r["action"], "keep_both")


class TestEscalation(unittest.TestCase):
    def setUp(self) -> None:
        self.gs = GuardrailService(_RULES)

    def test_repeated_misunderstanding(self) -> None:
        r = self.gs.check_escalation({"misunderstanding_count": 3})
        self.assertIsInstance(r, dict)
        self.assertEqual(r["trigger"], "repeated_misunderstanding")
        self.assertEqual(r["outcome"], "ESCALATE")

    def test_duration_end_call(self) -> None:
        r = self.gs.check_escalation({"duration_minutes": 16})
        self.assertIsInstance(r, dict)
        self.assertEqual(r["trigger"], "max_call_duration")
        self.assertEqual(r["outcome"], "END_CALL")

    def test_duration_wrap_up(self) -> None:
        r = self.gs.check_escalation({"duration_minutes": 12})
        self.assertIsInstance(r, dict)
        self.assertEqual(r["outcome"], "WRAP_UP")

    def test_duration_no_escalation(self) -> None:
        r = self.gs.check_escalation({"duration_minutes": 10})
        self.assertEqual(r, "NO_ESCALATION")

    def test_human_request(self) -> None:
        r = self.gs.check_escalation(
            {"caller_text": "I want to speak to a person please"}
        )
        self.assertIsInstance(r, dict)
        self.assertEqual(r["trigger"], "human_request")
        self.assertEqual(r["outcome"], "ESCALATE")

    def test_caller_distress(self) -> None:
        r = self.gs.check_escalation({"caller_distress": True})
        self.assertIsInstance(r, dict)
        self.assertEqual(r["trigger"], "caller_distress")

    def test_clinical_question(self) -> None:
        r = self.gs.check_escalation({"clinical_question": True})
        self.assertIsInstance(r, dict)
        self.assertEqual(r["trigger"], "clinical_question")

    def test_off_topic(self) -> None:
        r = self.gs.check_escalation({"off_topic_redirect_count": 3})
        self.assertIsInstance(r, dict)
        self.assertEqual(r["trigger"], "off_topic_persistent")

    def test_data_conflict(self) -> None:
        r = self.gs.check_escalation({"unresolvable_conflict": True})
        self.assertIsInstance(r, dict)
        self.assertEqual(r["trigger"], "data_conflict_unresolvable")

    def test_priority_human_beats_duration(self) -> None:
        r = self.gs.check_escalation(
            {
                "caller_text": "I need a real person",
                "duration_minutes": 16,
            }
        )
        self.assertEqual(r["trigger"], "human_request")


class TestFeedbackAndPrompts(unittest.TestCase):
    def setUp(self) -> None:
        self.gs = GuardrailService(_RULES)

    def test_format_guardrail_feedback(self) -> None:
        blocked = self.gs.check_outgoing_message("I guarantee help", "provider")
        msg = self.gs.format_guardrail_feedback(blocked["violations"])
        self.assertIn("[GUARDRAIL]", msg)

    def test_load_prompt(self) -> None:
        text = load_prompt("provider_inbound")
        self.assertIn("intake coordinator", text)
        self.assertIn("ready_for_eligibility", text)


if __name__ == "__main__":
    unittest.main()
