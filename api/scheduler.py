"""APScheduler integration for automated data collection.

Runs collection jobs on configurable cron schedules within the FastAPI process.
"""

from __future__ import annotations

import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

def _default_schedules() -> dict[str, dict[str, str]]:
    """Cron defaults are declared in harness.yaml (runtime_rules.schedule_triggers)
    — edit there, not here. Release days: WWCB Tue (Wed on holiday weeks),
    Export Sales/GTR Thu → weekly Friday collects the same week's releases."""
    from common.harness_config import get_runtime_rules
    triggers = get_runtime_rules().get("schedule_triggers", {})
    return {
        "weekly": {
            "cron_expression": triggers.get("weekly", "0 6 * * 5"),
            "sources": "weekly",
        },
        "monthly": {
            "cron_expression": triggers.get("monthly", "0 6 15 * *"),
            "sources": "monthly",
        },
    }


DEFAULT_SCHEDULES: dict[str, dict[str, str]] = _default_schedules()

_job_states: dict[str, dict[str, Any]] = {}


def _parse_cron(expr: str) -> dict[str, str]:
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: {expr!r} (expected 5 fields)")
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


def _run_collection_sync(source_arg: str) -> None:
    from datetime import datetime
    from collector.run import run_source, _resolve_targets
    targets = _resolve_targets(source_arg)
    # as-is: 기본 since(2010)로 전체 범위 재조회 — 대형 소스(SOIL 등) 타임아웃 위험
    # to-be: 스케줄 배치는 당해 연도만 증분 갱신 (초기 백필은 CLI --since로 1회 수행)
    #        병합 보존 dedup이 최신 주차 데이터를 기존 이력에 합류시킴 (2026-07-10 사용자 지시)
    since = datetime.utcnow().year  # USER-CONFIG: 주간 배치 증분 범위
    for source_key in targets:
        result = run_source(source_key, since=since)
        log.info("Scheduled collection %s: %s (since=%d)", source_key, result["status"], since)


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


def setup_default_jobs(scheduler: AsyncIOScheduler) -> None:
    for group_name, config in DEFAULT_SCHEDULES.items():
        job_id = f"collect_{group_name}"
        cron_parts = _parse_cron(config["cron_expression"])
        trigger = CronTrigger(**cron_parts)
        scheduler.add_job(
            _run_collection_sync,
            trigger=trigger,
            id=job_id,
            args=[config["sources"]],
            replace_existing=True,
            name=f"Collect {group_name} sources",
        )
        _job_states[job_id] = {
            "source": group_name,
            "schedule_type": group_name,
            "cron_expression": config["cron_expression"],
            "paused": False,
        }
        log.info("Registered job %s: %s", job_id, config["cron_expression"])


def get_job_states() -> list[dict[str, Any]]:
    scheduler = get_scheduler()
    result = []
    for job in scheduler.get_jobs():
        state = _job_states.get(job.id, {})
        result.append({
            "source": state.get("source", job.id),
            "schedule_type": state.get("schedule_type", "custom"),
            "cron_expression": state.get("cron_expression", ""),
            "next_run": str(job.next_run_time) if job.next_run_time else None,
            "paused": state.get("paused", False),
        })
    return result


def update_schedule(source: str, cron_expression: str) -> bool:
    scheduler = get_scheduler()
    job_id = f"collect_{source}"
    job = scheduler.get_job(job_id)

    if job is None:
        cron_parts = _parse_cron(cron_expression)
        trigger = CronTrigger(**cron_parts)
        scheduler.add_job(
            _run_collection_sync,
            trigger=trigger,
            id=job_id,
            args=[source],
            replace_existing=True,
            name=f"Collect {source}",
        )
    else:
        cron_parts = _parse_cron(cron_expression)
        trigger = CronTrigger(**cron_parts)
        job.reschedule(trigger)

    _job_states[job_id] = {
        "source": source,
        "schedule_type": "custom",
        "cron_expression": cron_expression,
        "paused": False,
    }
    return True


def pause_all() -> None:
    scheduler = get_scheduler()
    scheduler.pause()
    for state in _job_states.values():
        state["paused"] = True


def resume_all() -> None:
    scheduler = get_scheduler()
    scheduler.resume()
    for state in _job_states.values():
        state["paused"] = False
