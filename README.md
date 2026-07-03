# USDA Grain Pipeline

CBOT 곡물 선물 가격 예측을 위한 USDA 데이터 수집·분석 파이프라인.
9개 공식 USDA 소스에서 옥수수/대두/밀 데이터를 수집하고, FastAPI로 서빙하며, Next.js 대시보드로 시각화합니다.

```
USDA APIs/PDFs → collector/ (9 sources) → data/ (parquet/PDF/이미지)
                                              ↓
                                      api/ (FastAPI :8000, Swagger /docs)
                                              ↓
                                    dashboard/ (Next.js :3000)
```

## Quick Start

```bash
# Python backend
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -r requirements-lock.txt
cp .env.example .env                             # API 키 입력 (NASS, FAS)
python -m collector.run --source all             # 전체 수집
python -m uvicorn api.main:app --reload          # API 서버 → http://localhost:8000/docs

# Dashboard
cd dashboard && npm install && npm run dev       # → http://localhost:3000
```

자동 환경 구성: `scripts/setup_env.ps1` (Windows) / `scripts/setup_env.sh` (Linux/Mac)

## 데이터 소스 (9종, 전부 무료·공식)

| 소스 | 내용 | 주기 |
|------|------|------|
| gtr | AMS 곡물 운송 리포트 지수 | 주간 |
| quickstats | NASS QuickStats 통계 API | 주간 |
| export_sales | FAS 수출 판매 API | 주간 |
| wwcb / wwcb_images | 주간 기상·작황 회보 PDF / 이미지 추출 | 주간 |
| wasde / wasde_pdf | WASDE 수급 전망 (CSV/XML) / 원본 PDF | 월간 |
| psd | FAS 생산·수급·유통 CSV | 월간 |
| ers_feedgrains | ERS 사료곡물 연감 CSV | 월간 |

WASDE/WWCB는 www.usda.gov 장애 시 **공식 ESMIS 아카이브**(esmis.nal.usda.gov, 무인증)로 자동 폴백합니다.
운영 정책: ESMIS Crawl-delay 10초 준수, 증분 수집(주기 실행 시 최신 릴리스만).

## 검증 (배포 게이트)

```bash
python scripts/verify_pipeline.py   # 시맨틱 e2e 8체크 — HTTP 200이 아닌 응답 의미+상태 변화를 단언
```

## 문서

| 문서 | 내용 |
|------|------|
| `CLAUDE.md` / `AGENTS.md` | 개발 규칙, 모듈 가이드 (AI 에이전트용 포함) |
| `docs/changelog_curation_tool.md` | 전체 변경 이력 (as-is→to-be) |
| `docs/postmortem_2026-07_usda_outage.md` | www.usda.gov 장애 대응 부검 — 문제 발생 시 최우선 참조 |
| `scripts/portable_checklist.md` | 다른 머신으로 이전 가이드 |
| `seed.yaml` / `harness.yaml` | Ouroboros/dryforge 하네스 명세 |
