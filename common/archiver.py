"""Image archive — moves old images to yearly archive directories.

Preserves metadata with archived flag. Archived images remain accessible
via the API through archive path fallback.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from common.data_access import get_backend

log = logging.getLogger(__name__)

# USER-CONFIG: days before archiving images (default: 365 = 1 year)
ARCHIVE_CUTOFF_DAYS = 365


def archive_old_images(cutoff_days: int | None = None) -> dict[str, Any]:
    """Move images older than cutoff_days to archive directory.

    Returns a summary of archived files.
    """
    if cutoff_days is None:
        cutoff_days = ARCHIVE_CUTOFF_DAYS

    backend = get_backend()
    cutoff_date = datetime.utcnow() - timedelta(days=cutoff_days)
    cutoff_str = cutoff_date.strftime("%Y-%m-%d")

    images_dir = Path(backend.resolve_path("assets/wwcb/images"))
    metadata_dir = Path(backend.resolve_path("assets/wwcb/metadata"))

    if not images_dir.exists():
        log.info("No images directory found — nothing to archive")
        return {"archived": 0, "skipped": 0}

    meta_files = sorted(metadata_dir.glob("*_images.json")) if metadata_dir.exists() else []
    all_meta: dict[str, list[dict]] = {}
    for mf in meta_files:
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
            all_meta[mf.name] = data
        except Exception:
            log.warning("Failed to read metadata: %s", mf.name)

    archived_count = 0
    skipped_count = 0

    for meta_filename, images in all_meta.items():
        updated = False
        for img in images:
            if img.get("archived"):
                skipped_count += 1
                continue

            extracted_at = img.get("extracted_at", "")
            if not extracted_at or extracted_at >= cutoff_str:
                skipped_count += 1
                continue

            filename = img.get("filename", "")
            if not filename:
                continue

            src_path = images_dir / filename
            if not src_path.exists():
                continue

            pdf_date = img.get("pdf_date", "")
            year = pdf_date[:4] if pdf_date and len(pdf_date) >= 4 else str(cutoff_date.year)

            archive_rel = f"archive/wwcb/images/{year}"
            backend.ensure_dir(archive_rel)
            archive_dir = Path(backend.resolve_path(archive_rel))
            dest_path = archive_dir / filename

            shutil.move(str(src_path), str(dest_path))

            img["archived"] = True
            img["archive_path"] = f"{archive_rel}/{filename}"
            updated = True
            archived_count += 1
            log.debug("Archived: %s → %s", filename, dest_path)

        if updated:
            meta_path = metadata_dir / meta_filename
            meta_path.write_text(
                json.dumps(images, indent=2, ensure_ascii=False), encoding="utf-8"
            )

    summary = {"archived": archived_count, "skipped": skipped_count, "cutoff_date": cutoff_str}
    log.info("Archive complete: %d archived, %d skipped", archived_count, skipped_count)
    return summary
