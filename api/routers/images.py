"""Image API endpoints — listing, serving, metadata, caption/decision editing."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api.deps import get_data_backend
from common.curation import import_curation_decisions, get_curation_metadata
from common.data_access import DataBackend

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/images", tags=["images"])


class CaptionUpdate(BaseModel):
    caption: str


class DecisionUpdate(BaseModel):
    keep: bool
    note: str = ""


def _load_image_summary(backend: DataBackend) -> list[dict[str, Any]]:
    summary_path = "assets/wwcb/metadata/wwcb_images_summary.json"
    if not backend.exists(summary_path):
        return []
    data = backend.read_json(summary_path)
    return data.get("images", [])


def _find_image_by_id(images: list[dict], image_id: str) -> dict | None:
    for img in images:
        if img.get("id") == image_id or Path(img.get("filename", "")).stem == image_id:
            return img
    return None


@router.get("")
async def list_images(
    from_date: str | None = Query(None, alias="from"),
    region: str | None = None,
    category: str | None = None,
    backend: DataBackend = Depends(get_data_backend),
) -> list[dict[str, Any]]:
    """List images with optional filters."""
    images = _load_image_summary(backend)

    if from_date:
        images = [img for img in images if (img.get("pdf_date") or "") >= from_date]
    if region:
        images = [
            img for img in images
            if region.upper() in (img.get("region") or "").upper()
        ]
    if category:
        images = [img for img in images if img.get("category") == category]

    return [
        {
            "id": img.get("id", Path(img.get("filename", "")).stem),
            "filename": img.get("filename"),
            "source_pdf": img.get("source_pdf"),
            "pdf_date": img.get("pdf_date"),
            "category": img.get("category"),
            "region": img.get("region"),
            "toc_section": img.get("toc_section", ""),
            "page_text": (img.get("page_text") or "")[:200],
            "ocr_text": (img.get("ocr_text") or "")[:200],
        }
        for img in images
    ]


@router.get("/{image_id}/file")
async def get_image_file(
    image_id: str,
    backend: DataBackend = Depends(get_data_backend),
) -> FileResponse:
    """Serve the image file."""
    images = _load_image_summary(backend)
    img = _find_image_by_id(images, image_id)
    if not img:
        raise HTTPException(404, f"Image not found: {image_id}")

    img_path = img.get("path")
    if not img_path or not Path(img_path).exists():
        archive_path = _check_archive_path(backend, img)
        if archive_path:
            return FileResponse(archive_path)
        raise HTTPException(404, f"Image file missing: {image_id}")

    return FileResponse(img_path)


@router.get("/{image_id}/meta")
async def get_image_meta(
    image_id: str,
    backend: DataBackend = Depends(get_data_backend),
) -> dict[str, Any]:
    """Full image metadata."""
    images = _load_image_summary(backend)
    img = _find_image_by_id(images, image_id)
    if not img:
        raise HTTPException(404, f"Image not found: {image_id}")
    return img


@router.put("/{image_id}/caption")
async def update_caption(
    image_id: str,
    body: CaptionUpdate,
    backend: DataBackend = Depends(get_data_backend),
) -> dict[str, str]:
    """Update image caption (Phase 2 web UI)."""
    # USER-CONFIG: Phase 2 auth check injection point
    images = _load_image_summary(backend)
    img = _find_image_by_id(images, image_id)
    if not img:
        raise HTTPException(404, f"Image not found: {image_id}")

    meta_path = f"assets/wwcb/metadata/{Path(img['source_pdf']).stem}_images.json"
    if backend.exists(meta_path):
        all_meta = backend.read_json(meta_path)
        for m in all_meta:
            if m.get("id") == image_id or Path(m.get("filename", "")).stem == image_id:
                m["caption"] = body.caption
                break
        backend.write_json(meta_path, all_meta)

    return {"status": "updated", "image_id": image_id}


@router.put("/{image_id}/decision")
async def update_decision(
    image_id: str,
    body: DecisionUpdate,
    backend: DataBackend = Depends(get_data_backend),
) -> dict[str, str]:
    """Set keep/skip decision for an image (Phase 2 web UI)."""
    # USER-CONFIG: Phase 2 auth check injection point
    curation_path = "assets/wwcb/curation.json"
    if backend.exists(curation_path):
        curation = backend.read_json(curation_path)
    else:
        curation = {"rules": {}, "blocklist_hashes": [], "manual_decisions": {}}

    curation.setdefault("manual_decisions", {})[image_id] = {
        "keep": body.keep,
        "note": body.note,
    }

    if not body.keep:
        images = _load_image_summary(backend)
        img = _find_image_by_id(images, image_id)
        if img and img.get("phash"):
            blocklist = curation.setdefault("blocklist_hashes", [])
            if img["phash"] not in blocklist:
                blocklist.append(img["phash"])

    backend.write_json(curation_path, curation)
    return {"status": "updated", "image_id": image_id, "keep": str(body.keep)}


class CurationImport(BaseModel):
    decisions: list[dict[str, Any]]
    curator: str = "user"


@router.post("/curation/import")
async def import_curation(body: CurationImport) -> dict[str, Any]:
    """Import curation decisions and generate ML-ready dataset."""
    result = import_curation_decisions(body.decisions, body.curator)
    return {"status": "imported", **result}


@router.get("/curation/metadata")
async def curation_metadata() -> dict[str, Any]:
    """Get curated dataset metadata (stats, schema, version)."""
    meta = get_curation_metadata()
    if not meta:
        raise HTTPException(404, "No curated dataset found")
    return meta


def _check_archive_path(backend: DataBackend, img: dict) -> str | None:
    """Check if the image exists in the archive directory."""
    if img.get("archived") and img.get("archive_path"):
        archive_full = backend.resolve_path(img["archive_path"])
        if Path(archive_full).exists():
            return archive_full
    filename = img.get("filename", "")
    if not filename:
        return None
    pdf_date = img.get("pdf_date", "")
    if pdf_date and len(pdf_date) >= 4:
        year = pdf_date[:4]
        archive_rel = f"archive/wwcb/images/{year}/{filename}"
        archive_full = backend.resolve_path(archive_rel)
        if Path(archive_full).exists():
            return archive_full
    return None
