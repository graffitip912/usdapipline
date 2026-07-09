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
    # as-is: 전역 replace + 날짜 형식 미검증 — 비정상 파일명도 목록에 포함 (2026-07-09 점검)
    # to-be: stem에서 날짜 추출 후 YYYYMMDD 검증 통과분만 노출
    dates = sorted(
        stem[len("wwcb_"):]
        for stem in (f.split("/")[-1].split("\\")[-1].removesuffix(".json") for f in files)
        if stem.startswith("wwcb_") and _DATE_RE.match(stem[len("wwcb_"):])
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
    # as-is: FileNotFoundError만 처리 — 손상 JSON/키 누락 시 500 (2026-07-09 점검)
    # to-be: 부재는 404, 손상은 503으로 원인 명시 (조용한 실패 금지)
    try:
        data = backend.read_json(f"{_REL_DIR}/wwcb_{date}.json")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"wwcb report not found: {date}")
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail=f"wwcb report unreadable ({date}): {exc}"
        )

    if q:
        needle = q.lower()
        data = {
            **data,
            "sections": [
                s for s in data.get("sections", [])
                if needle in s.get("title", "").lower()
                or needle in s.get("text", "").lower()
            ],
            "filtered_by": q,
        }
    return data
