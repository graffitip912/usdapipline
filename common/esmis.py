"""Official USDA ESMIS / Cornell Library API client.

The Cornell USDA ESMIS API (usda.library.cornell.edu/api/v1) is the official
machine-readable index of USDA Economics, Statistics and Market Information
System releases. Release files are hosted on esmis.nal.usda.gov (USDA
National Agricultural Library). No authentication required.

Verified 2026-07-03:
- GET /api/v1/release/findByIdentifier/wasde?latest=true -> 200, JSON
- Files: https://esmis.nal.usda.gov/sites/default/release-files/{id}/...
- WWCB release pages: /publication/weekly-weather-and-crop-bulletin/{YYYY-MM-DD}
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

import requests

from common.http import fetch, fetch_json

log = logging.getLogger(__name__)

# NOTE: call the ESMIS host directly — usda.library.cornell.edu 301-redirects
# here but DROPS the query string, which silently breaks pagination.
CORNELL_API_BASE = "https://esmis.nal.usda.gov/api/v1"
ESMIS_BASE = "https://esmis.nal.usda.gov"

# USER-CONFIG: ESMIS publication slugs (esmis.nal.usda.gov/publication/<slug>)
WWCB_PUB_SLUG = "weekly-weather-and-crop-bulletin"

_RELEASE_FILE_RE = re.compile(r'href="(/sites/default/release-files/[^"]+)"')


def latest_releases(identifier: str, page: int = 0) -> list[dict[str, Any]]:
    """List releases for a publication identifier, newest first.

    Each entry has 'files' (absolute URLs on esmis.nal.usda.gov),
    'release_datetime' (ISO string), and 'title'. 25 results per page.
    """
    url = f"{CORNELL_API_BASE}/release/findByIdentifier/{identifier}"
    data = fetch_json(url, params={"latest": "true", "page": page}, timeout=60)
    results = data.get("results", [])
    log.info("ESMIS API: %s page %d -> %d releases", identifier, page, len(results))
    return results


def release_files(identifier: str, page: int = 0) -> list[tuple[datetime, list[str]]]:
    """Return (release_datetime, file_urls) tuples, newest first."""
    out: list[tuple[datetime, list[str]]] = []
    for rel in latest_releases(identifier, page=page):
        dt_str = rel.get("release_datetime", "")
        try:
            normalized = dt_str.replace("+0000", "+00:00").replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized).replace(tzinfo=None)
        except ValueError:
            log.debug("ESMIS: unparseable release_datetime %r, skipping", dt_str)
            continue
        files = rel.get("files", [])
        if files:
            out.append((dt, files))
    return out


def pick_file(files: list[str], ext: str) -> str | None:
    """Pick the first file URL with the given extension (e.g. 'xml', 'pdf')."""
    suffix = f".{ext.lstrip('.').lower()}"
    for f in files:
        if f.lower().endswith(suffix):
            return f
    return None


def publication_page_files(pub_slug: str, date: datetime | None = None) -> list[str]:
    """Extract release file URLs from an ESMIS publication page.

    With *date*, fetches the dated release page
    (/publication/<slug>/YYYY-MM-DD); without, fetches the main
    publication page, which links files of the ~10 most recent releases
    (use publication_release_dates() + a dated page to pin one release).
    Returns absolute URLs. Empty list if the page does not exist (404).
    """
    url = f"{ESMIS_BASE}/publication/{pub_slug}"
    if date is not None:
        url += f"/{date.strftime('%Y-%m-%d')}"
    try:
        resp = fetch(url, timeout=60)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return []
        raise
    paths = _RELEASE_FILE_RE.findall(resp.text)
    return [f"{ESMIS_BASE}{p}" for p in dict.fromkeys(paths)]


def publication_release_dates(pub_slug: str) -> list[str]:
    """List recent release dates (YYYY-MM-DD strings, ascending) linked
    from the main publication page."""
    url = f"{ESMIS_BASE}/publication/{pub_slug}"
    resp = fetch(url, timeout=60)
    pattern = re.compile(
        r'href="/publication/' + re.escape(pub_slug) + r'/(\d{4}-\d{2}-\d{2})"'
    )
    return sorted(set(pattern.findall(resp.text)))
