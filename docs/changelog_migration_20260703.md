# 변경 이력 — 하드웨어 이전 (2026-07-03)

새 머신(Windows 10 Home, NST_TEST_PM)으로 이전하며 발견/수정한 사항의 as-is/to-be 기록.

## 1. pyproject.toml — 신규 환경에서 `pip install -e .` 실패

| 항목 | 내용 |
|------|------|
| failure_reason | setuptools 자동 패키지 탐색이 flat-layout에서 top-level 디렉토리 5개(api, data, common, collector, dashboard)를 발견하고 빌드 거부. 기존 머신에서는 구버전 캐시/이미 설치된 환경이라 드러나지 않던 잠복 결함. |
| as_is | `[tool.setuptools]` 패키지 지정 없음 → 신규 clone에서 editable install 불가 |
| to_be | `[tool.setuptools.packages.find] include = ["collector*", "common*", "api*"]` 추가 → Python 패키지 3개만 명시적 포함 |
| resolution_method | pyproject.toml에 packages.find 지시자 추가 후 `pip install -e .` 성공 확인 |
| 산출물 | `pyproject.toml` (repo 커밋 필요) |

## 2. migration-bundle restore.ps1 — 인코딩으로 인한 파싱 실패

| 항목 | 내용 |
|------|------|
| failure_reason | 스크립트 내 한글 문자열이 인코딩 불일치(BOM 없는 UTF-8을 PS 5.1이 CP949로 해석)로 깨지며 문자열 터미네이터 파싱 오류 → 스크립트 실행 불가 |
| as_is | 한글 메시지 포함 restore.ps1 (BOM 없음) → `ParserError: The string is missing the terminator` |
| to_be | 메시지를 ASCII로 교체하고 UTF-8(BOM)로 재작성 → 4단계 복원 정상 수행 |
| resolution_method | Out-File -Encoding utf8로 재작성. **주의: zip 번들 내 restore.ps1은 여전히 구버전** — 다른 머신에서 재사용 시 동일 오류 발생. zip 갱신 필요. |
| 산출물 | `C:\workspace\migration-bundle-20260703\restore.ps1` (번들 로컬 폴더만 수정됨) |

## 3. 신규 머신 환경 구성

| 항목 | 내용 |
|------|------|
| as_is | Python 미설치 (Windows Store 스텁만 존재), Node.js v22.23.1 기설치 |
| to_be | Python 3.12.10 (winget, Python.Python.3.12) + .venv + 의존성 설치 완료 |
| resolution_method | `winget install Python.Python.3.12` → setup_env.ps1 재실행 |

## 4. export_sales 주간 자동 수집 제외 (이전 후 후속 결정)

| 항목 | 내용 |
|------|------|
| failure_reason | FAS opendata API 전면 장애 — `/esr/commodities`, `/esr/exports/...` 모두 HTTP 500. API 키 유효(40자 설정 확인), 인증(401)/폐지(404) 아님. 2026-07-03 07:04 수집 실패 기록 + 17시대 재확인까지 최소 하루 지속. |
| as_is | SOURCES["export_sales"] 스케줄 태그 "weekly" → 매주 금요일 cron마다 재시도 낭비 + 실패 노이즈 |
| to_be | 태그 "manual"로 변경 — 주간 자동 수집 제외, 모듈·수동 Run 버튼·기존 데이터 조회는 보존. FAS 복구 시 USER-CONFIG 주석 위치에서 "weekly"로 복귀 |
| resolution_method | collector/run.py SOURCES 태그 변경 + harness.yaml sources 목록 + CLAUDE.md 표 + api/main.py Swagger 설명 동기화. VerificationHistory 959f09f463d4를 시스템 경로(PUT /verification/history/{id}/resolve)로 as-is→to-be 마감. |
| 산출물 | collector/run.py, harness.yaml, CLAUDE.md, api/main.py |

## 이전 성공 판정 (RESTORE.md 검증 절차)

1. ~~setup_env.ps1~~ ✅ (pyproject.toml 수정 후 통과)
2. ~~verify_pipeline.py~~ ✅ **8/8 통과** (API :8000 + 대시보드 :3000 기동 상태)
3. ~~승인 기록 6건~~ ✅ `/api/verification/reviews` 6건, 전원 `user_verdict=approved`, 디스크 원본(`data/meta/verification/user_reviews.jsonl`) UTF-8 무결 확인 (한글 remarks 정상 디코딩)
4. 잔여: 사용자 브라우저에서 :3000/admin 승인 기록 육안 확인

## 미커밋 변경 (사용자 결정 대기)

- `pyproject.toml` — 위 1번 수정. 커밋하지 않으면 다음 신규 머신에서 동일 실패 재발.
- `dashboard/package-lock.json` — npm 버전 차이로 인한 메타데이터 정규화(libc 필드 제거). 기능 영향 없음.
