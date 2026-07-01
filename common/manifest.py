"""Artifact manifest - tracks every raw/normalized/asset file."""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

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
]

_cache: pd.DataFrame | None = None
_lock = threading.Lock()


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_COLUMNS)


def read() -> pd.DataFrame:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache.copy()
        if MANIFEST_PATH.exists():
            _cache = pd.read_parquet(MANIFEST_PATH)
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
    """Explicitly persist the in-memory cache to disk."""
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
) -> bool:
    """Insert or update a manifest row. Returns True if content is new/changed."""
    with _lock:
        global _cache
        df = _cache.copy() if _cache is not None else _load_unlocked()
        path_str = str(path)
        mask = (df["source"] == source) & (df["path"] == path_str)
        existing = df.loc[mask]

        if not existing.empty and existing.iloc[0]["sha256"] == sha256:
            return False

        row = pd.DataFrame(
            [{
                "source": source,
                "artifact_type": artifact_type,
                "period": period,
                "path": path_str,
                "sha256": sha256,
                "status": status,
                "collected_at": datetime.utcnow().isoformat(),
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
        _cache = pd.read_parquet(MANIFEST_PATH)
    else:
        _cache = _empty_df()
    return _cache.copy()


def has_unchanged(source: str, sha256: str) -> bool:
    """Check if we already have this exact content."""
    df = read()
    return ((df["source"] == source) & (df["sha256"] == sha256)).any()
