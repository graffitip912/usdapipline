"""WASDE PDF archiver – download original WASDE report PDFs.

Phase 1: raw PDF download for archive/audit purposes.
The structured data comes from the CSV collector (m1_structured/wasde.py).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from common import manifest
from common.http import download_file, head_ok
from common.storage import RAW_DIR, ensure_dirs, sha256_file

log = logging.getLogger(__name__)

SOURCE = "USDA_WASDE_PDF"

WASDE_PDF_BASE = "https://www.usda.gov/sites/default/files/documents"
LATEST_PDF_URL = f"{WASDE_PDF_BASE}/latest-wasde-report.pdf"

PDF_PATTERNS = [
    "{base}/oce-wasde-report-{year}-{month:02d}.pdf",
    "{base}/wasde-{year}-{month:02d}.pdf",
    "{base}/wasde{month:02d}{shortyear:02d}.pdf",
]


def collect(since: int = 2010, force: bool = False) -> None:
    ensure_dirs()
    raw_dir = RAW_DIR / "wasde"
    raw_dir.mkdir(parents=True, exist_ok=True)

    _download_latest(raw_dir, force)
    _download_archive(raw_dir, since, force)


def _download_latest(raw_dir: Path, force: bool) -> None:
    dest = raw_dir / "wasde_latest.pdf"
    try:
        download_file(LATEST_PDF_URL, dest)
        file_hash = sha256_file(dest)
        if not force and manifest.has_unchanged(SOURCE, file_hash):
            log.info("WASDE PDF: latest unchanged")
            dest.unlink(missing_ok=True)
            return
        manifest.upsert(
            source=SOURCE,
            artifact_type="raw_pdf",
            period="latest",
            path=dest,
            sha256=file_hash,
        )
        log.info("WASDE PDF: saved latest → %s", dest)
    except Exception:
        log.warning("WASDE PDF: could not download latest report")


def _download_archive(raw_dir: Path, since: int, force: bool) -> None:
    now = datetime.utcnow()
    downloaded = 0

    for year in range(since, now.year + 1):
        end_month = now.month if year == now.year else 12
        for month in range(1, end_month + 1):
            dest = raw_dir / f"wasde_{year}_{month:02d}.pdf"
            if dest.exists() and not force:
                continue

            url = _try_pdf_url(year, month)
            if url is None:
                continue

            try:
                download_file(url, dest)
                file_hash = sha256_file(dest)
                manifest.upsert(
                    source=SOURCE,
                    artifact_type="raw_pdf",
                    period=f"{year}-{month:02d}",
                    path=dest,
                    sha256=file_hash,
                )
                downloaded += 1
            except Exception:
                log.debug("WASDE PDF: failed %d-%02d", year, month)

    log.info("WASDE PDF: downloaded %d archive PDFs", downloaded)


def _try_pdf_url(year: int, month: int) -> str | None:
    shortyear = year % 100
    for pattern in PDF_PATTERNS:
        url = pattern.format(
            base=WASDE_PDF_BASE, year=year, month=month, shortyear=shortyear
        )
        if head_ok(url, timeout=10):
            return url
    return None
