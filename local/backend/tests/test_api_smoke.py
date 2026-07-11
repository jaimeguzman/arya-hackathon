"""Phase 3 API smoke tests — requires Docker DBs seeded."""

from __future__ import annotations

import io
import unittest
from uuid import UUID

from fastapi.testclient import TestClient

from backend.main import app


class TestApiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._cm = TestClient(app)
        cls.client = cls._cm.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._cm.__exit__(None, None, None)

    def test_01_health(self) -> None:
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["service"], "IntakeAI")
        self.assertEqual(body["postgres"], "ok")
        self.assertEqual(body["neo4j"], "ok")
        self.assertEqual(body["redis"], "ok")

    def test_02_create_intake(self) -> None:
        r = self.client.post(
            "/api/intake",
            json={"source": "inbound_call_provider"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "new")
        self.assertTrue(UUID(body["id"]))
        type(self).intake_id = body["id"]

    def test_03_update_intake_data(self) -> None:
        intake_id = getattr(type(self), "intake_id", None)
        if not intake_id:
            self.skipTest("no intake_id")
        r = self.client.put(
            f"/api/intake/{intake_id}",
            json={
                "patient_data": {"patient_name": "Maria Johnson", "zip_code": "11201"},
                "clinical_data": {"icd_code": "Z96.641"},
            },
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["patient_data"]["patient_name"], "Maria Johnson")
        self.assertEqual(body["clinical_data"]["icd_code"], "Z96.641")

    def test_04_eligibility_accept(self) -> None:
        r = self.client.post(
            "/api/eligibility/check",
            json={
                "icd_code": "Z96.641",
                "insurance_payer": "Medicare",
                "insurance_plan": "Medicare Part A",
                "zip_code": "11201",
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["decision"], "ACCEPT")
        self.assertGreater(len(body["matched_caregivers"]), 0)
        self.assertIn(body["voice_guidance"], ("CONFIRM", "HEDGE", "DEFER"))

    def test_05_eligibility_decline_zip(self) -> None:
        r = self.client.post(
            "/api/eligibility/check",
            json={
                "icd_code": "Z96.641",
                "insurance_payer": "Medicare",
                "insurance_plan": "Medicare Part A",
                "zip_code": "90210",
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["decision"], "DECLINE")

    def test_06_eligibility_decline_insurance(self) -> None:
        r = self.client.post(
            "/api/eligibility/check",
            json={
                "icd_code": "Z96.641",
                "insurance_payer": "Aetna",
                "insurance_plan": "Aetna HMO",
                "zip_code": "11201",
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["decision"], "DECLINE")

    def test_07_caregiver_match(self) -> None:
        r = self.client.post(
            "/api/caregivers/match",
            json={"certification_types": ["RN", "orthopedic"], "zip_code": "11201"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertGreater(body["count"], 0)

    def test_08_document_upload(self) -> None:
        pdf = b"%PDF-1.1\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
        r = self.client.post(
            "/api/documents/upload",
            files={"file": ("sample.pdf", io.BytesIO(pdf), "application/pdf")},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["processing_status"], "uploaded")
        self.assertIsNone(body["page_count"])

    def test_09_followup_create(self) -> None:
        intake_id = getattr(type(self), "intake_id", None)
        if not intake_id:
            # create one
            cr = self.client.post("/api/intake", json={"source": "inbound_call_provider"})
            intake_id = cr.json()["id"]
        r = self.client.post(
            "/api/followup",
            json={
                "intake_record_id": intake_id,
                "type": "sms_sent",
                "target_phone": "+15555550100",
                "message": "test",
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["type"], "sms_sent")
        self.assertEqual(str(body["intake_record_id"]), str(intake_id))

    def test_10_voice_inbound_twiml(self) -> None:
        r = self.client.post("/voice/inbound")
        self.assertEqual(r.status_code, 200)
        self.assertIn("ConversationRelay", r.text)
        self.assertIn("application/xml", r.headers.get("content-type", ""))


if __name__ == "__main__":
    unittest.main()
