"""Path management for raw / normalized / assets layers."""

from __future__ import annotations

import hashlib
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

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


def ensure_dirs() -> None:
    for d in [
        RAW_DIR / "gtr",
        RAW_DIR / "quickstats",
        RAW_DIR / "wasde",
        RAW_DIR / "wwcb",
        RAW_DIR / "psd",
        RAW_DIR / "ers_feedgrains",
        RAW_DIR / "export_sales",
        NORM_DIR / "structured",
        NORM_DIR / "wwcb_narrative",
        ASSETS_DIR / "wwcb",
        ASSETS_DIR / "wwcb" / "images",
        ASSETS_DIR / "wwcb" / "metadata",
        ASSETS_DIR / "geo",
    ]:
        d.mkdir(parents=True, exist_ok=True)


def raw_path(source: str, filename: str) -> Path:
    return RAW_DIR / source / filename


def norm_path(filename: str) -> Path:
    return NORM_DIR / "structured" / filename


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
