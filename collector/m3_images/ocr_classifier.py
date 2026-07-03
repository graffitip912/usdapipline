"""Stage 3: Tesseract OCR text extraction and content classification.

Gracefully degrades when Tesseract is not installed — logs a warning
and skips OCR, allowing stages 1-2 to operate independently.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

_tesseract_available: bool | None = None

# USER-CONFIG: OCR classification keywords (case-insensitive)
CLASSIFICATION_KEYWORDS: dict[str, list[str]] = {
    "satellite": ["satellite", "NDVI", "vegetation index", "normalized difference"],
    "weather_map": [
        "drought monitor", "precipitation", "departure from normal",
        "temperature", "forecast", "outlook", "moisture", "snow cover",
        "soil moisture", "Palmer",
    ],
    "chart": ["percent", "bushels", "tons", "acres", "million", "billion", "index"],
}

# USER-CONFIG: minimum OCR text length to attempt classification
MIN_OCR_TEXT_LENGTH = 10


def _check_tesseract() -> bool:
    global _tesseract_available
    if _tesseract_available is not None:
        return _tesseract_available
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        _tesseract_available = True
        log.debug("Tesseract OCR available")
    except Exception:
        _tesseract_available = False
        log.warning(
            "Tesseract not installed or not in PATH — OCR stage will be skipped. "
            "Install: https://github.com/tesseract-ocr/tesseract"
        )
    return _tesseract_available


def extract_ocr_text(image_path: Path) -> str:
    """Extract text from image using Tesseract. Returns empty string on failure."""
    if not _check_tesseract():
        return ""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img, lang="eng")
        return text.strip()
    except Exception:
        log.debug("OCR failed for %s", image_path.name)
        return ""


def classify_by_ocr(ocr_text: str) -> str:
    """Classify image content based on OCR-extracted text.

    Returns one of: 'satellite', 'weather_map', 'chart', 'unknown'.
    """
    if not ocr_text or len(ocr_text) < MIN_OCR_TEXT_LENGTH:
        return "unknown"

    text_lower = ocr_text.lower()
    scores: dict[str, int] = {}

    for category, keywords in CLASSIFICATION_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text_lower)
        if score > 0:
            scores[category] = score

    if not scores:
        return "unknown"

    return max(scores, key=scores.get)


def extract_section_header(page_text: str) -> str | None:
    """Detect the nearest section header from page text.

    Looks for capitalized or bold-style headings that indicate content sections.
    """
    if not page_text:
        return None

    lines = page_text.split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped or len(stripped) < 3:
            continue
        if len(stripped) > 100:
            continue
        if stripped.isupper() and len(stripped) > 5:
            return stripped
        if re.match(r"^[A-Z][A-Za-z\s,&-]+$", stripped) and len(stripped) < 60:
            return stripped
    return None


def parse_wwcb_toc(page1_text: str) -> dict[int, str]:
    """Parse Table of Contents from WWCB PDF page 1.

    Returns {page_number: section_title} mapping.
    """
    toc: dict[int, str] = {}
    lines = page1_text.split("\n")

    in_contents = False
    content_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.lower() == "contents":
            in_contents = True
            continue
        if in_contents:
            if "WEEKLY WEATHER" in stripped or "HIGHLIGHTS" in stripped:
                break
            if stripped:
                content_lines.append(stripped)

    buffer = ""
    for line in content_lines:
        match = re.search(r"\.{2,}\s*(\d+)\s*$", line)
        if match:
            page_num = int(match.group(1))
            title = re.sub(r"\s*\.{2,}\s*\d+\s*$", "", buffer + " " + line).strip()
            title = re.sub(r"\s+", " ", title)
            if title and page_num > 0:
                toc[page_num] = title
            buffer = ""
        else:
            buffer += " " + line if buffer else line

    return toc


def lookup_toc_section(toc: dict[int, str], page: int) -> str | None:
    """Find the TOC section title for a given page number.

    Uses the nearest preceding TOC entry (sections span multiple pages).
    """
    if not toc:
        return None
    candidates = [p for p in toc if p <= page]
    if not candidates:
        return None
    return toc[max(candidates)]
