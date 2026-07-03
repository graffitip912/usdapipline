"""Curated dataset management for ML-ready image-text data.

Imports curation decisions from the curation tool and generates
structured datasets in data/curated/wwcb_images/.

Output structure:
  data/curated/wwcb_images/
    dataset.jsonl       — one record per approved/edited image
    metadata.json       — dataset stats, schema, version
    excluded.jsonl      — excluded images for audit trail
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common.data_access import get_backend

log = logging.getLogger(__name__)

# USER-CONFIG: curated dataset base path (relative to data root)
_CURATED_REL = "curated/wwcb_images"


def _resolve_dir() -> Path:
    backend = get_backend()
    p = Path(backend.resolve_path(_CURATED_REL))
    p.mkdir(parents=True, exist_ok=True)
    return p


def import_curation_decisions(
    decisions: list[dict[str, Any]],
    curator: str = "user",
) -> dict[str, Any]:
    """Import curation decisions and generate ML-ready dataset files.

    Args:
        decisions: list of dicts from curation tool JSON export.
            Each must have: filename, status, description.
            Optional: source_pdf, page, category, region, toc_section.
        curator: identifier for who made the decisions.

    Returns:
        Summary dict with counts and output paths.
    """
    out_dir = _resolve_dir()
    backend = get_backend()
    now = datetime.now(timezone.utc).isoformat()

    approved = []
    excluded = []

    for item in decisions:
        status = item.get("status", "pending")
        if status in ("approved", "edited"):
            record = _build_ml_record(item, curator, now)
            approved.append(record)
        elif status == "excluded":
            excluded.append({
                "filename": item.get("filename", ""),
                "reason": "user_excluded",
                "excluded_at": now,
                "excluded_by": curator,
            })

    dataset_path = out_dir / "dataset.jsonl"
    _write_jsonl(dataset_path, approved)

    excluded_path = out_dir / "excluded.jsonl"
    _write_jsonl(excluded_path, excluded)

    # Category/label distribution for ML reference
    label_dist: dict[str, int] = {}
    region_dist: dict[str, int] = {}
    section_dist: dict[str, int] = {}
    for r in approved:
        label_dist[r["category"]] = label_dist.get(r["category"], 0) + 1
        region_dist[r["region"]] = region_dist.get(r["region"], 0) + 1
        section_dist[r["toc_section"]] = section_dist.get(r["toc_section"], 0) + 1

    metadata = {
        "dataset": "wwcb_images_curated",
        "version": "1.0.0",
        "created_at": now,
        "curator": curator,
        "schema": {
            "format": "jsonl",
            "fields": {
                "image_path": "relative path from data root to image file",
                "description": "user-curated image description",
                "category": "image type: map | chart | thumbnail | satellite | weather_map",
                "region": "geographic region depicted",
                "toc_section": "PDF table-of-contents section title",
                "source_pdf": "origin PDF filename",
                "pdf_date": "publication date of source PDF",
                "page": "page number in source PDF",
                "ocr_text": "Tesseract OCR extracted text (if available)",
                "curation_status": "approved or edited",
                "curated_at": "ISO timestamp of curation",
                "curated_by": "curator identifier",
            },
            "ml_usage": {
                "captioning": "image_path + description",
                "classification": "image_path + category + region",
                "retrieval": "image_path + description + toc_section",
                "multi_label": "image_path + category + region + toc_section",
            },
        },
        "stats": {
            "total_approved": len(approved),
            "total_excluded": len(excluded),
            "total_decisions": len(decisions),
            "pending": len(decisions) - len(approved) - len(excluded),
            "label_distribution": label_dist,
            "region_distribution": region_dist,
            "section_distribution": section_dist,
        },
    }

    meta_path = out_dir / "metadata.json"
    meta_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    log.info(
        "Curated dataset: %d approved, %d excluded → %s",
        len(approved), len(excluded), out_dir,
    )

    return {
        "approved": len(approved),
        "excluded": len(excluded),
        "dataset_path": str(dataset_path),
        "excluded_path": str(excluded_path),
        "metadata_path": str(meta_path),
    }


def _build_ml_record(item: dict, curator: str, timestamp: str) -> dict:
    filename = item.get("filename", "")
    return {
        "image_path": f"assets/wwcb/images/{filename}",
        "description": item.get("description", ""),
        "category": item.get("category", "unknown"),
        "region": item.get("region", ""),
        "toc_section": item.get("toc_section", ""),
        "source_pdf": item.get("source_pdf", ""),
        "pdf_date": item.get("pdf_date", ""),
        "page": item.get("page", 0),
        "ocr_text": item.get("ocr_text", ""),
        "curation_status": item.get("status", "approved"),
        "curated_at": timestamp,
        "curated_by": curator,
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_curated_dataset(split: str | None = None) -> list[dict]:
    """Load the curated dataset records.

    Args:
        split: reserved for future train/val/test splits.

    Returns:
        List of ML-ready record dicts.
    """
    out_dir = _resolve_dir()
    dataset_path = out_dir / "dataset.jsonl"
    if not dataset_path.exists():
        return []
    records = []
    with open(dataset_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def get_curation_metadata() -> dict | None:
    """Load curation metadata (stats, schema, version)."""
    out_dir = _resolve_dir()
    meta_path = out_dir / "metadata.json"
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text(encoding="utf-8"))
