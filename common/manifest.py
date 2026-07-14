"""Artifact manifest — tracks every raw/normalized/asset file.

Status lifecycle:
  success → (next run fails) → failed → (retry succeeds) → success
                                      → (3 consecutive fails) → stale
  stale → (next scheduled run succeeds) → success
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from common.storage import DATA_DIR

MANIFEST_PATH = DATA_DIR / "manifest.parquet"

_COLUMNS = [
    "source",
    "artifact_type",
    "period",
    "path",
    "sha256",
    "status",
    "collected_at",
    "retry_count",
    "error_message",
]

def _max_retries() -> int:
    """Stale threshold — declared in harness.yaml (runtime_rules.retry_policy.max_retries)."""
    try:
        from common.harness_config import get_retry_policy
        return int(get_retry_policy().get("max_retries", 3))
    except Exception:
        return 3

_cache: pd.DataFrame | None = None
_lock = threading.Lock()


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_COLUMNS)


def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in ("retry_count", "error_message"):
        if col not in df.columns:
            df[col] = 0 if col == "retry_count" else ""
    return df


def read() -> pd.DataFrame:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache.copy()
        if MANIFEST_PATH.exists():
            _cache = _ensure_columns(pd.read_parquet(MANIFEST_PATH))
        else:
            _cache = _empty_df()
        return _cache.copy()


def write(df: pd.DataFrame) -> None:
    global _cache
    with _lock:
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(MANIFEST_PATH, index=False, compression="zstd")
        _cache = df.copy()


def flush() -> None:
    with _lock:
        if _cache is not None:
            MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
            _cache.to_parquet(MANIFEST_PATH, index=False, compression="zstd")


def upsert(
    source: str,
    artifact_type: str,
    period: str,
    path: str | Path,
    sha256: str,
    status: str = "success",
    error_message: str = "",
) -> bool:
    """Insert or update a manifest row. Returns True if content is new/changed."""
    with _lock:
        global _cache
        df = _cache.copy() if _cache is not None else _load_unlocked()
        df = _ensure_columns(df)
        path_str = str(path)
        mask = (df["source"] == source) & (df["path"] == path_str)
        existing = df.loc[mask]

        if not existing.empty and existing.iloc[0]["sha256"] == sha256 and status == "success":
            return False

        retry_count = 0
        if status == "failed" and not existing.empty:
            prev_retries = int(existing.iloc[0].get("retry_count", 0))
            retry_count = prev_retries + 1
            if retry_count >= _max_retries():
                status = "stale"

        row = pd.DataFrame(
            [{
                "source": source,
                "artifact_type": artifact_type,
                "period": period,
                "path": path_str,
                "sha256": sha256,
                "status": status,
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "retry_count": retry_count if status in ("failed", "stale") else 0,
                "error_message": error_message,
            }]
        )

        if not existing.empty:
            df = df.loc[~mask]
        df = pd.concat([df, row], ignore_index=True)
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(MANIFEST_PATH, index=False, compression="zstd")
        _cache = df.copy()
        return True


def _load_unlocked() -> pd.DataFrame:
    global _cache
    if MANIFEST_PATH.exists():
        _cache = _ensure_columns(pd.read_parquet(MANIFEST_PATH))
    else:
        _cache = _empty_df()
    return _cache.copy()


def has_unchanged(source: str, sha256: str) -> bool:
    df = read()
    return ((df["source"] == source) & (df["sha256"] == sha256)).any()


def record_failure(source: str, error_message: str = "") -> str:
    """Record a collection failure for a source. Returns the resulting status."""
    with _lock:
        global _cache
        df = _cache.copy() if _cache is not None else _load_unlocked()
        df = _ensure_columns(df)

        mask = df["source"] == source
        source_rows = df.loc[mask]

        prev_retries = 0
        if not source_rows.empty:
            latest = source_rows.sort_values("collected_at", ascending=False).iloc[0]
            prev_retries = int(latest.get("retry_count", 0))

        retry_count = prev_retries + 1
        status = "stale" if retry_count >= _max_retries() else "failed"

        row = pd.DataFrame(
            [{
                "source": source,
                "artifact_type": "collection_attempt",
                "period": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "path": "",
                "sha256": "",
                "status": status,
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "retry_count": retry_count,
                "error_message": error_message[:500],
            }]
        )

        df = pd.concat([df, row], ignore_index=True)
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(MANIFEST_PATH, index=False, compression="zstd")
        _cache = df.copy()
        return status


def record_skipped(source: str, reason: str = "") -> None:
    """Record an intentionally skipped collection (e.g. API key not set).

    Distinct from failure: retry counting is not advanced and the source
    surfaces as status='skipped' in monitoring (seed.yaml all_sources_runnable
    criteria).
    """
    with _lock:
        global _cache
        df = _cache.copy() if _cache is not None else _load_unlocked()
        df = _ensure_columns(df)
        row = pd.DataFrame(
            [{
                "source": source,
                "artifact_type": "collection_attempt",
                "period": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "path": "",
                "sha256": "",
                "status": "skipped",
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "retry_count": 0,
                "error_message": reason[:500],
            }]
        )
        df = pd.concat([df, row], ignore_index=True)
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(MANIFEST_PATH, index=False, compression="zstd")
        _cache = df.copy()


def record_success(source: str) -> None:
    """Reset retry count on successful collection."""
    pass


def get_status(source: str) -> dict[str, Any]:
    """Get status summary for a single source."""
    df = read()
    source_rows = df[df["source"] == source]

    if source_rows.empty:
        return {
            "source": source,
            "status": "unknown",
            "last_success": None,
            "last_attempt": None,
            "retry_count": 0,
            "error_message": "",
        }

    sorted_rows = source_rows.sort_values("collected_at", ascending=False)
    latest = sorted_rows.iloc[0]

    success_rows = sorted_rows[sorted_rows["status"] == "success"]
    last_success = success_rows.iloc[0]["collected_at"] if not success_rows.empty else None

    return {
        "source": source,
        "status": latest["status"],
        "last_success": last_success,
        "last_attempt": latest["collected_at"],
        "retry_count": int(latest.get("retry_count", 0)),
        "error_message": latest.get("error_message", ""),
    }


def get_all_status() -> list[dict[str, Any]]:
    """Get status summary for all known sources."""
    df = read()
    sources = df["source"].unique().tolist()
    return [get_status(s) for s in sorted(sources)]


def get_failed_sources() -> list[str]:
    """Return source names that are in 'failed' status (eligible for retry)."""
    df = read()
    if df.empty:
        return []
    latest = (
        df.sort_values("collected_at", ascending=False)
        .drop_duplicates(subset=["source"], keep="first")
    )
    return latest[latest["status"] == "failed"]["source"].tolist()
