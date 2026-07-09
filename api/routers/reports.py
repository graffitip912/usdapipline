"""리포트 본문 API — WWCB 내러티브 섹션 텍스트 서빙.

as-is: 리포트 본문은 raw PDF로만 존재, REST 계약 없음 (predict-models가 접근 불가)
to-be: normalized/wwcb_narrative/*.json을 REST로 서빙 — predict-models TB2 v2가
       이미지 도메인 서술에 같은 회차 리포트 본문을 결합하는 데 사용

계약:
  GET /api/reports                     — 사용 가능한 리포트 목록 (kind, date)
  GET /api/reports/wwcb/{date}         — 회차 전체 섹션 (YYYYMMDD)
  GET /api/reports/wwcb/{date}?q=...   — 제목/본문 키워드 필터 (부분 일치, 대소문자 무시)
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query

from common.data_access import get_backend

router = APIRouter(prefix="/api/reports", tags=["reports"])

_REL_DIR = "normalized/wwcb_narrative"
_DATE_RE = re.compile(r"^\d{8}$")


@router.get("")
def list_reports() -> dict:
    """사용 가능한 리포트 회차 목록."""
    backend = get_backend()
    files = backend.list_files(_REL_DIR, "wwcb_*.json")
    dates = sorted(
        name.replace("wwcb_", "").replace(".json", "")
        for name in (f.split("/")[-1].split("\\")[-1] for f in files)
    )
    return {"kinds": ["wwcb"], "wwcb": {"count": len(dates), "dates": dates}}


@router.get("/wwcb/{date}")
def get_wwcb_report(
    date: str,
    q: str | None = Query(default=None, description="제목/본문 키워드 필터"),
) -> dict:
    """WWCB 회차 본문 섹션. date=YYYYMMDD."""
    if not _DATE_RE.match(date):
        raise HTTPException(status_code=422, detail="date must be YYYYMMDD")

    backend = get_backend()
    try:
        data = backend.read_json(f"{_REL_DIR}/wwcb_{date}.json")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"wwcb report not found: {date}")

    if q:
        needle = q.lower()
        data = {
            **data,
            "sections": [
                s for s in data["sections"]
                if needle in s["title"].lower() or needle in s["text"].lower()
            ],
            "filtered_by": q,
        }
    return data
