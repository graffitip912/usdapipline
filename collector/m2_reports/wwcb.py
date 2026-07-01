"""WWCB – Weekly Weather and Crop Bulletin (PDF raw download).

Phase 1: download current + archive PDFs to raw storage.
Phase 2 will add narrative text extraction and image extraction.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from common import manifest
from common.http import download_file, head_ok
from common.storage import RAW_DIR, ensure_dirs, sha256_file

log = logging.getLogger(__name__)

SOURCE = "USDA_WWCB"

CURRENT_PDF_URL = "https://www.usda.gov/sites/default/files/documents/wwcb.pdf"

ARCHIVE_BASE = "https://www.usda.gov/sites/default/files/documents"
ARCHIVE_PATTERNS = [
    "{base}/wwcb_{date}.pdf",
    "{base}/WWCB_{date}.pdf",
]

ESMIS_BASE = "https://esmis.nal.usda.gov/sites/default/release-files"
ESMIS_PATTERNS = [
    "{base}/{release_id}/wwcb{issue}{yy}.pdf",
]


def collect(since: int = 2010, force: bool = False) -> None:
    """Download current WWCB PDF (and optionally recent archive)."""
    ensure_dirs()
    raw_dir = RAW_DIR / "wwcb"
    raw_dir.mkdir(parents=True, exist_ok=True)

    _download_current(raw_dir, force)

    if since < datetime.utcnow().year:
        _download_recent_archive(raw_dir, weeks_back=52, force=force)


def _download_current(raw_dir: Path, force: bool) -> None:
    today = datetime.utcnow().strftime("%Y%m%d")
    dest = raw_dir / f"wwcb_current_{today}.pdf"

    try:
        download_file(CURRENT_PDF_URL, dest)
    except Exception:
        log.exception("WWCB: failed to download current PDF")
        return

    file_hash = sha256_file(dest)
    if not force and manifest.has_unchanged(SOURCE, file_hash):
        log.info("WWCB: current PDF unchanged")
        dest.unlink(missing_ok=True)
        return

    manifest.upsert(
        source=SOURCE,
        artifact_type="raw_pdf",
        period=f"week_{today}",
        path=dest,
        sha256=file_hash,
    )
    log.info("WWCB: saved current PDF → %s (%.1f MB)", dest, dest.stat().st_size / 1e6)


def _download_recent_archive(raw_dir: Path, weeks_back: int, force: bool) -> None:
    """Try to fetch archived weekly PDFs by date pattern."""
    now = datetime.utcnow()
    downloaded = 0
    failed = 0

    for w in range(1, weeks_back + 1):
        target_date = now - timedelta(weeks=w)
        tuesday = target_date - timedelta(days=(target_date.weekday() - 1) % 7)
        date_str = tuesday.strftime("%m%d%y")
        date_str_long = tuesday.strftime("%Y%m%d")

        dest = raw_dir / f"wwcb_{date_str_long}.pdf"
        if dest.exists() and not force:
            continue

        url = _try_archive_url(date_str)
        if url is None:
            date_str_alt = tuesday.strftime("%m%d%Y")
            url = _try_archive_url(date_str_alt)
        if url is None:
            url = _try_esmis_url(tuesday)
        if url is None:
            failed += 1
            if failed > 10:
                log.info("WWCB: stopping archive scan after %d consecutive misses", failed)
                break
            continue

        failed = 0
        try:
            download_file(url, dest)
            file_hash = sha256_file(dest)
            manifest.upsert(
                source=SOURCE,
                artifact_type="raw_pdf",
                period=f"week_{date_str_long}",
                path=dest,
                sha256=file_hash,
            )
            downloaded += 1
            log.debug("WWCB: archived %s", dest.name)
        except Exception:
            log.debug("WWCB: failed to download %s", url)

    log.info("WWCB: downloaded %d archive PDFs", downloaded)


def _try_archive_url(date_str: str) -> str | None:
    for pattern in ARCHIVE_PATTERNS:
        url = pattern.format(base=ARCHIVE_BASE, date=date_str)
        if head_ok(url, timeout=10):
            return url
    return None


def _try_esmis_url(tuesday: datetime) -> str | None:
    """Try ESMIS archive as fallback. URL pattern uses issue number + 2-digit year."""
    yy = tuesday.strftime("%y")
    week_num = int(tuesday.strftime("%U"))
    issue = f"{week_num:02d}"
    release_id = f"wwcb-{tuesday.strftime('%Y-%m-%d')}"
    for pattern in ESMIS_PATTERNS:
        url = pattern.format(base=ESMIS_BASE, release_id=release_id, issue=issue, yy=yy)
        if head_ok(url, timeout=10):
            return url
    return None
