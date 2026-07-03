# 부검 자료: www.usda.gov 장애 대응 및 공식 ESMIS 소스 전환

> 작성: 2026-07-03 | 상태: 사용자 승인 완료 (2026-07-03)
> 목적: 추후 수집 파이프라인 문제 발생 시 원인 추적을 위한 부검(postmortem) 기록.
> 관련: `changelog_curation_tool.md` (as-is/to-be 상세), seed.yaml v1.3.0

---

## 1. 사건 개요

| 항목 | 내용 |
|------|------|
| 증상 | wasde/wasde_pdf/wwcb 3개 수집기 전체 실패, 수집기 1회 실행에 13분~5시간 블로킹 |
| 원인 | www.usda.gov 도메인 전세계 장애 (HEAD/GET/robots.txt 전부 타임아웃 또는 connection reset) |
| 판별 근거 | 외부 네트워크(Anthropic WebFetch)에서도 동일 타임아웃 → 로컬 네트워크/방화벽 문제 아님. 타 USDA 도메인(quickstats.nass.usda.gov, apps.fas.usda.gov, ers.usda.gov, esmis.nal.usda.gov)은 정상 |
| 영향 범위 | WASDE CSV(구조화 데이터), WASDE PDF(아카이브), WWCB PDF(주간 회보) — 파이프라인 9개 소스 중 3개 |
| 해결 | USDA 공식 아카이브 ESMIS(esmis.nal.usda.gov, 국립농업도서관) API 기반으로 전환 |
| 부수 발견 | www.usda.gov와 무관한 기존 버그 3건 동시 발견·수정 (아래 6절) |

## 2. 타임라인

| 일시 | 사건 |
|------|------|
| 2026-07-02 | wasde 수집기 955초 블로킹 발견 → circuit breaker 1차 적용 (810s→90s) |
| 2026-07-02 | 원인 판별: www.usda.gov 서버 자체 장애 확인 (코드 문제 아님) |
| 2026-07-02 | **[실책]** 검증 없는 추측성 폴백 URL 3종 추가 (usda.gov, release.nass.usda.gov, downloads.usda.library.cornell.edu) — 전부 무효로 판명 |
| 2026-07-03 | 사용자 지적("수집 단계 문제는 심각, 공식 문서로 해결") → 공식 API 조사 착수 |
| 2026-07-03 | Cornell ESMIS API + esmis.nal.usda.gov 파일 호스트 발견, 라이브 검증 |
| 2026-07-03 | `common/esmis.py` 신규 작성, wasde/wasde_pdf/wwcb 재작성 |
| 2026-07-03 | 적대적 코드 리뷰 피드백 루프 → critical 2건 포함 16건 발견·수정 |
| 2026-07-03 | 전체 9개 수집기 재검증 통과 (기준 10개 전건 충족) |
| 2026-07-03 | 사용자 데이터 샘플 대조 확인 → 승인 |

## 3. 근본 원인 분석 (5 Whys)

1. **왜 수집이 실패했나** — www.usda.gov가 응답하지 않음 (외부 장애)
2. **왜 파이프라인 전체가 장시간 블로킹됐나** — 단일 호스트 하드코딩 + 조기 탈출 없는 재시도 루프 (18개월 × 3재시도 × 15초)
3. **왜 1차 대응(폴백 URL)이 실패했나** — 공식 문서를 조사하지 않고 URL을 추측으로 작성, 검증 없이 배포
4. **왜 추측이 검증 없이 배포됐나** — "폴백 추가"를 코드 수정으로만 보고 데이터 소스 신뢰성 검증 단계를 생략
5. **왜 공식 경로를 처음부터 쓰지 않았나** — 최초 구현 시 www.usda.gov가 정상이어서 대체 경로 조사가 이루어진 적이 없음

**교훈**: 외부 데이터 소스는 (a) 공식 문서 기반으로만 추가하고, (b) 추가 시점에 라이브 검증하며, (c) 반드시 공식 대체 경로를 함께 파악해 둔다.

## 4. 최종 아키텍처

