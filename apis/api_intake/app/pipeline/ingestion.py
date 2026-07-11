"""Layer 1 — Ingestion and preprocessing.

Standardizes an incoming fax (PDF or TIFF) into per-page records:
- digital-text pages keep their extracted text layer,
- scanned-image pages are rendered and cleaned up (deskew, denoise,
  contrast enhancement) for the downstream OCR/vision path.

Spec: app_spec.txt <document_pipeline><layer number="1">.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageFilter, ImageOps

# A page whose text layer has at least this many non-whitespace characters is
# treated as digital-text; below it the page is treated as a scanned image.
DIGITAL_TEXT_MIN_CHARS = 25

# Rendering resolution for scanned pages (72 dpi base * scale = 144 dpi).
RENDER_SCALE = 2.0

# Deskew search: try rotations in [-MAX_DESKEW_DEGREES, +MAX_DESKEW_DEGREES]
# at DESKEW_STEP_DEGREES increments and keep the angle that maximizes the
# variance of horizontal projection profiles (text lines align -> high variance).
MAX_DESKEW_DEGREES = 5.0
DESKEW_STEP_DEGREES = 1.0

# Median filter kernel size used for denoising scanned pages.
DENOISE_KERNEL_SIZE = 3

# Downsample width used only while estimating the skew angle (speed).
DESKEW_ESTIMATE_WIDTH = 400

PAGE_TYPE_DIGITAL_TEXT = "digital-text"
PAGE_TYPE_SCANNED_IMAGE = "scanned-image"

SUPPORTED_EXTENSIONS = {".pdf", ".tif", ".tiff"}

CLEANUP_STEPS = ("deskew", "denoise", "contrast")


@dataclass
class IngestedPage:
    """One standardized page produced by Layer 1."""

    page_number: int  # 1-based
    page_type: str  # PAGE_TYPE_DIGITAL_TEXT | PAGE_TYPE_SCANNED_IMAGE
    text: str  # extracted text layer ("" for scanned pages)
    image: Image.Image | None  # cleaned page image (None for digital-text pages)
    cleanup_applied: tuple[str, ...]  # cleanup steps applied, in order


def _row_profile_variance(image: Image.Image) -> float:
    """Variance of per-row darkness sums; higher when text lines are level."""
    grayscale = image.convert("L")
    width, height = grayscale.size
    pixels = list(grayscale.getdata())
    row_sums = [
        sum(pixels[row * width : (row + 1) * width]) for row in range(height)
    ]
    mean = sum(row_sums) / len(row_sums)
    return sum((value - mean) ** 2 for value in row_sums) / len(row_sums)


def estimate_skew_angle(image: Image.Image) -> float:
    """Estimate the page skew angle in degrees via projection profiles."""
    if image.width > DESKEW_ESTIMATE_WIDTH:
        ratio = DESKEW_ESTIMATE_WIDTH / image.width
        sample = image.resize(
            (DESKEW_ESTIMATE_WIDTH, max(1, round(image.height * ratio)))
        )
    else:
        sample = image

    best_angle = 0.0
    best_variance = _row_profile_variance(sample)
    angle = -MAX_DESKEW_DEGREES
    while angle <= MAX_DESKEW_DEGREES:
        if angle != 0.0:
            rotated = sample.rotate(angle, expand=False, fillcolor=255)
            variance = _row_profile_variance(rotated)
            if variance > best_variance:
                best_variance = variance
                best_angle = angle
        angle += DESKEW_STEP_DEGREES
    return best_angle


def cleanup_page_image(image: Image.Image) -> Image.Image:
    """Apply the Layer 1 cleanup steps: deskew, denoise, contrast."""
    grayscale = image.convert("L")
    skew = estimate_skew_angle(grayscale)
    if skew != 0.0:
        grayscale = grayscale.rotate(skew, expand=False, fillcolor=255)
    denoised = grayscale.filter(ImageFilter.MedianFilter(DENOISE_KERNEL_SIZE))
    return ImageOps.autocontrast(denoised)


def classify_page_text(text: str) -> str:
    """Tag a page digital-text vs scanned-image from its text layer."""
    if len("".join(text.split())) >= DIGITAL_TEXT_MIN_CHARS:
        return PAGE_TYPE_DIGITAL_TEXT
    return PAGE_TYPE_SCANNED_IMAGE


def ingest_document(path: str | Path) -> list[IngestedPage]:
    """Standardize a PDF/TIFF fax into cleaned, typed per-page records."""
    source = Path(path)
    extension = source.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported document type '{extension}'; "
            f"expected one of {sorted(SUPPORTED_EXTENSIONS)}"
        )
    if not source.exists():
        raise FileNotFoundError(str(source))

    pages: list[IngestedPage] = []
    with fitz.open(source) as document:
        for index, page in enumerate(document):
            text = page.get_text().strip()
            page_type = classify_page_text(text)
            if page_type == PAGE_TYPE_DIGITAL_TEXT:
                pages.append(
                    IngestedPage(
                        page_number=index + 1,
                        page_type=page_type,
                        text=text,
                        image=None,
                        cleanup_applied=(),
                    )
                )
                continue
            matrix = fitz.Matrix(RENDER_SCALE, RENDER_SCALE)
            pixmap = page.get_pixmap(matrix=matrix, colorspace=fitz.csGRAY)
            raw = Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples)
            pages.append(
                IngestedPage(
                    page_number=index + 1,
                    page_type=page_type,
                    text="",
                    image=cleanup_page_image(raw),
                    cleanup_applied=CLEANUP_STEPS,
                )
            )
    return pages
