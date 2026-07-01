"""Scheduling control API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from api.scheduler import get_job_states, pause_all, resume_all, update_schedule

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


class ScheduleUpdate(BaseModel):
    cron_expression: str


@router.get("")
async def list_schedules() -> list[dict[str, Any]]:
    """Current schedule configuration and next run times."""
    return get_job_states()


@router.put("/{source}")
async def update_source_schedule(source: str, body: ScheduleUpdate) -> dict[str, str]:
    """Change the cron schedule for a source."""
    update_schedule(source, body.cron_expression)
    return {"status": "updated", "source": source, "cron_expression": body.cron_expression}


@router.post("/pause")
async def pause_schedules() -> dict[str, str]:
    """Pause all scheduled collection jobs."""
    pause_all()
    return {"status": "paused"}


@router.post("/resume")
async def resume_schedules() -> dict[str, str]:
    """Resume all scheduled collection jobs."""
    resume_all()
    return {"status": "resumed"}
