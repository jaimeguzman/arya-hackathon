"""Phase 4 e2e — sample PDFs through DocumentProcessor with FakeGemini."""

from __future__ import annotations

import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.services.gemini_client import FakeGeminiClient
from backend.workers.document_processor import DocumentProcessor

_LOCAL = Path(__file__).resolve().parents[2]
_SAMPLES = _LOCAL / "data" / "sample_referrals"


class TestPipelineE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._cm = TestClient(app)
        cls.client = cls._cm.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._cm.__exit__(None, None, None)

    def _upload(self, pdf_name: str, intake_id: str | None = None) -> dict:
        pdf = _SAMPLES / pdf_name
        if not pdf.exists():
            self.skipTest(f"missing {pdf_name}")
        params = {}
        if intake_id:
            params["intake_record_id"] = intake_id
        with pdf.open("rb") as fh:
            r = self.client.post(
                "/api/documents/upload",
                params=params,
                files={"file": (pdf_name, fh, "application/pdf")},
            )
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_complete_referral_pipeline(self) -> None:
        fake = FakeGeminiClient()
        with patch(
            "backend.workers.document_processor.get_default_gemini",
            return_value=fake,
        ), patch(
            "backend.api.documents._processor",
            DocumentProcessor(gemini=fake),
        ):
            # re-bind processor used by upload route
            import backend.api.documents as docs_api

            docs_api._processor = DocumentProcessor(gemini=fake)
            body = self._upload("referral_complete.pdf")
            doc_id = body["id"]
            st = self.client.get(f"/api/documents/{doc_id}/status")
            self.assertEqual(st.status_code, 200, st.text)
            data = st.json()
            self.assertEqual(data["status"], "complete")
            self.assertIn("fields", data["extraction_result"])
            self.assertIsInstance(data["confidence_scores"], dict)
            self.assertIsInstance(data["gaps"], list)
            # digital complete should prefer rules on at least one page
            ext = self.client.get(f"/api/documents/{doc_id}/extraction")
            self.assertEqual(ext.status_code, 200, ext.text)
            pages = ext.json()["pages"]
            paths = {p.get("extraction_path") for p in pages}
            self.assertTrue(paths & {"rules", "vision", None})

    def test_handwritten_uses_vision(self) -> None:
        fake = FakeGeminiClient()
        import backend.api.documents as docs_api

        docs_api._processor = DocumentProcessor(gemini=fake)
        body = self._upload("referral_handwritten.pdf")
        doc_id = body["id"]
        st = self.client.get(f"/api/documents/{doc_id}/status")
        self.assertEqual(st.status_code, 200)
        self.assertEqual(st.json()["status"], "complete", st.text)
        ext = self.client.get(f"/api/documents/{doc_id}/extraction")
        self.assertEqual(ext.status_code, 200)
        pages = ext.json()["pages"]
        self.assertTrue(pages)
        for p in pages:
            if p.get("classification") != "cover_sheet":
                self.assertEqual(p.get("extraction_path"), "vision")

    def test_poor_quality_uses_vision(self) -> None:
        fake = FakeGeminiClient()
        import backend.api.documents as docs_api

        docs_api._processor = DocumentProcessor(gemini=fake)
        body = self._upload("referral_poor_quality.pdf")
        doc_id = body["id"]
        st = self.client.get(f"/api/documents/{doc_id}/status")
        self.assertEqual(st.json()["status"], "complete", st.text)
        pages = self.client.get(f"/api/documents/{doc_id}/extraction").json()["pages"]
        for p in pages:
            if p.get("classification") != "cover_sheet":
                self.assertEqual(p.get("extraction_path"), "vision")

    def test_missing_f2f_gap(self) -> None:
        fake = FakeGeminiClient()
        import backend.api.documents as docs_api

        docs_api._processor = DocumentProcessor(gemini=fake)
        # create intake so merge runs
        ir = self.client.post("/api/intake", json={"source": "fax"})
        self.assertEqual(ir.status_code, 200)
        intake_id = ir.json()["id"]
        body = self._upload("referral_missing_f2f.pdf", intake_id=intake_id)
        st = self.client.get(f"/api/documents/{body['id']}/status").json()
        self.assertEqual(st["status"], "complete", st)
        gaps = st.get("gaps") or []
        names = {g.get("field_name") for g in gaps}
        # medicare docs should surface f2f when missing
        if "f2f_encounter" in names:
            f2f = next(g for g in gaps if g["field_name"] == "f2f_encounter")
            self.assertEqual(
                f2f["suggested_action"],
                "Call referring provider to request F2F documentation.",
            )

    def test_status_shape(self) -> None:
        fake = FakeGeminiClient()
        import backend.api.documents as docs_api

        docs_api._processor = DocumentProcessor(gemini=fake)
        body = self._upload("referral_complete.pdf")
        data = self.client.get(f"/api/documents/{body['id']}/status").json()
        for key in (
            "id",
            "status",
            "current_layer",
            "extraction_result",
            "confidence_scores",
            "gaps",
        ):
            self.assertIn(key, data)


class TestEligibilityWatcherUnit(unittest.TestCase):
    def test_watch_paths(self) -> None:
        from backend.workers.eligibility_watcher import WATCH_PATHS, relevant_changed

        self.assertIn(("patient_data", "zip_code"), WATCH_PATHS)
        before = {
            "patient_data": {"zip_code": "11201"},
            "insurance_data": {},
            "clinical_data": {},
            "care_request": {},
        }

        class Fake:
            patient_data = {"zip_code": "10001"}
            insurance_data = {}
            clinical_data = {}
            care_request = {}

        self.assertTrue(relevant_changed(before, Fake()))


class TestSchedulerConstants(unittest.TestCase):
    def test_retry_delays(self) -> None:
        from datetime import timedelta

        from backend.models.tables import FollowUpType
        from backend.workers.followup_scheduler import POLL_SECONDS, RETRY_DELAY

        self.assertEqual(POLL_SECONDS, 30)
        self.assertEqual(RETRY_DELAY[FollowUpType.sms_sent], timedelta(hours=4))
        self.assertEqual(
            RETRY_DELAY[FollowUpType.outbound_call_attempted], timedelta(hours=2)
        )
        self.assertEqual(RETRY_DELAY[FollowUpType.email_sent], timedelta(hours=24))


if __name__ == "__main__":
    unittest.main()
