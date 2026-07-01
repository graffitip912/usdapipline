# USDA Grain Pipeline

CBOT 곡물 선물 가격 예측을 위한 USDA 데이터 수집·분석 파이프라인.
9개 소스에서 옥수수/대두/밀 데이터를 수집하고, FastAPI로 서빙하며, Next.js 대시보드로 시각화.

## Quick Start

```bash
# Python backend
python -m venv .venv && .venv/Scripts/activate  # Windows
pip install -e .
cp .env.example .env  # API 키 설정
python -m collector.run --source all             # 전체 수집
python -m uvicorn api.main:app --reload          # API 서버 (port 8000)

# Dashboard
cd dashboard && npm install && npm run dev       # port 3000
```

## Architecture

```
USDA APIs/PDFs → collector/ (9 sources) → data/ (parquet/json/images)
                                              ↓
                                      api/ (FastAPI :8000)
                                              ↓
                                    dashboard/ (Next.js :3000)
```

**Phase 1 (현재):** FastAPI가 수집+API 겸임, 파일시스템 저장, 인증 없음
**Phase 2:** 수집/API 분리, S3/DB 전환, JWT 인증

## Key Rules

- **모든 데이터 접근은 `DataBackend` 추상화를 통해** — 직접 경로 참조 금지
- **외부 LLM API 사용 금지** — 이미지 분류는 규칙+해싱+Tesseract OCR
- **튜닝 값에 `# USER-CONFIG:` 주석** — `grep -r "USER-CONFIG"` 으로 검색
- **`data/` 디렉토리는 gitignore** — 런타임 데이터만 저장

## Structure

| 디렉토리 | 역할 |
|----------|------|
| `common/` | 공유 모듈 (data_access, manifest, storage, schema, http, archiver) |
| `collector/` | 데이터 수집기 (m1_structured, m2_reports, m3_images) |
| `api/` | FastAPI 백엔드 (routers, scheduler, deps) |
| `dashboard/` | Next.js 대시보드 |
| `data/` | 런타임 데이터 (gitignored) |

## API Endpoints

- `GET /api/health` — 서버 상태
- `GET /api/collector/status` — 전체 수집기 상태
- `POST /api/collector/run/{source}` — 수동 수집 실행
- `GET /api/grain/prices?commodity=corn` — 가격 데이터
- `GET /api/images` — 이미지 목록
- `GET /api/schedule` — 스케줄 조회

## Data Sources

| 소스 | 스케줄 | 모듈 |
|------|--------|------|
| GTR xlsx | weekly | m1_structured.gtr |
| QuickStats API | weekly | m1_structured.quickstats |
| Export Sales API | weekly | m1_structured.export_sales |
| WWCB PDF | weekly | m2_reports.wwcb |
| WWCB Images | weekly | m3_images.wwcb_images |
| WASDE CSV | monthly | m1_structured.wasde |
| PSD CSV | monthly | m1_structured.psd |
| ERS Feed Grains | monthly | m1_structured.ers_feedgrains |
| WASDE PDF | monthly | m2_reports.wasde_pdf |

## Testing

```bash
python -c "from api.main import app; print('API OK')"
cd dashboard && npm run build
```

@AGENTS.md
