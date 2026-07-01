"""Data access abstraction layer.

All data reads/writes go through DataBackend. Phase 1 provides LocalBackend
(filesystem). Phase 2 adds S3Backend / GCSBackend — swap via DATA_BACKEND env var.
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import pandas as pd
from PIL import Image

log = logging.getLogger(__name__)

# USER-CONFIG: default data backend
_DEFAULT_BACKEND = "local"

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class DataBackend(ABC):
    """Abstract interface for all data storage operations."""

    @abstractmethod
    def read_parquet(self, rel_path: str) -> pd.DataFrame: ...

    @abstractmethod
    def write_parquet(self, rel_path: str, df: pd.DataFrame) -> None: ...

    @abstractmethod
    def read_json(self, rel_path: str) -> Any: ...

    @abstractmethod
    def write_json(self, rel_path: str, data: Any) -> None: ...

    @abstractmethod
    def read_image(self, rel_path: str) -> bytes: ...

    @abstractmethod
    def write_image(self, rel_path: str, data: bytes) -> None: ...

    @abstractmethod
    def list_files(self, rel_dir: str, pattern: str = "*") -> list[str]: ...

    @abstractmethod
    def exists(self, rel_path: str) -> bool: ...

    @abstractmethod
    def resolve_path(self, rel_path: str) -> str:
        """Return the absolute/full path for a relative data path."""
        ...

    @abstractmethod
    def ensure_dir(self, rel_dir: str) -> None: ...


class LocalBackend(DataBackend):
    """Filesystem-based data backend (Phase 1 default)."""

    def __init__(self, base_dir: Path | None = None):
        if base_dir is None:
            env_dir = os.getenv("DATA_BASE_DIR")
            base_dir = Path(env_dir) if env_dir else _PROJECT_ROOT / "data"
        self._base = Path(base_dir)

    @property
    def base_dir(self) -> Path:
        return self._base

    def _full(self, rel_path: str) -> Path:
        return self._base / rel_path

    def read_parquet(self, rel_path: str) -> pd.DataFrame:
        p = self._full(rel_path)
        if not p.exists():
            return pd.DataFrame()
        return pd.read_parquet(p)

    def write_parquet(self, rel_path: str, df: pd.DataFrame) -> None:
        p = self._full(rel_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(p, index=False, compression="zstd")

    def read_json(self, rel_path: str) -> Any:
        p = self._full(rel_path)
        return json.loads(p.read_text(encoding="utf-8"))

    def write_json(self, rel_path: str, data: Any) -> None:
        p = self._full(rel_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def read_image(self, rel_path: str) -> bytes:
        return self._full(rel_path).read_bytes()

    def write_image(self, rel_path: str, data: bytes) -> None:
        p = self._full(rel_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def list_files(self, rel_dir: str, pattern: str = "*") -> list[str]:
        d = self._full(rel_dir)
        if not d.exists():
            return []
        base_len = len(self._base.parts)
        return [
            str(Path(*p.parts[base_len:]))
            for p in sorted(d.glob(pattern))
            if p.is_file()
        ]

    def exists(self, rel_path: str) -> bool:
        return self._full(rel_path).exists()

    def resolve_path(self, rel_path: str) -> str:
        return str(self._full(rel_path))

    def ensure_dir(self, rel_dir: str) -> None:
        self._full(rel_dir).mkdir(parents=True, exist_ok=True)


_backend_instance: DataBackend | None = None


def get_backend() -> DataBackend:
    """Return the singleton DataBackend based on DATA_BACKEND env var."""
    global _backend_instance
    if _backend_instance is not None:
        return _backend_instance

    # USER-CONFIG: backend selection via environment variable
    backend_type = os.getenv("DATA_BACKEND", _DEFAULT_BACKEND).lower()

    if backend_type == "local":
        _backend_instance = LocalBackend()
    elif backend_type == "s3":
        raise NotImplementedError("S3Backend is a Phase 2 feature")
    elif backend_type == "gcs":
        raise NotImplementedError("GCSBackend is a Phase 2 feature")
    else:
        raise ValueError(f"Unknown DATA_BACKEND: {backend_type!r}")

    log.info("Data backend initialized: %s (base=%s)", backend_type, _backend_instance)
    return _backend_instance


def reset_backend() -> None:
    """Reset the singleton — for testing or runtime reconfiguration."""
    global _backend_instance
    _backend_instance = None
