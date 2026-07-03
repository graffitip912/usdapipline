"""WWCB – Weekly Weather and Crop Bulletin (PDF raw download).

Phase 1: download current + archive PDFs to raw storage.
Phase 2 will add narrative text extraction and image extraction.

Source: official ESMIS archive (esmis.nal.usda.gov). Release pages are
date-based (/publication/weekly-weather-and-crop-bulletin/YYYY-MM-DD,
released Tuesdays), so no URL guessing is needed. www.usda.gov is not
used (host outage 2026-07, and ESMIS is the archive of record).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from common import esmis, manifest
from common.http import download_file
from common.storage import RAW_DIR, ensure_dirs, sha256_file

log = logging.getLogger(__name__)

SOURCE = "USDA_WWCB"

# USER-CONFIG: consecutive missing weeks before stopping the archive scan
MAX_CONSECUTIVE_MISSES = 8


def collect(since: int = 2010, force: bool = False) -> None:
    """Download current WWCB PDF (and optionally recent archive) from ESMIS."""
    ensure_dirs()
    raw_dir = RAW_DIR / "wwcb"
    raw_dir.mkdir(parents=True, exist_ok=True)

    _download_current(raw_dir, force)

    if since < datetime.utcnow().year:
        # USER-CONFIG: archive depth in weeks (ESMIS retains full history;
        # `since` earlier than ~1 year is capped by this window)
        _download_recent_archive(raw_dir, weeks_back=52, force=force)


def _download_current(raw_dir: Path, force: bool) -> None:
    """Fetch the most recent release linked from the ESMIS publication page."""
    try:
        dates = esmis.publication_release_dates(esmis.WWCB_PUB_SLUG)
    except Exception:
        log.exception("WWCB: could not list releases from ESMIS")
        return
    if not dates:
        log.warning("WWCB: no releases found on ESMIS publication page")
        return

    latest = datetime.strptime(dates[-1], "%Y-%m-%d")
    if _download_release(raw_dir, latest, force):
        log.info("WWCB: current release %s collected", dates[-1])


def _download_recent_archive(raw_dir: Path, weeks_back: int, force: bool) -> None:
    """Fetch archived weekly PDFs via date-based ESMIS release pages.

    WWCB is normally released on Tuesdays but slips to Wednesday on
    holiday weeks (verified: 2026-05-27 exists, 2026-05-26 does not),
    so each week probes Tue -> Wed -> Mon. Stops after
    MAX_CONSECUTIVE_MISSES consecutive missing weeks.
    """
    now = datetime.utcnow()
    tuesday = now - timedelta(days=(now.weekday() - 1) % 7)
    downloaded = 0
    misses = 0

    for w in range(1, weeks_back + 1):
        week_tue = tuesday - timedelta(weeks=w)
        candidates = [week_tue, week_tue + timedelta(days=1), week_tue - timedelta(days=1)]

        if not force and any(
            (raw_dir / f"wwcb_{d.strftime('%Y%m%d')}.pdf").exists() for d in candidates
        ):
            misses = 0
            continue

        if any(_download_release(raw_dir, d, force) for d in candidates):
            downloaded += 1
            misses = 0
        else:
            misses += 1
            if misses >= MAX_CONSECUTIVE_MISSES:
                log.info(
                    "WWCB: %d consecutive missing weeks — stopping archive scan",
                    misses,
                )
                break

    log.info("WWCB: downloaded %d archive PDFs", downloaded)


def _download_release(raw_dir: Path, date: datetime, force: bool) -> bool:
    """Download the PDF of the ESMIS release dated *date*. Returns True on success."""
    try:
        files = esmis.publication_page_files(esmis.WWCB_PUB_SLUG, date)
    except Exception:
        log.warning("WWCB: release page fetch failed for %s", date.date())
        return False

    pdf_url = esmis.pick_file(files, "pdf")
    if pdf_url is None:
        return False

    date_str = date.strftime("%Y%m%d")
    dest = raw_dir / f"wwcb_{date_str}.pdf"
    if dest.exists() and not force:
        return True

    try:
        download_file(pdf_url, dest)
    except Exception:
        log.warning("WWCB: download failed for %s", pdf_url)
        return False

    file_hash = sha256_file(dest)
    if not force and manifest.has_unchanged(SOURCE, file_hash):
        log.info("WWCB: %s unchanged", dest.name)
        return True

    manifest.upsert(
        source=SOURCE,
        artifact_type="raw_pdf",
        period=f"week_{date_str}",
        path=dest,
        sha256=file_hash,
    )
    log.info("WWCB: saved %s (%.1f MB)", dest.name, dest.stat().st_size / 1e6)
    return True
