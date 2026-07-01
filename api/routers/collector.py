"""Collector status and control API endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks

from collector.run import SOURCES, run_source
from common import manifest

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/collector", tags=["collector"])


@router.get("/status")
async def collector_status() -> list[dict[str, Any]]:
    """All collector statuses from the manifest."""
    all_status = manifest.get_all_status()
    source_keys = set(SOURCES.keys())
    known = {s["source"] for s in all_status}
    for key in source_keys:
        if key not in known and f"USDA_{key.upper()}" not in known:
            all_status.append({
                "source": key,
                "status": "never_run",
                "last_success": None,
                "last_attempt": None,
                "retry_count": 0,
                "error_message": "",
            })
    return all_status


@router.post("/run/{source}")
async def run_collector(
    source: str,
    background_tasks: BackgroundTasks,
    since: int = 2010,
    force: bool = False,
) -> dict[str, str]:
    """Trigger a collection run for a specific source (runs in background)."""
    if source not in SOURCES:
        return {"source": source, "status": "error", "message": f"Unknown source: {source}"}
    background_tasks.add_task(run_source, source, since, force)
    return {"source": source, "status": "started", "message": f"Collection started for {source}"}


@router.get("/history/{source}")
async def collector_history(source: str, limit: int = 50) -> list[dict[str, Any]]:
    """Collection history for a specific source."""
    df = manifest.read()
    source_rows = df[
        (df["source"] == source) | (df["source"] == f"USDA_{source.upper()}")
    ]
    if source_rows.empty:
        return []
    sorted_rows = source_rows.sort_values("collected_at", ascending=False).head(limit)
    return sorted_rows.to_dict("records")
