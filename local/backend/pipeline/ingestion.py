# ponytail: grayscale only — ceiling: no deskew/OpenCV; upgrade: adaptive preprocess
"""Layer 1 — PDF ingestion & page image render."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from uuid import UUID

import fitz
from PIL import Image

logger = logging.getLogger(__name__)
_LOCAL = Path(__file__).resolve().parents[2]
PAGE_CEILING = 200


def ingest_pdf(file_path: str, document_id: UUID) -> list[dict[str, Any]]:
    path = Path(file_path)
    doc = fitz.open(path)
    n = doc.page_count
    if n > PAGE_CEILING:
        logger.warning("page_count %s exceeds ceiling %s — truncating", n, PAGE_CEILING)
        n = PAGE_CEILING

    out_dir = _LOCAL / "uploads" / "pages" / str(document_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    pages: list[dict[str, Any]] = []

    for i in range(n):
        page = doc.load_page(i)
        raw_text = page.get_text("text") or ""
        alnum = len(re.findall(r"[A-Za-z0-9]", raw_text))
        is_digital = alnum > 20

        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        png_path = out_dir / f"page_{i + 1:04d}.png"
        pix.save(str(png_path))

        # grayscale
        img = Image.open(png_path).convert("L")
        img.save(png_path)

        pages.append(
            {
                "page_number": i + 1,
                "file_path": str(png_path),
                "is_digital": is_digital,
                "raw_text": raw_text,
                "classification": None,
                "extraction_path": None,
                "raw_extraction": {},
                "normalized": {},
            }
        )
    doc.close()
    return pages
