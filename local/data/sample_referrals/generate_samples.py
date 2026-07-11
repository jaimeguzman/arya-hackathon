"""Generate synthetic sample referral PDFs for Phase 4 tests."""

from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

OUT = Path(__file__).resolve().parent


def _text_pdf(path: Path, lines: list[str]) -> None:
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=11)
        y += 16
    doc.save(path)
    doc.close()


def _sparse_pdf(path: Path, marker: str = ".") -> None:
    """Nearly empty text layer → is_digital False (<20 alnum)."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), marker, fontsize=8)
    doc.save(path)
    doc.close()


def main() -> None:
    _text_pdf(
        OUT / "referral_complete.pdf",
        [
            "ABC Home Health Referral — Discharge Summary",
            "Patient Name: Maria L. Johnson",
            "DOB: 03/15/1948",
            "Zip: 11201",
            "Payer: Medicare",
            "Plan Name: Medicare Part A",
            "Member ID: 1EG4TE5MK72",
            "Diagnosis ICD: Z96.641",
            "Physician: Dr. Sarah Chen",
            "NPI: 1234567893",
            "Discharge Date: 06/01/2026",
            "Face-to-Face Encounter: documented 05/28/2026",
            "Physician Orders: SN + PT signed",
            "Homebound Status: yes",
            "Facility: Brooklyn Methodist Hospital",
        ],
    )
    _text_pdf(
        OUT / "referral_missing_f2f.pdf",
        [
            "Referral Packet — Missing F2F",
            "Patient Name: John Rivera",
            "DOB: 01/02/1955",
            "Zip: 11201",
            "Payer: Medicare",
            "Plan Name: Medicare Part A",
            "ICD: Z96.641",
            "Physician: Dr. Amy Park",
            "Facility: NYU Langone",
            "Note: Face-to-face encounter documentation not attached",
        ],
    )
    _sparse_pdf(OUT / "referral_handwritten.pdf", ".")
    _sparse_pdf(OUT / "referral_poor_quality.pdf", "..")
    print("Wrote sample PDFs to", OUT)


if __name__ == "__main__":
    main()