```
WASDE 구조화:  www.usda.gov OCE CSV (1순위, circuit breaker ~60s)
               └─ 실패 시 → Cornell API → ESMIS XML → US 밀/옥수수/대두 파싱 → parquet 병합
WASDE PDF:     Cornell API가 정확한 파일 URL 제공 (추측/프로빙 없음)
WWCB PDF:      ESMIS 날짜 기반 릴리스 페이지 (화→수→월 후보 프로빙)
```

- **Cornell ESMIS API**: `https://esmis.nal.usda.gov/api/v1/release/findByIdentifier/{id}?latest=true&page=N`
  (주의: `usda.library.cornell.edu` 경유 시 301 리다이렉트가 쿼리스트링을 유실시켜 페이지네이션이 깨짐 — 반드시 esmis 호스트 직접 호출)
- **무인증·무료**. 명시 정책은 robots.txt `Crawl-delay: 10`뿐 → `common/http.py`에 호스트별 10초 간격 적용
- **증분 갱신**: 초기 수집분 유지, 주기 실행은 최신 릴리스만 (주간 ~3회, 월간 ~8회 HTTP 호출)
- **스케줄**: 주간 = 금요일 06:00 UTC (WWCB 화/수, Export Sales·GTR 목 발행), 월간 = 15일 06:00 UTC (WASDE 10~12일 발행)

## 5. 변경 파일 목록

| 파일 | 변경 |
|------|------|
| `common/esmis.py` | **신규** — Cornell API + ESMIS 페이지 클라이언트 |
| `common/http.py` | 호스트별 rate-limit (`_HOST_MIN_INTERVAL_SEC`, ESMIS 10초) |
| `collector/m1_structured/wasde.py` | ESMIS XML 폴백 + `_normalize_xml` 파서 + CSV 실패 시 폴백 전환 |
| `collector/m2_reports/wasde_pdf.py` | 전면 재작성 (Cornell API, 증분 조기 종료) |
| `collector/m2_reports/wwcb.py` | 전면 재작성 (ESMIS 릴리스 페이지, 화/수/월 프로빙) |
| `collector/m1_structured/export_sales.py` | 재시도 30s/60s×3회 축소 + dedupe에 marketing_year 추가 |
| `api/scheduler.py` | 주간 크론 월→금 |
| `api/routers/verification.py` | max_loop_iterations(10) 강제 (별건, 하네스 감사 대응) |
| `dashboard/src/app/admin/page.tsx` | 검증 이력 as-is/to-be 상세 패널 (별건) |

## 6. www.usda.gov와 무관한 동시 발견 버그 (부검 시 참고)

| 버그 | 증상 | 수정 |
|------|------|------|
| `fitz`(PyMuPDF) 미설치 | wwcb_images 즉시 실패 | PyMuPDF 1.28.0 설치 (requirements-lock.txt 갱신 필요 시 참고) |
| export_sales dedupe 키에 marketing_year 누락 | 신곡/구곡 중첩 주차 데이터 손실 (최초 구현부터 존재) | subset에 추가 |
| 병합 시 ingested_at NaT | pandera가 신규 레코드 전량 드롭 (신규 코드에서 발견) | 병합 전 validate_and_stamp 선행 |

## 7. 검증 기록

기준 10개 전건 통과 (2026-07-03):
9/9 수집기 정상 종료, wasde 141레코드·3곡물·스키마 통과·ingested_at null 0,
WASDE PDF 29건, WWCB 2026년 25건, manifest 전 소스 기록, 무효 URL 잔존 없음.
샘플 대조: 옥수수 Production 2025/26=17,021 / 밀 Ending Stocks 2026/27=744 / 대두 Crushings 2026/27=2,750 — 원본 PDF와 일치, 사용자 직접 확인.

- 검증 샘플: https://claude.ai/code/artifact/87dfbe58-b0d4-48d6-939e-37ec9eb8b640
- Stage 3 보고서: https://claude.ai/code/artifact/f89fc751-4784-4f7b-ba99-dab02904090a

## 8. 알려진 제약 (향후 문제 발생 시 우선 확인)

