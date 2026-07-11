"""Phase 5 orchestrator unit tests."""

from __future__ import annotations

import unittest

from backend.agents.orchestrator import (
    IntakeState,
    empty_state,
    has_critical_gaps,
    map_extracted_to_buckets,
    Orchestrator,
)


class TestIntakeStateHelpers(unittest.TestCase):
    def test_empty_state_keys(self) -> None:
        s = empty_state(source_type="fax")
        self.assertEqual(s["source_type"], "fax")
        self.assertFalse(s["workflow_complete"])
        self.assertEqual(s["eligibility_run_count"], 0)

    def test_map_extracted(self) -> None:
        buckets = map_extracted_to_buckets(
            {
                "patient_name": "Maria Johnson",
                "zip_code": "11201",
                "payer_name": "Medicare",
                "icd_codes": ["Z96.641"],
            }
        )
        self.assertEqual(buckets["patient_data"]["patient_name"], "Maria Johnson")
        self.assertEqual(buckets["insurance_data"]["payer_name"], "Medicare")
        self.assertEqual(buckets["clinical_data"]["icd_codes"], ["Z96.641"])

    def test_critical_gaps(self) -> None:
        s: IntakeState = empty_state(gaps=[{"field_name": "f2f_encounter", "priority": "high"}])
        self.assertTrue(has_critical_gaps(s))
        s2: IntakeState = empty_state(gaps=[{"field_name": "notes", "priority": "low"}])
        self.assertFalse(has_critical_gaps(s2))
        s3: IntakeState = empty_state(missing_documents=["F2F"])
        self.assertTrue(has_critical_gaps(s3))

    def test_routers(self) -> None:
        orch = Orchestrator()
        fax = empty_state(source_type="fax")
        self.assertEqual(orch.route_after_receive(fax), "process_document")
        call = empty_state(source_type="inbound_call_provider")
        self.assertEqual(orch.route_after_receive(call), "handle_inbound_call")
        snf = empty_state(source_type="snf_referral")
        self.assertEqual(orch.route_after_receive(snf), "process_document")

        accept_clean = empty_state(eligibility_decision="ACCEPT", gaps=[])
        self.assertEqual(orch.route_after_eligibility(accept_clean), "make_decision")
        accept_gap = empty_state(
            eligibility_decision="ACCEPT",
            gaps=[{"field_name": "f2f_encounter", "priority": "high"}],
        )
        self.assertEqual(orch.route_after_eligibility(accept_gap), "evaluate_gaps")
        decline = empty_state(eligibility_decision="DECLINE")
        self.assertEqual(orch.route_after_eligibility(decline), "make_decision")


if __name__ == "__main__":
    unittest.main()
