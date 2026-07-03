"""WASDE PDF archiver – download original WASDE report PDFs.

Phase 1: raw PDF download for archive/audit purposes.
The structured data comes from the CSV/XML collector (m1_structured/wasde.py).

Source: official ESMIS archive (esmis.nal.usda.gov) indexed by the Cornell
Library API — exact file URLs, no URL guessing or HEAD probing needed.
www.usda.gov is not used (host outage 2026-07, and ESMIS is the archive
of record).
"""

from __future__ import annotations

import logging

from common import esmis, manifest
from common.http import download_file
from common.storage import RAW_DIR, ensure_dirs, sha256_file

log = logging.getLogger(__name__)

SOURCE = "USDA_WASDE_PDF"

# USER-CONFIG: safety cap on API pages per run (25 releases/page)
MAX_API_PAGES = 30


def collect(since: int = 2010, force: bool = False) -> None:
    ensure_dirs()
    raw_dir = RAW_DIR / "wasde"
    raw_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    skipped = 0
    for page in range(MAX_API_PAGES):
        try:
            releases = esmis.release_files("wasde", page=page)
        except Exception:
            log.exception("WASDE PDF: ESMIS API unreachable (page %d)", page)
            break
        if not releases:
            break

        reached_since = False
        page_downloads = 0
        page_existing = 0
        for report_date, files in releases:
            if report_date.year < since:
                reached_since = True
                break

            pdf_url = esmis.pick_file(files, "pdf")
            if pdf_url is None:
                log.debug("WASDE PDF: no PDF in release %s", report_date)
                continue

            dest = raw_dir / f"wasde_{report_date.year}_{report_date.month:02d}.pdf"
            if dest.exists() and not force:
                skipped += 1
                page_existing += 1
                continue

            try:
                download_file(pdf_url, dest)
            except Exception:
                log.warning("WASDE PDF: download failed for %s", pdf_url)
                continue

            manifest.upsert(
                source=SOURCE,
                artifact_type="raw_pdf",
                period=f"{report_date.year}-{report_date.month:02d}",
                path=dest,
                sha256=sha256_file(dest),
            )
            downloaded += 1
            page_downloads += 1
            log.debug("WASDE PDF: saved %s", dest.name)

        if reached_since:
            break
        # Incremental early-stop: a page that is entirely on disk already
        # means older pages were collected by a previous run — scheduled
        # runs only need to pick up the newest release(s).
        if not force and page_downloads == 0 and page_existing > 0:
            log.debug("WASDE PDF: page %d fully present, stopping scan", page)
            break

    log.info(
        "WASDE PDF: downloaded %d PDFs from ESMIS (%d already present)",
        downloaded, skipped,
    )