1. **XML 파서 범위**: US 밀/옥수수/대두만 (sr11, sr12 matrix2, sr15 matrix1). World 테이블·대두박/대두유 미파싱 → 해당 데이터가 필요한 기능이 비면 이것이 원인. www.usda.gov CSV 복구 시 자동 보완됨
2. **동월 재발행(v2) 미갱신**: wasde_pdf는 `wasde_{Y}_{M}.pdf` 존재 시 스킵 → 정정본 발행 시 `--force` 필요
3. **XML 컬럼 규칙**: 연도 열에 이전월/당월 전망이 중복될 때 문서 순서상 마지막(당월)을 채택 — WAOB가 XML 구조를 바꾸면 파서 점검 필요
4. **WASDE 2025-10 부재**: 정부 셧다운으로 미발행. 수집 결측이 아님
5. **www.usda.gov 복구 시**: CSV(전체 이력, 최고 품질)가 자동으로 1순위 복귀. ESMIS 누적분과 병합 시 report_date 포함 dedupe로 vintage 보존
6. **ESMIS 구조 변경 리스크**: 릴리스 페이지 HTML 파싱(정규식) 의존 — ESMIS가 Drupal 테마를 바꾸면 `common/esmis.py`의 `_RELEASE_FILE_RE` 확인
7. **export_sales = FAS OpenData API 서버측 500** (2026-07-02~03 지속, 키 정상): www.usda.gov와 별개의 외부 장애. 수집기는 우아하게 저하하나 graceful skip 시 manifest에 시도 기록이 없어 상태가 never_run으로 표시됨. FAS 서버 복구 후 재실행하면 자동 정상화
8. **소스 명칭 이중화**: manifest에 수집기 정식명(USDA_*)과 실행 키(wasde 등)가 공존 — 상태/검증 조회는 반드시 `collector/run.py MANIFEST_SOURCES` 매핑을 경유할 것. 새 수집기 추가 시 이 레지스트리에 등록 필수

## 9. 재발 방지 조치

- memory 지침 등록: 검증 기준 수립→자체 피드백 루프→사용자 확인 순서 의무화 (`feedback_verification_loop.md`)
- memory 지침 등록: as-is/to-be 변경 이력 기록 의무 (`feedback_change_tracking.md`)
- 외부 소스 추가 시: 공식 문서 확인 + robots.txt/쿼터 정책 확인 + 라이브 검증을 필수 절차로 수행
- 적대적 코드 리뷰(라이브 HTTP 검증 병행)를 배포 게이트로 사용 — 이번에 critical 2건을 정적 리뷰로는 못 잡았음

## 10. 2차 프로세스 결함: 피드백 루프의 맹점 (2026-07-03 추가)

파이프라인 최종 확인 중 사용자가 admin **Run 버튼 완전 무반응**을 발견 — 피드백 루프를 통과한 상태였음.

**루프가 놓친 이유 3가지**:
1. 리뷰 범위 = 수정한 파일 → UI↔API 통합 경계의 결함(UI는 정식명 전송, API는 실행 키 기대)은 어느 단일 파일에서도 안 보임
2. 검증 = HTTP 상태 코드 → 서버가 200 + `{"status":"error"}`를 반환해도 통과 (조용한 no-op)
3. 버튼 클릭→상태 변화 관찰을 실제로 수행한 적 없음 (페이지 200 응답 ≠ 버튼 동작)

**구조적 수정** — `scripts/verify_pipeline.py` 신설 (재실행 가능한 시맨틱 e2e 검증, 8체크):
- [A] UI→API 계약: api.ts의 모든 호출 경로가 FastAPI 라우트에 존재하는지 자동 대조
- [B] 수집기 상태 canonical 9개 (중복/이물 감지)
- [C] Run 버튼 체인: POST→status=='started' 단언→manifest 상태 변화 관찰 (캐시 skip 시 force 2단계), 잘못된 소스명의 error 계약 확인
- [D] 검증 preview가 UI의 소스 키로 동작 (구조화 5개 소스 데이터 존재)
- [E] 스케줄 pause/resume 왕복
- [F] 대시보드 4페이지 smoke

**운영 규칙**: 이후 모든 변경은 이 스크립트 통과가 배포 게이트 (CLAUDE.md Testing 등재).
UI/API 어느 쪽이든 계약을 바꾸면 [A]/[C]가 자동으로 잡는다.
