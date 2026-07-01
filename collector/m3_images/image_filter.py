"""Multi-stage image filter: rule-based + perceptual hash blocklist.

Stage 1 (rules): size, aspect ratio, page position, keyword proximity.
Stage 2 (hashing): perceptual hash against blocklist for duplicate/unwanted images.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# USER-CONFIG: default curation config path (relative to data dir)
CURATION_REL_PATH = "assets/wwcb/curation.json"

DEFAULT_CURATION = {
    "rules": {
        # USER-CONFIG: minimum image dimensions (pixels) — below this = icon
        "min_width": 150,
        "min_height": 150,
        # USER-CONFIG: minimum area for map candidate prioritization
        "min_area": 250_000,
        # USER-CONFIG: minimum file size in KB
        "min_size_kb": 10,
        # USER-CONFIG: maximum aspect ratio — above this = banner/decoration
        "max_aspect_ratio": 4.0,
        # USER-CONFIG: skip images from the first page (usually cover/logo)
        "exclude_first_page": True,
        # USER-CONFIG: keywords that indicate satellite/weather content (case-insensitive)
        "keywords": [
            "satellite", "drought", "precipitation", "temperature",
            "moisture", "NDVI", "vegetation", "snow cover", "flood",
        ],
    },
    "blocklist_hashes": [],
    "manual_decisions": {},
}

# USER-CONFIG: hamming distance threshold for blocklist matching
HASH_DISTANCE_THRESHOLD = 5


@dataclass
class FilterResult:
    keep: bool
    reason: str
    stage: str


def _load_curation(data_dir: Path) -> dict[str, Any]:
    curation_path = data_dir / CURATION_REL_PATH
    if curation_path.exists():
        try:
            return json.loads(curation_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("Failed to read curation.json, using defaults")
    return DEFAULT_CURATION.copy()


def _save_curation(data_dir: Path, curation: dict[str, Any]) -> None:
    curation_path = data_dir / CURATION_REL_PATH
    curation_path.parent.mkdir(parents=True, exist_ok=True)
    curation_path.write_text(
        json.dumps(curation, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def init_curation(data_dir: Path) -> dict[str, Any]:
    """Ensure curation.json exists; return the config."""
    curation_path = data_dir / CURATION_REL_PATH
    if not curation_path.exists():
        _save_curation(data_dir, DEFAULT_CURATION)
        log.info("Created default curation.json at %s", curation_path)
    return _load_curation(data_dir)


class RuleFilter:
    """Stage 1: rule-based filtering by size, position, and keyword proximity."""

    def __init__(self, rules: dict[str, Any]):
        self.min_width = rules.get("min_width", 150)
        self.min_height = rules.get("min_height", 150)
        self.min_area = rules.get("min_area", 250_000)
        self.min_size_kb = rules.get("min_size_kb", 10)
        self.max_aspect_ratio = rules.get("max_aspect_ratio", 4.0)
        self.exclude_first_page = rules.get("exclude_first_page", True)
        self.keywords = [kw.lower() for kw in rules.get("keywords", [])]

    def apply(self, meta: dict[str, Any]) -> FilterResult:
        w = meta.get("width", 0)
        h = meta.get("height", 0)
        page = meta.get("page", 1)
        file_size_kb = meta.get("file_size_kb", 0)
        page_text = (meta.get("page_text", "") or "").lower()

        if w < self.min_width or h < self.min_height:
            return FilterResult(False, f"too small: {w}x{h}", "rule")

        if file_size_kb < self.min_size_kb:
            return FilterResult(False, f"file too small: {file_size_kb:.1f}KB", "rule")

        aspect = max(w, h) / max(min(w, h), 1)
        if aspect > self.max_aspect_ratio:
            return FilterResult(False, f"aspect ratio too high: {aspect:.1f}", "rule")

        if self.exclude_first_page and page == 1:
            return FilterResult(False, "first page excluded", "rule")

        area = w * h
        has_keyword = any(kw in page_text for kw in self.keywords)
        if area >= self.min_area and has_keyword:
            return FilterResult(True, "large + keyword match → prioritized", "rule")

        if area >= self.min_area:
            return FilterResult(True, "large area", "rule")

        if has_keyword:
            return FilterResult(True, "keyword match in nearby text", "rule")

        return FilterResult(True, "passed size filters", "rule")


class HashFilter:
    """Stage 2: perceptual hash blocklist comparison."""

    def __init__(self, blocklist_hashes: list[str]):
        self._blocklist: list[Any] = []
        self._imagehash_available = False

        try:
            import imagehash
            self._imagehash_available = True
            for h_str in blocklist_hashes:
                try:
                    self._blocklist.append(imagehash.hex_to_hash(h_str))
                except Exception:
                    log.warning("Invalid blocklist hash: %s", h_str)
        except ImportError:
            log.warning("imagehash not installed — hash filtering disabled")

    def compute_hash(self, image_path: Path) -> str | None:
        if not self._imagehash_available:
            return None
        try:
            import imagehash
            from PIL import Image
            img = Image.open(image_path)
            return str(imagehash.phash(img))
        except Exception:
            log.debug("Failed to compute hash for %s", image_path)
            return None

    def apply(self, image_path: Path) -> FilterResult:
        if not self._imagehash_available:
            return FilterResult(True, "imagehash not available — skipped", "hash")

        try:
            import imagehash
            from PIL import Image
            img = Image.open(image_path)
            img_hash = imagehash.phash(img)
        except Exception:
            return FilterResult(True, "hash computation failed — kept", "hash")

        for blocked in self._blocklist:
            distance = img_hash - blocked
            if distance <= HASH_DISTANCE_THRESHOLD:
                return FilterResult(False, f"blocklist match (distance={distance})", "hash")

        return FilterResult(True, "no blocklist match", "hash")

    def add_to_blocklist(self, hash_str: str, data_dir: Path) -> None:
        curation = _load_curation(data_dir)
        if hash_str not in curation.get("blocklist_hashes", []):
            curation.setdefault("blocklist_hashes", []).append(hash_str)
            _save_curation(data_dir, curation)
            log.info("Added %s to blocklist", hash_str)


def apply_filters(
    image_path: Path,
    meta: dict[str, Any],
    data_dir: Path,
) -> FilterResult:
    """Run the full filter pipeline (rules → hash) on a single image."""
    curation = _load_curation(data_dir)

    filename = meta.get("filename", image_path.name)
    manual = curation.get("manual_decisions", {}).get(filename)
    if manual is not None:
        return FilterResult(
            manual.get("keep", True),
            f"manual decision: {manual.get('note', '')}",
            "manual",
        )

    rule_filter = RuleFilter(curation.get("rules", {}))
    rule_result = rule_filter.apply(meta)
    if not rule_result.keep:
        return rule_result

    hash_filter = HashFilter(curation.get("blocklist_hashes", []))
    hash_result = hash_filter.apply(image_path)
    if not hash_result.keep:
        return hash_result

    return FilterResult(True, f"{rule_result.reason}; {hash_result.reason}", "passed")
