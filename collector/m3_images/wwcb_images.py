"""WWCB image extractor – extract satellite/weather/crop images from PDF.

Uses PyMuPDF to extract embedded images from Weekly Weather and Crop
Bulletin PDFs. Classifies images by size heuristic, extracts the
accompanying narrative text from each page, and stores images as
PNG files with a JSON metadata sidecar.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF

from common import manifest
from common.storage import ASSETS_DIR, RAW_DIR, ensure_dirs, sha256_file

log = logging.getLogger(__name__)

SOURCE = "USDA_WWCB_IMAGES"

MIN_WIDTH = 150
MIN_HEIGHT = 150
MIN_FILE_KB = 10

IMAGE_CATEGORIES = {
    "map": {"min_area": 250_000, "max_aspect": 2.5},
    "chart": {"min_area": 40_000, "min_aspect": 1.8},
    "thumbnail": {"min_area": 5_000, "max_area": 250_000},
}


def _classify_image(width: int, height: int, page_num: int, total_pages: int) -> str:
    area = width * height
    aspect = max(width, height) / max(min(width, height), 1)

    if area >= IMAGE_CATEGORIES["map"]["min_area"] and aspect <= IMAGE_CATEGORIES["map"]["max_aspect"]:
        return "map"
    if area >= IMAGE_CATEGORIES["chart"]["min_area"] and aspect >= IMAGE_CATEGORIES["chart"]["min_aspect"]:
        return "chart"
    if area >= IMAGE_CATEGORIES["thumbnail"]["min_area"]:
        return "thumbnail"
    return "icon"


_HEADER_RE = re.compile(
    r"^\s*\d+\s*$|"
    r"^Weekly Weather and Crop Bulletin|"
    r"^\w+ \d+, \d{4}\s*$|"
    r"^Footer text\s*$",
    re.IGNORECASE,
)

REGION_KEYWORDS = [
    "EUROPE", "MIDDLE EAST", "NORTHWESTERN AFRICA", "AUSTRALIA",
    "SOUTH AFRICA", "ARGENTINA", "BRAZIL", "SOUTH ASIA", "EAST ASIA",
    "SOUTHEAST ASIA", "FORMER SOVIET UNION", "CHINA", "CANADA", "MEXICO",
]


def _extract_page_text(page) -> str:
    raw = page.get_text("text")
    lines = raw.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _HEADER_RE.match(stripped):
            continue
        cleaned.append(stripped)
    return "\n".join(cleaned)


MIN_NARRATIVE_CHARS = 100

SEARCH_WINDOW = 2


def _detect_region(text: str) -> str | None:
    upper = text.upper()
    for region in REGION_KEYWORDS:
        if region in upper:
            return region.title()
    if "UNITED STATES" in upper or "U.S." in upper:
        return "United States"
    return None


def _has_narrative(text: str) -> bool:
    narrative_lines = [l for l in text.split("\n") if len(l) > 40]
    return sum(len(l) for l in narrative_lines) >= MIN_NARRATIVE_CHARS


def _find_best_text(page_texts: list[str], page_idx: int) -> tuple[str, str | None, list[int]]:
    """Search current page and adjacent pages for narrative text.

    Returns (combined_text, region, source_pages).
    """
    current = page_texts[page_idx]
    if _has_narrative(current):
        return current, _detect_region(current), [page_idx]

    total = len(page_texts)
    candidates: list[tuple[int, str]] = []

    for offset in range(1, SEARCH_WINDOW + 1):
        for neighbor in (page_idx - offset, page_idx + offset):
            if 0 <= neighbor < total and _has_narrative(page_texts[neighbor]):
                candidates.append((neighbor, page_texts[neighbor]))

    if not candidates:
        return current, _detect_region(current), [page_idx]

    combined_parts = [current] if current.strip() else []
    source_pages = [page_idx] if current.strip() else []
    for idx, text in candidates:
        combined_parts.append(text)
        source_pages.append(idx)

    combined = "\n\n".join(combined_parts)
    region = _detect_region(combined)
    return combined, region, sorted(set(source_pages))


def _images_dir() -> Path:
    return ASSETS_DIR / "wwcb" / "images"


def _metadata_dir() -> Path:
    return ASSETS_DIR / "wwcb" / "metadata"


def _parse_date_from_filename(filename: str) -> str | None:
    """Extract date from WWCB filename like wwcb_20260630.pdf or wwcb_current_20260630.pdf."""
    import re
    m = re.search(r"(\d{8})", filename)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d").strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def extract_images_from_pdf(pdf_path: Path, force: bool = False) -> list[dict]:
    """Extract all meaningful images from a single WWCB PDF.

    Returns a list of metadata dicts for each extracted image.
    """
    images_dir = _images_dir()
    images_dir.mkdir(parents=True, exist_ok=True)

    pdf_date = _parse_date_from_filename(pdf_path.name) or "unknown"
    pdf_stem = pdf_path.stem

    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)
    extracted = []
    seen_xrefs = set()

    page_texts = [_extract_page_text(doc[i]) for i in range(total_pages)]

    for page_num in range(total_pages):
        page = doc[page_num]
        image_list = page.get_images(full=True)

        if not image_list:
            continue

        best_text, page_region, text_sources = _find_best_text(page_texts, page_num)

        for img_idx, img_info in enumerate(image_list):
            xref = img_info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)

            try:
                base_image = doc.extract_image(xref)
            except Exception:
                log.debug("WWCB_IMG: failed to extract xref %d from %s", xref, pdf_path.name)
                continue

            if not base_image or not base_image.get("image"):
                continue

            width = base_image.get("width", 0)
            height = base_image.get("height", 0)

            if width < MIN_WIDTH or height < MIN_HEIGHT:
                continue

            file_size_kb = len(base_image["image"]) / 1024
            if file_size_kb < MIN_FILE_KB:
                log.debug("WWCB_IMG: skipping xref %d (%.1fKB < %dKB min)", xref, file_size_kb, MIN_FILE_KB)
                continue

            ext = base_image.get("ext", "png")
            if ext not in ("png", "jpeg", "jpg"):
                ext = "png"

            category = _classify_image(width, height, page_num, total_pages)
            if category == "icon":
                continue

            img_filename = f"{pdf_stem}_p{page_num+1:03d}_x{xref}.{ext}"
            img_path = images_dir / img_filename

            if img_path.exists() and not force:
                meta = _load_existing_meta(img_path)
                if meta:
                    extracted.append(meta)
                    continue

            img_path.write_bytes(base_image["image"])

            meta = {
                "filename": img_filename,
                "path": str(img_path),
                "source_pdf": pdf_path.name,
                "pdf_date": pdf_date,
                "page": page_num + 1,
                "total_pages": total_pages,
                "xref": xref,
                "width": width,
                "height": height,
                "area": width * height,
                "aspect_ratio": round(max(width, height) / max(min(width, height), 1), 2),
                "category": category,
                "format": ext,
                "file_size_kb": round(len(base_image["image"]) / 1024, 1),
                "region": page_region,
                "page_text": best_text,
                "text_source_pages": [p + 1 for p in text_sources],
                "extracted_at": datetime.utcnow().isoformat(),
            }
            extracted.append(meta)
            log.debug(
                "WWCB_IMG: %s → %s (%dx%d, %s, %.1fKB)",
                pdf_path.name, img_filename, width, height,
                category, meta["file_size_kb"],
            )

    doc.close()
    return extracted


def _load_existing_meta(img_path: Path) -> dict | None:
    meta_path = _metadata_dir() / (img_path.stem + ".json")
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _save_metadata(all_meta: list[dict], pdf_name: str) -> Path:
    """Save per-PDF metadata as a JSON file."""
    meta_dir = _metadata_dir()
    meta_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(pdf_name).stem
    meta_path = meta_dir / f"{stem}_images.json"
    meta_path.write_text(
        json.dumps(all_meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return meta_path


def _save_summary(all_results: dict[str, list[dict]]) -> Path:
    """Save a combined summary across all PDFs."""
    meta_dir = _metadata_dir()
    meta_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "generated_at": datetime.utcnow().isoformat(),
        "total_pdfs": len(all_results),
        "total_images": sum(len(v) for v in all_results.values()),
        "by_category": {},
        "pdfs": {},
    }

    all_images = []
    for pdf_name, images in all_results.items():
        summary["pdfs"][pdf_name] = {
            "image_count": len(images),
            "categories": {},
        }
        for img in images:
            cat = img.get("category", "unknown")
            summary["by_category"][cat] = summary["by_category"].get(cat, 0) + 1
            summary["pdfs"][pdf_name]["categories"][cat] = (
                summary["pdfs"][pdf_name]["categories"].get(cat, 0) + 1
            )
            all_images.append(img)

    summary["images"] = all_images

    summary_path = meta_dir / "wwcb_images_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return summary_path


def collect(since: int = 2010, force: bool = False) -> None:
    """Extract images from all downloaded WWCB PDFs."""
    ensure_dirs()
    raw_dir = RAW_DIR / "wwcb"

    if not raw_dir.exists():
        log.warning("WWCB_IMG: no raw PDFs found — run wwcb collector first")
        return

    pdf_files = sorted(raw_dir.glob("*.pdf"))
    if not pdf_files:
        log.warning("WWCB_IMG: no PDF files in %s", raw_dir)
        return

    log.info("WWCB_IMG: found %d PDFs to process", len(pdf_files))

    all_results: dict[str, list[dict]] = {}
    total_extracted = 0

    for pdf_path in pdf_files:
        try:
            images = extract_images_from_pdf(pdf_path, force=force)
            if images:
                _save_metadata(images, pdf_path.name)
                all_results[pdf_path.name] = images
                total_extracted += len(images)
                log.info("WWCB_IMG: %s → %d images", pdf_path.name, len(images))
            else:
                log.info("WWCB_IMG: %s → no extractable images", pdf_path.name)
        except Exception:
            log.exception("WWCB_IMG: failed to process %s", pdf_path.name)

    if all_results:
        summary_path = _save_summary(all_results)
        manifest.upsert(
            source=SOURCE,
            artifact_type="image_metadata",
            period=f"summary",
            path=summary_path,
            sha256=sha256_file(summary_path),
        )
        log.info(
            "WWCB_IMG: extracted %d images from %d PDFs → %s",
            total_extracted, len(all_results), summary_path,
        )
    else:
        log.warning("WWCB_IMG: no images extracted from any PDF")
