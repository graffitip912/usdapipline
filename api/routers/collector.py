"""Collector status and control API endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from collector.run import MANIFEST_SOURCES, SOURCES, run_source
from common import manifest
from api.deps import get_verification_store

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/collector", tags=["collector"])


@router.get("/status")
async def collector_status() -> list[dict[str, Any]]:
    """One canonical status entry per run key.

    The manifest stores two spellings per source (collector SOURCE constant
    for successes, run key for failure attempts) — merge both so each of the
    9 sources appears exactly once. Verification records are keyed by run key.
    """
    df = manifest.read()
    all_status: list[dict[str, Any]] = []

    for key in SOURCES:
        names = {key, MANIFEST_SOURCES[key]}
        rows = df[df["source"].isin(names)] if not df.empty else df

        if rows is None or rows.empty:
            entry: dict[str, Any] = {
                "source": key,
                "status": "never_run",
                "last_success": None,
                "last_attempt": None,
                "retry_count": 0,
                "error_message": "",
            }
        else:
            sorted_rows = rows.sort_values("collected_at", ascending=False)
            latest = sorted_rows.iloc[0]
            success_rows = sorted_rows[sorted_rows["status"] == "success"]
            entry = {
                "source": key,
                "status": latest["status"],
                "last_success": success_rows.iloc[0]["collected_at"] if not success_rows.empty else None,
                "last_attempt": latest["collected_at"],
                "retry_count": int(latest.get("retry_count", 0) or 0),
                "error_message": latest.get("error_message", "") or "",
            }
        all_status.append(entry)

    try:
        store = get_verification_store()
        for entry in all_status:
            v_status = store.get_source_verification_status(entry["source"])
            entry["verification_status"] = v_status["verification_status"]
            entry["last_verification_failure"] = v_status["last_verification_failure"]
            entry["open_change_requests"] = v_status["open_change_requests"]
            entry["unresolved_failures"] = v_status["unresolved_failures"]
    except Exception:
        for entry in all_status:
            entry.setdefault("verification_status", "not_verified")
            entry.setdefault("last_verification_failure", None)
            entry.setdefault("open_change_requests", 0)
            entry.setdefault("unresolved_failures", 0)

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
        raise HTTPException(status_code=404, detail=f"Unknown source: {source}")
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
