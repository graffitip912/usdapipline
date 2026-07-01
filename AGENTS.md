# Module Guide

## common/

공유 인프라. 모든 모듈이 의존.

- `data_access.py` — `DataBackend` ABC + `LocalBackend`. 환경변수 `DATA_BACKEND`로 백엔드 전환.
- `storage.py` — 경로 관리. `DataBackend` 위임 + 하위호환 상수 (`RAW_DIR`, `NORM_DIR` 등).
- `manifest.py` — 수집 이력 관리. 상태 lifecycle: success → failed → stale (3회 연속 실패).
- `schema.py` — `GrainRecord` Pydantic 모델 + `GrainSchema` Pandera 검증.
- `http.py` — 공유 HTTP 클라이언트 (retry, rate-limit, User-Agent).
- `archiver.py` — 1년 이상 이미지 → `data/archive/` 이동. 메타데이터에 `archived` 플래그.

## collector/

데이터 수집기. `run.py`가 진입점.

- `run.py` — CLI + `run_source()` 프로그래밍 인터페이스. API에서 호출 가능.
- `m1_structured/` — 구조화 데이터 (Parquet 출력): gtr, quickstats, wasde, psd, ers_feedgrains, export_sales
- `m2_reports/` — PDF 리포트: wwcb, wasde_pdf
- `m3_images/` — WWCB 이미지 추출 (4단계 파이프라인)
  - `wwcb_images.py` — 메인 추출 로직. `extract_images_from_pdf()`.
  - `image_filter.py` — 규칙 필터 + 해시 블록리스트. `curation.json` 설정.
  - `ocr_classifier.py` — Tesseract OCR 텍스트 추출 + 콘텐츠 분류.

## api/

FastAPI 백엔드. `main.py`가 앱 진입점.

- `main.py` — FastAPI 앱, CORS, lifespan (스케줄러 시작/중지).
- `deps.py` — 의존성 주입 (`DataBackend`). Phase 2 인증 주입 지점.
- `scheduler.py` — APScheduler 통합. 기본 weekly/monthly 스케줄.
- `routers/collector.py` — 수집기 상태/실행/이력 API.
- `routers/grain.py` — 곡물 가격/수급/재고/GTR 데이터 API.
- `routers/images.py` — 이미지 목록/서빙/메타데이터/캡션/판정 API.
- `routers/schedule.py` — 스케줄 조회/변경/일시정지/재개 API.

## dashboard/

Next.js 대시보드. `src/app/`에 페이지.

- `src/lib/api.ts` — FastAPI 클라이언트. `NEXT_PUBLIC_API_URL` 환경변수.
- `src/app/grain/page.tsx` — 곡물 분석 (Chart.js 차트).
- `src/app/images/page.tsx` — 이미지 뷰어 (갤러리 + 필터 + 상세 모달).
- `src/app/admin/page.tsx` — 관리자 모니터링 (수집기 상태 + 스케줄).
- `src/components/` — NavBar, GrainChart 컴포넌트.
