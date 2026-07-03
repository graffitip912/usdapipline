"""WWCB image extractor — 4-stage filtering pipeline.

Stage 1: Rule-based filter (size, aspect ratio, page position, keywords)
Stage 2: Perceptual hash blocklist (imagehash)
Stage 3: Tesseract OCR classification (satellite, weather_map, chart, unknown)
Stage 4: Manual curation via curation.json

Uses PyMuPDF to extract embedded images from Weekly Weather and Crop
Bulletin PDFs. Stores images as PNG files with JSON metadata sidecars.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF

from common import manifest
from common.data_access import get_backend
from common.storage import sha256_file

from collector.m3_images.image_filter import (
    HashFilter,
    apply_filters,
    init_curation,
)
from collector.m3_images.ocr_classifier import (
    classify_by_ocr,
    extract_ocr_text,
    extract_section_header,
    lookup_toc_section,
    parse_wwcb_toc,
)

log = logging.getLogger(__name__)

SOURCE = "USDA_WWCB_IMAGES"

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

# USER-CONFIG: minimum narrative text length for page text extraction
MIN_NARRATIVE_CHARS = 100

# USER-CONFIG: number of adjacent pages to search for narrative text
SEARCH_WINDOW = 2


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


def _parse_date_from_filename(filename: str) -> str | None:
    m = re.search(r"(\d{8})", filename)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d").strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def extract_images_from_pdf(pdf_path: Path, force: bool = False) -> list[dict]:
    """Extract all meaningful images from a single WWCB PDF through the 4-stage pipeline."""
    backend = get_backend()
    data_dir = Path(backend.resolve_path(""))

    images_rel = "assets/wwcb/images"
    metadata_rel = "assets/wwcb/metadata"
    backend.ensure_dir(images_rel)
    backend.ensure_dir(metadata_rel)

    curation = init_curation(data_dir)
    images_dir = Path(backend.resolve_path(images_rel))

    pdf_date = _parse_date_from_filename(pdf_path.name) or "unknown"
    pdf_stem = pdf_path.stem

    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)
    extracted = []
    filtered_out = []
    seen_xrefs = set()

    page_texts = [_extract_page_text(doc[i]) for i in range(total_pages)]
    toc = parse_wwcb_toc(page_texts[0]) if page_texts else {}

    for page_num in range(total_pages):
        page = doc[page_num]
        image_list = page.get_images(full=True)

        if not image_list:
            continue

        best_text, page_region, text_sources = _find_best_text(page_texts, page_num)
        section_header = extract_section_header(page_texts[page_num])
        toc_section = lookup_toc_section(toc, page_num + 1)

        for img_idx, img_info in enumerate(image_list):
            xref = img_info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)

            try:
                base_image = doc.extract_image(xref)
            except Exception:
                log.debug("Failed to extract xref %d from %s", xref, pdf_path.name)
                continue

            if not base_image or not base_image.get("image"):
                continue

            width = base_image.get("width", 0)
            height = base_image.get("height", 0)

            ext = base_image.get("ext", "png")
            if ext not in ("png", "jpeg", "jpg"):
                ext = "png"

            img_filename = f"{pdf_stem}_p{page_num+1:03d}_x{xref}.{ext}"
            img_path = images_dir / img_filename

            pre_filter_meta = {
                "filename": img_filename,
                "width": width,
                "height": height,
                "file_size_kb": round(len(base_image["image"]) / 1024, 1),
                "page": page_num + 1,
                "page_text": best_text,
            }

            filter_result = apply_filters(img_path if img_path.exists() else pdf_path, pre_filter_meta, data_dir)

            if not filter_result.keep:
                filtered_out.append({
                    "filename": img_filename,
                    "filter_stage": filter_result.stage,
                    "filter_reason": filter_result.reason,
                })
                log.debug("Filtered: %s — %s (%s)", img_filename, filter_result.reason, filter_result.stage)
                continue

            if not img_path.exists() or force:
                img_path.write_bytes(base_image["image"])

            ocr_text = extract_ocr_text(img_path)
            ocr_category = classify_by_ocr(ocr_text)

            hash_filter = HashFilter(curation.get("blocklist_hashes", []))
            img_hash = hash_filter.compute_hash(img_path)

            meta = {
                "id": img_path.stem,
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
                "category": ocr_category if ocr_category != "unknown" else _classify_by_size(width, height),
                "format": ext,
                "file_size_kb": round(len(base_image["image"]) / 1024, 1),
                "region": page_region,
                "page_text": best_text,
                "ocr_text": ocr_text,
                "section_header": section_header,
                "toc_section": toc_section,
                "text_source_pages": [p + 1 for p in text_sources],
                "filter_stage": filter_result.stage,
                "filter_reason": filter_result.reason,
                "phash": img_hash,
                "extracted_at": datetime.utcnow().isoformat(),
            }
            extracted.append(meta)
            log.debug(
                "%s → %s (%dx%d, %s, %.1fKB, ocr=%s)",
                pdf_path.name, img_filename, width, height,
                meta["category"], meta["file_size_kb"], ocr_category,
            )

    doc.close()

    if filtered_out:
        log.info(
            "%s: %d extracted, %d filtered out",
            pdf_path.name, len(extracted), len(filtered_out),
        )

    return extracted


def _classify_by_size(width: int, height: int) -> str:
    area = width * height
    aspect = max(width, height) / max(min(width, height), 1)
    if area >= 250_000 and aspect <= 2.5:
        return "map"
    if area >= 40_000 and aspect >= 1.8:
        return "chart"
    if area >= 5_000:
        return "thumbnail"
    return "icon"


def _save_metadata(all_meta: list[dict], pdf_name: str) -> Path:
    backend = get_backend()
    meta_dir = Path(backend.resolve_path("assets/wwcb/metadata"))
    meta_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(pdf_name).stem
    meta_path = meta_dir / f"{stem}_images.json"
    meta_path.write_text(
        json.dumps(all_meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return meta_path


def _save_summary(all_results: dict[str, list[dict]]) -> Path:
    backend = get_backend()
    meta_dir = Path(backend.resolve_path("assets/wwcb/metadata"))
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
    """Extract images from all downloaded WWCB PDFs through the 4-stage pipeline."""
    backend = get_backend()
    raw_dir = Path(backend.resolve_path("raw/wwcb"))

    if not raw_dir.exists():
        log.warning("No raw PDFs found — run wwcb collector first")
        return

    pdf_files = sorted(raw_dir.glob("*.pdf"))
    if not pdf_files:
        log.warning("No PDF files in %s", raw_dir)
        return

    log.info("Found %d PDFs to process", len(pdf_files))

    all_results: dict[str, list[dict]] = {}
    total_extracted = 0

    for pdf_path in pdf_files:
        try:
            images = extract_images_from_pdf(pdf_path, force=force)
            if images:
                _save_metadata(images, pdf_path.name)
                all_results[pdf_path.name] = images
                total_extracted += len(images)
                log.info("%s → %d images", pdf_path.name, len(images))
            else:
                log.info("%s → no extractable images", pdf_path.name)
        except Exception:
            log.exception("Failed to process %s", pdf_path.name)

    if all_results:
        summary_path = _save_summary(all_results)
        manifest.upsert(
            source=SOURCE,
            artifact_type="image_metadata",
            period="summary",
            path=summary_path,
            sha256=sha256_file(summary_path),
        )
        log.info(
            "Extracted %d images from %d PDFs → %s",
            total_extracted, len(all_results), summary_path,
        )
    else:
        log.warning("No images extracted from any PDF")
