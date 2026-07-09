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
- **증분 쓰기 4원칙** (2026-07-09 데이터 유실 사고 2건 재발 방지): ① 기존 파일 병합 보존
  ② 신규 행 스탬프(ingested_at 등)는 concat 직후 부여 ③ dedup 키에 식별 차원 전체 포함
  (region 등) + `kind="stable"` 정렬 ④ tmp→`os.replace` 원자적 교체. 병합용 읽기 실패 시
  **쓰기 중단** (새 데이터만으로 덮어쓰기 금지)

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
| Export Sales API | manual (FAS 장애로 제외, 2026-07-03) | m1_structured.export_sales |
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

# 배포 게이트: 시맨틱 e2e 검증 (API :8000 필수, 대시보드 :3000 권장)
# UI→API 계약, Run 버튼 체인, 검증 preview, 스케줄 왕복 등 8개 체크.
# HTTP 200이 아니라 응답 의미 + 관찰 가능한 상태 변화를 단언 — 변경 후 반드시 통과.
python scripts/verify_pipeline.py
```

@AGENTS.md

<!-- ooo:START -->
<!-- ooo:VERSION:0.43.3 -->
# Ouroboros — Specification-First AI Development

> Before telling AI what to build, define what should be built.
> As Socrates asked 2,500 years ago — "What do you truly know?"
> Ouroboros turns that question into an evolutionary AI workflow engine.

Most AI coding fails at the input, not the output. Ouroboros fixes this by
**exposing hidden assumptions before any code is written**.

1. **Socratic Clarity** — Question until ambiguity ≤ 0.2
2. **Ontological Precision** — Solve the root problem, not symptoms
3. **Evolutionary Loops** — Each evaluation cycle feeds back into better specs

```
Interview → Seed → Execute → Evaluate
    ↑                           ↓
    └─── Evolutionary Loop ─────┘
```

## ooo Commands

Each command loads its agent/MCP on-demand. Details in each skill file.

| Command | Loads |
|---------|-------|
| `ooo` | — |
| `ooo interview` | `ouroboros:socratic-interviewer` |
| `ooo seed` | `ouroboros:seed-architect` |
| `ooo run` | MCP required |
| `ooo evolve` | MCP: `evolve_step` |
| `ooo evaluate` | `ouroboros:evaluator` |
| `ooo unstuck` | `ouroboros:{persona}` |
| `ooo status` | MCP: `session_status` |
| `ooo setup` | — |
| `ooo help` | — |

## Agents

Loaded on-demand — not preloaded.

**Core**: socratic-interviewer, ontologist, seed-architect, evaluator,
wonder, reflect, advocate, contrarian, judge
**Support**: hacker, simplifier, researcher, architect
<!-- ooo:END -->
