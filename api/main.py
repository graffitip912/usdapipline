"""FastAPI application — USDA Grain Pipeline API.

Combines data collection control, grain data serving, image serving,
and scheduling in a single process.
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from api.routers import collector, grain, images, reports, schedule, verification
from api.scheduler import get_scheduler, setup_default_jobs
from common.storage import ensure_dirs

log = logging.getLogger(__name__)

# USER-CONFIG: allowed CORS origins (override via CORS_ALLOWED_ORIGINS env var)
_cors_origins_str = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:3020")
ALLOWED_ORIGINS = [o.strip() for o in _cors_origins_str.split(",")]


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    scheduler = get_scheduler()
    setup_default_jobs(scheduler)
    scheduler.start()
    log.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))
    yield
    scheduler.shutdown(wait=False)
    log.info("Scheduler stopped")


API_DESCRIPTION = """
CBOT 곡물 선물 가격 예측을 위한 USDA 데이터 수집·서빙 API.

## 데이터 흐름
`USDA 공식 소스 9종 → collector → data/ (parquet/PDF/이미지) → 본 API → 대시보드(:3000)`

## 소스 (9종)
| 실행 키 | 내용 | 주기 |
|---|---|---|
| gtr, quickstats, wwcb, wwcb_images | GTR 지수 / NASS 통계 / 주간 기상·작황 PDF / 이미지 추출 | 주간 (금 06:00 UTC) |
| wasde, psd, ers_feedgrains, wasde_pdf | WASDE 수급 / FAS PSD / 사료곡물 / WASDE PDF | 월간 (15일 06:00 UTC) |
| export_sales | FAS 수출 판매 — **FAS opendata 장애로 자동 수집 제외 (2026-07-03), 수동 실행만** | manual |

- WASDE/WWCB는 www.usda.gov 장애 시 공식 ESMIS 아카이브(esmis.nal.usda.gov)로 자동 폴백
- **Phase 1**: 인증 없음, 파일시스템 저장. Phase 2에서 JWT + S3/DB 전환 예정
- 소스 파라미터는 항상 **실행 키**(예: `wasde`, `gtr`)를 사용
"""

OPENAPI_TAGS = [
    {"name": "collector", "description": "수집기 상태 조회·수동 실행·이력. 실행은 백그라운드로 동작하며 상태는 manifest 기준."},
    {"name": "grain", "description": "정규화된 곡물 데이터 서빙 — 가격, 수급(supply), 재고(inventory), GTR 지수. commodity=corn|soybean|wheat."},
    {"name": "images", "description": "WWCB 추출 이미지 목록/파일/메타데이터, 캡션·판정 수정, 큐레이션 결과 import."},
    {"name": "schedule", "description": "APScheduler 크론 스케줄 조회·변경·일시정지·재개 (weekly/monthly 그룹)."},
    {"name": "reports", "description": "리포트 본문 서빙 — WWCB 내러티브 섹션 텍스트 (predict-models TB2 v2 report_context 소스)."},
    {"name": "verification", "description": "AC-3/5/6 데이터 검증 게이트 — 검증 이력(as-is→to-be), 사용자 리뷰(승인 게이트), 변경 요청 루프(생성→적용→재수집→검증, 최대 10회), 데이터 미리보기."},
    {"name": "health", "description": "서버 헬스 체크."},
]

app = FastAPI(
    title="USDA Grain Pipeline API",
    version="0.2.0",
    description=API_DESCRIPTION,
    openapi_tags=OPENAPI_TAGS,
    contact={"name": "USDA Grain Pipeline", "email": "phn912@naraspace.com"},
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(collector.router)
app.include_router(grain.router)
app.include_router(images.router)
app.include_router(reports.router)
app.include_router(schedule.router)
app.include_router(verification.router)


@app.get("/api/health", tags=["health"])
async def health_check():
    """서버 생존 확인. 항상 `{"status": "ok"}` 반환 — 모니터링/로드밸런서용."""
    return {"status": "ok", "service": "usda-grain-pipeline"}


if __name__ == "__main__":
    import uvicorn
    # USER-CONFIG: API server host and port
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
