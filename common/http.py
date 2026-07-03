"""HTTP client with retry, backoff, rate-limit, and User-Agent."""

from __future__ import annotations

import logging
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)


def _is_retryable(exc: BaseException) -> bool:
    """Connection/timeout errors or 5xx server errors are retryable."""
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return exc.response.status_code >= 500
    return False


_USER_AGENT = (
    "USDA-Grain-Pipeline/0.1 "
    "(research; +https://github.com/naraspace/predict)"
)

_session: requests.Session | None = None
_lock = threading.Lock()
_last_request_ts: dict[str, float] = {}
# USER-CONFIG: minimum seconds between requests, per host.
# esmis.nal.usda.gov declares "Crawl-delay: 10" in robots.txt — respect it
# to avoid IP blocking. All other hosts use the default 1 req/sec.
_MIN_INTERVAL_SEC = 1.0
_HOST_MIN_INTERVAL_SEC = {
    "esmis.nal.usda.gov": 10.0,
    "usda.library.cornell.edu": 10.0,
}


def get_session() -> requests.Session:
    global _session
    with _lock:
        if _session is None:
            _session = requests.Session()
            _session.headers.update({"User-Agent": _USER_AGENT})
            adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20)
            _session.mount("https://", adapter)
            _session.mount("http://", adapter)
        return _session


def _rate_limit(url: str = "") -> None:
    host = ""
    try:
        host = url.split("/", 3)[2]
    except IndexError:
        pass
    interval = _HOST_MIN_INTERVAL_SEC.get(host, _MIN_INTERVAL_SEC)
    with _lock:
        elapsed = time.monotonic() - _last_request_ts.get(host, 0.0)
        if elapsed < interval:
            time.sleep(interval - elapsed)
        _last_request_ts[host] = time.monotonic()


@retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    stop=stop_after_attempt(5),
    before_sleep=lambda rs: log.warning(
        "Retry %d/%d for %s (reason: %s)",
        rs.attempt_number, 5, rs.args[0] if rs.args else "?", rs.outcome.exception(),
    ),
    reraise=True,
)
def fetch(url: str, *, params: dict[str, Any] | None = None,
          timeout: int = 120, stream: bool = False) -> requests.Response:
    _rate_limit(url)
    resp = get_session().get(url, params=params, timeout=timeout, stream=stream)
    resp.raise_for_status()
    return resp


def fetch_json(url: str, *, params: dict[str, Any] | None = None,
               timeout: int = 120) -> Any:
    """Fetch URL and parse JSON response. Raises ValueError on decode failure."""
    resp = fetch(url, params=params, timeout=timeout)
    try:
        return resp.json()
    except ValueError as exc:
        log.error("JSON decode failed for %s (status %d, body[:200]=%s)",
                  url, resp.status_code, resp.text[:200])
        raise ValueError(f"Invalid JSON from {url}") from exc


@retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    stop=stop_after_attempt(3),
    before_sleep=lambda rs: log.warning(
        "Retry %d/%d HEAD %s (reason: %s)",
        rs.attempt_number, 3, rs.args[0] if rs.args else "?", rs.outcome.exception(),
    ),
    reraise=True,
)
def head(url: str, *, timeout: int = 15) -> requests.Response:
    """HEAD request with shared session, retry, rate-limit, and User-Agent."""
    _rate_limit(url)
    resp = get_session().head(url, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return resp


def head_ok(url: str, *, timeout: int = 15) -> bool:
    """Return True if HEAD returns 2xx, False on 4xx/connection errors."""
    try:
        head(url, timeout=timeout)
        return True
    except (requests.HTTPError, requests.ConnectionError, requests.Timeout):
        return False


def download_file(url: str, dest: str | Path,
                  *, params: dict[str, Any] | None = None) -> None:
    """Stream-download a file to *dest* atomically (temp + rename)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    resp = fetch(url, params=params, stream=True)
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=dest.parent, suffix=".tmp", prefix=dest.stem,
        )
        try:
            with open(fd, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
            Path(tmp_path).replace(dest)
        except BaseException:
            Path(tmp_path).unlink(missing_ok=True)
            raise
    finally:
        resp.close()
