"""Path management for raw / normalized / assets layers.

Delegates base directory resolution to DataBackend. Direct path constants
(RAW_DIR, etc.) are preserved for backward compatibility with existing
collectors but resolve through the abstraction layer.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from common.data_access import get_backend, LocalBackend

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _base_dir() -> Path:
    backend = get_backend()
    if isinstance(backend, LocalBackend):
        return backend.base_dir
    return _PROJECT_ROOT / "data"


def _lazy_dir(subpath: str) -> Path:
    return _base_dir() / subpath


# Keep module-level constants for backward compatibility.
# Collectors that import these directly will still work.
BASE_DIR = _PROJECT_ROOT
DATA_DIR = _PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
NORM_DIR = DATA_DIR / "normalized"
ASSETS_DIR = DATA_DIR / "assets"

SOURCE_DIRS: dict[str, Path] = {
    "gtr": RAW_DIR / "gtr",
    "quickstats": RAW_DIR / "quickstats",
    "wasde": RAW_DIR / "wasde",
    "wwcb": RAW_DIR / "wwcb",
    "psd": RAW_DIR / "psd",
    "ers_feedgrains": RAW_DIR / "ers_feedgrains",
    "export_sales": RAW_DIR / "export_sales",
}

# USER-CONFIG: directory structure for data layers
_RAW_DIRS = [
    "raw/gtr", "raw/quickstats", "raw/wasde", "raw/wwcb",
    "raw/psd", "raw/ers_feedgrains", "raw/export_sales",
]
_NORM_DIRS = ["normalized/structured", "normalized/wwcb_narrative"]
_ASSET_DIRS = [
    "assets/wwcb", "assets/wwcb/images", "assets/wwcb/metadata", "assets/geo",
]
_META_DIRS = ["meta/verification"]
_CURATED_DIRS = ["curated/wwcb_images"]


def ensure_dirs() -> None:
    backend = get_backend()
    for d in _RAW_DIRS + _NORM_DIRS + _ASSET_DIRS + _META_DIRS + _CURATED_DIRS:
        backend.ensure_dir(d)


def raw_path(source: str, filename: str) -> Path:
    return _base_dir() / "raw" / source / filename


def norm_path(filename: str) -> Path:
    return _base_dir() / "normalized" / "structured" / filename


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
