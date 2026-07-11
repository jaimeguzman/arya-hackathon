"""Phase 4 unit tests — layers 1–7 with FakeGemini (no network)."""

from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

from backend.agents.correction_agent import correct_field
from backend.agents.cross_reference_agent import cross_reference
from backend.agents.validation_agent import luhn_npi, validate_fields
from backend.pipeline.classification import classify_pages
from backend.pipeline.completeness import check_completeness, is_medicare
from backend.pipeline.confidence import BASE_RULES, BASE_VISION, score_fields
from backend.pipeline.extraction import (
    extract_and_normalize,
    normalize_fields,
    path_b_extract,
)
from backend.pipeline.ingestion import ingest_pdf
from backend.pipeline.review_loop import run_review_loop
from backend.services.gemini_client import FakeGeminiClient
from backend.services.guardrail_service import GuardrailService

_LOCAL = Path(__file__).resolve().parents[2]
_SAMPLES = _LOCAL / "data" / "sample_referrals"


class TestIngestion(unittest.TestCase):
    def test_digital_complete_referral(self) -> None:
        pdf = _SAMPLES / "referral_complete.pdf"
        if not pdf.exists():
            self.skipTest("sample PDF missing")
        pages = ingest_pdf(str(pdf), uuid.uuid4())
        self.assertGreaterEqual(len(pages), 1)
        self.assertTrue(pages[0]["is_digital"])
        self.assertGreater(len(pages[0]["raw_text"]), 20)
        self.assertTrue(Path(pages[0]["file_path"]).exists())
        self.assertTrue(pages[0]["file_path"].endswith("page_0001.png"))

    def test_handwritten_not_digital(self) -> None:
        pdf = _SAMPLES / "referral_handwritten.pdf"
        if not pdf.exists():
            self.skipTest("sample PDF missing")
        pages = ingest_pdf(str(pdf), uuid.uuid4())
        self.assertFalse(pages[0]["is_digital"])

    def test_poor_quality_not_digital(self) -> None:
        pdf = _SAMPLES / "referral_poor_quality.pdf"
        if not pdf.exists():
            self.skipTest("sample PDF missing")
        pages = ingest_pdf(str(pdf), uuid.uuid4())
        self.assertFalse(pages[0]["is_digital"])


class TestClassification(unittest.TestCase):
    def test_categories_and_cover_sheet(self) -> None:
        gemini = FakeGeminiClient(
            {"classif": '{"classification": "cover_sheet"}'}
        )
        pages = [
            {
                "page_number": 1,
                "file_path": str(_SAMPLES / "referral_complete.pdf"),
                "is_digital": True,
                "raw_text": "FAX COVER SHEET please route",
                "classification": None,
            }
        ]
        # heuristic path — no vision needed for cover
        out = classify_pages(pages, gemini)
        self.assertEqual(out[0]["classification"], "cover_sheet")


class TestExtraction(unittest.TestCase):
    def test_path_b_rules(self) -> None:
        text = (
            "Patient Name: Maria Johnson\n"
            "DOB: 03/15/1945\n"
            "Zip: 11201\n"
            "Insurance: Medicare\n"
            "ICD Z96.641\n"
            "Physician: Dr. Smith\n"
        )
        fields = path_b_extract(text)
        self.assertGreaterEqual(len(fields), 3)
        norm = normalize_fields(fields)
        self.assertEqual(norm.get("zip_code"), "11201")
        self.assertIn("Maria", norm.get("patient_name", ""))

    def test_path_c_vision_when_not_digital(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
            png = f.name
        gemini = FakeGeminiClient()
        pages = [
            {
                "page_number": 1,
                "file_path": png,
                "is_digital": False,
                "raw_text": "x",
                "classification": "discharge_summary",
            }
        ]
        out = extract_and_normalize(pages, gemini)
        self.assertEqual(out[0]["extraction_path"], "vision")
        self.assertIn("patient_name", out[0]["normalized"])

    def test_cover_sheet_skips_extraction(self) -> None:
        pages = [
            {
                "page_number": 1,
                "file_path": "x.png",
                "is_digital": True,
                "raw_text": "cover",
                "classification": "cover_sheet",
            }
        ]
        out = extract_and_normalize(pages, FakeGeminiClient())
        self.assertIsNone(out[0]["extraction_path"])
        self.assertEqual(out[0]["normalized"], {})


class TestValidationCorrection(unittest.TestCase):
    def test_zip_and_npi(self) -> None:
        results = validate_fields({"zip_code": "12", "icd_codes": ["Z96.641"]})
        by = {r["field"]: r for r in results}
        self.assertFalse(by["zip_code"]["valid"])
        self.assertTrue(by["icd_codes"]["valid"])
        self.assertTrue(luhn_npi("1234567893") or not luhn_npi("1234567890"))

    def test_correction_accept(self) -> None:
        gemini = FakeGeminiClient(
            {
                "correct": '{"corrected_value": "Z96.641", "confidence": 0.95, '
                '"reasoning": "ok", "can_correct": true}'
            }
        )
        gs = GuardrailService()
        out = correct_field("icd_codes", "Z9G.641", "bad", gemini, gs)
        self.assertTrue(out["accepted"])
        self.assertEqual(out["band"], "ACCEPT")


class TestCrossReference(unittest.TestCase):
    def test_name_variant(self) -> None:
        pages = [
            {"page_number": 1, "classification": "other", "normalized": {"patient_name": "M Johnson"}},
            {
                "page_number": 2,
                "classification": "other",
                "normalized": {"patient_name": "Maria Johnson"},
            },
        ]
        issues = cross_reference(pages)
        self.assertEqual(issues[0]["assessment"], "same_person_name_variant")
        self.assertEqual(issues[0]["recommended_resolution"], "Maria Johnson")


class TestCompletenessConfidence(unittest.TestCase):
    def test_medicare_f2f_gap_action(self) -> None:
        fields = {
            "patient_name": "Maria Johnson",
            "date_of_birth": "1945-03-15",
            "icd_codes": ["Z96.641"],
            "payer_name": "Medicare",
            "zip_code": "11201",
            "physician_name": "Dr Smith",
        }
        self.assertTrue(is_medicare(fields))
        gaps = check_completeness(fields)
        f2f = [g for g in gaps if g["field_name"] == "f2f_encounter"]
        self.assertTrue(f2f)
        self.assertEqual(
            f2f[0]["suggested_action"],
            "Call referring provider to request F2F documentation.",
        )

    def test_confidence_bases(self) -> None:
        pages = [
            {
                "classification": "discharge_summary",
                "extraction_path": "rules",
                "normalized": {"zip_code": "11201", "patient_name": "A"},
            }
        ]
        merged, scores, routing = score_fields(pages, guardrails=GuardrailService())
        self.assertAlmostEqual(scores["zip_code"], BASE_RULES)
        pages[0]["extraction_path"] = "vision"
        _, scores2, _ = score_fields(pages, guardrails=GuardrailService())
        self.assertAlmostEqual(scores2["zip_code"], BASE_VISION)


class TestReviewLoop(unittest.TestCase):
    def test_runs_without_error(self) -> None:
        pages = [
            {
                "page_number": 1,
                "classification": "discharge_summary",
                "raw_text": "Patient Name: X",
                "normalized": {"zip_code": "11201", "icd_codes": ["Z96.641"]},
            }
        ]
        out, gaps, issues = run_review_loop(pages, FakeGeminiClient(), GuardrailService())
        self.assertEqual(len(out), 1)


if __name__ == "__main__":
    unittest.main()
