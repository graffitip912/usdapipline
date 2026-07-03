# WWCB 이미지 큐레이션 도구 — 변경 이력 (as-is → to-be)

> seed.yaml 제약: "검증 실패 이력은 as-is→to-be 형태로 기록하여 추적 가능해야 함"

---

## v1 → v2 (2026-07-02)

### 변경 요청
사용자 요청 3건:
1. 썸네일 해상도가 너무 낮음
2. PDF 원문 페이지를 볼 수 있도록 하기 (이미지 위치 이동 포함)
3. International Weather and Crop Summary 섹션 이미지 일괄 제외 (111건)

### as-is (v1)
| 항목 | 상태 |
|------|------|
| 썸네일 | 200px, JPEG q45 |
| PDF 원문 보기 | 없음 |
| International Weather | 수동 제외 필요 (111건 미분류) |
| 레이아웃 | 썸네일 + 메타데이터 2열 카드 |
| 파일 크기 | 2.2 MB |
| 이미지 수 | 297개 전체 썸네일 포함 |

### to-be (v2)
| 항목 | 상태 |
|------|------|
| 썸네일 | 280px, JPEG q55 |
| PDF 원문 보기 | "원문 pN" 버튼 → 모달에 PDF 페이지 표시 (103페이지 렌더) |
| International Weather | 자동 제외 (state 초기값 'excluded') |
| 레이아웃 | v1과 동일 (썸네일 + 메타데이터 2열) |
| 파일 크기 | 9.3 MB |
| 이미지 수 | 297개 전체 썸네일 + 103개 PDF 페이지 렌더 |

### 문제점 (v2에서 발견)
| 문제 | 원인 | 심각도 |
|------|------|--------|
| JSON 내보내기 버튼 미작동 | Blob URL + a.click() → Artifact 샌드박스 CSP 차단 | **심각** — 핵심 기능 불능 |
| 자체 검수 누락 | 크기 최적화에 시야 고착, 인터랙티브 기능 검증 건너뜀 | **프로세스 결함** |

### 수정 (v2 패치)
- JSON 내보내기: Blob URL → 모달 + textarea + 클립보드 복사 (navigator.clipboard + execCommand 폴백)
- 모달 img display 상태 복원 로직 추가

---

## v2 → v3 (2026-07-02)

### 변경 요청
사용자 요청 2건 + 프로세스 개선 1건:
1. 이미지 해상도 여전히 낮음 — 원본과 차이가 큼
2. 이미지만으로는 맥락 파악 불가 — PDF 페이지를 카드에 통합 필요
3. (프로세스) 배포 전 전체 기능 검증 수행 필수

### as-is (v2 패치 후)
| 항목 | 상태 |
|------|------|
| 썸네일 | 280px, JPEG q55 |
| PDF 원문 보기 | 별도 버튼 클릭 → 모달에서만 확인 가능 |
| 카드 레이아웃 | 썸네일(좌) + 메타데이터(우) — PDF 맥락 분리 |
| 제외 항목 표시 | 반투명 카드 (이미지 포함, 공간 차지) |
| JSON 내보내기 | 모달 + textarea (패치 완료) |
| 파일 크기 | 9.3 MB |

### to-be (v3)
| 항목 | 상태 |
|------|------|
| 이미지 품질 | 380px, JPEG q62 (면적 3.6배↑, 품질 37%↑) |
| PDF 원문 보기 | 카드 좌측에 상시 표시 (480px, q35) |
| 카드 레이아웃 | PDF 페이지(좌) + 이미지/메타데이터(우) — 맥락 통합 |
| 제외 항목 표시 | 접이식 목록 (이미지 미포함, 공간 절약) + 개별 복원 버튼 |
| JSON 내보내기 | 모달 + textarea + 2단계 클립보드 폴백 |
| 파일 크기 | 9.3 MB |
| 배포 전 검증 | 14개 인터랙티브 기능 × 샌드박스 제약 대조 완료 |

### 산출물
| 산출물 | 위치 | 비고 |
|--------|------|------|
| 큐레이션 도구 v3 | Artifact (curation-tool-v3.html) | 9.3MB, 186 활성 + 111 자동제외 |
| 빌드 스크립트 v3 | scratchpad/build_curation_v3.py | PyMuPDF + PIL 기반 |
| PDF 페이지 렌더 | 103페이지 (International Weather 제외) | 빨간 테두리 = 이미지 위치 |

---

## 큐레이션 결과 Import (2026-07-02)

### as-is
| 항목 | 상태 |
|------|------|
| 큐레이션 결과 | 사용자 클립보드에 JSON 297건 |
| ML 데이터셋 | 미생성 |

### to-be
| 항목 | 상태 |
|------|------|
| 원본 결정 파일 | `data/curated/wwcb_images/wwcb_curation_dicisions.json` |
| 학습 데이터셋 | `data/curated/wwcb_images/dataset.jsonl` (176건 승인) |
| 제외 목록 | `data/curated/wwcb_images/excluded.jsonl` (121건 제외) |
| 메타데이터 | `data/curated/wwcb_images/metadata.json` |
| curator | phn912@naraspace.com |

### 큐레이션 통계
- **승인 176건**: 전부 map 카테고리, 34개 섹션에 분포
- **제외 121건**: International Weather 111건 + 사용자 수동 제외 10건
- **지역 분포**: United States 69, Mexico 37, Europe 22, 미분류 48
- **미처리 0건**: 전건 처리 완료

---

---

# WASDE 수집기 — 변경 이력

## HEAD 탐색 circuit breaker 추가 (2026-07-02)

### as-is
| 항목 | 상태 |
|------|------|
| `_discover_latest_csv_url()` | 18개월 순차 HEAD 요청, 조기 탈출 없음 |
| 서버 불응 시 소요 시간 | 최대 810초 (18 URL × 3 재시도 × 15초 타임아웃) |
| 타임아웃 | 15초 |

### to-be
| 항목 | 상태 |
|------|------|
| circuit breaker | 3회 연속 실패 시 즉시 중단 (`max_consecutive_failures = 3`) |
| 서버 불응 시 소요 시간 | 최대 90초 (3 URL × 3 재시도 × 10초) |
| 타임아웃 | 10초 (15→10 축소) |
| 로그 | 중단 시 warning 메시지 출력 |

### 근본 원인
코드 작성 시 서버 불응(timeout) 시나리오를 고려하지 않음. HEAD 탐색 루프에 조기 탈출 조건이 없어, 서버가 응답하지 않으면 전체 파이프라인이 장시간 블로킹됨.

### 파일
- `collector/m1_structured/wasde.py` line 64-91

---

## WASDE 대체 소스 폴백 + graceful degradation (2026-07-02)

### as-is
| 항목 | 상태 |
|------|------|
| CSV 탐색 | 단일 URL 템플릿 (`www.usda.gov`) |
| 서버 장애 시 | `RuntimeError` 발생 → 전체 파이프라인 중단 |
| PDF 탐색 | 단일 base URL (`www.usda.gov`) |
| PDF 아카이브 스캔 | 오래된 것부터 순서대로 (since→present), circuit breaker 없음 |

### to-be
| 항목 | 상태 |
|------|------|
| CSV 탐색 | 3개 URL 템플릿 순차 시도 (www.usda.gov → usda.gov → nass.usda.gov) |
| 서버 장애 시 | graceful skip (log.error + return), 파이프라인 계속 진행 |
| PDF 탐색 | 3개 base URL 순차 시도 (www.usda.gov → usda.gov → Cornell Library) |
| PDF 아카이브 스캔 | 최신→과거 역순, 5회 연속 실패 시 조기 종료 |
| max_loop_iterations | re-collect 엔드포인트에서 harness.yaml 설정(10) 강제 적용 |
| admin UI | verification history as-is/to-be 상세 보기 + linked CR 표시 |

### 파일
- `collector/m1_structured/wasde.py` — URL_TEMPLATES 멀티 템플릿 + graceful return
- `collector/m2_reports/wasde_pdf.py` — WASDE_PDF_BASES 멀티 소스 + circuit breaker
- `api/routers/verification.py` — max_loop_iterations 강제 적용
- `dashboard/src/app/admin/page.tsx` — verification history 상세 패널

---

## 공식 ESMIS/Cornell API 전환 (2026-07-03)

### 배경
www.usda.gov 전세계 장애 확인 (외부 네트워크 WebFetch에서도 타임아웃 — 로컬 문제 아님).
2026-07-02에 추가했던 추측성 폴백 URL은 전부 무효로 판명:
- `usda.gov` (bare) → 동일 서버로 리다이렉트, 동일 타임아웃
- `release.nass.usda.gov` → 존재하지 않는 경로
- `downloads.usda.library.cornell.edu` → DNS 미해석 (NAL 이관으로 폐기된 도메인)

공식 문서 조사로 확인된 정식 경로:
- **Cornell ESMIS API**: `usda.library.cornell.edu/api/v1/release/findByIdentifier/wasde?latest=true` (무인증 JSON, 699건 이력)
- **ESMIS 파일 호스트**: `esmis.nal.usda.gov/sites/default/release-files/...` (USDA 국립농업도서관)
- **WWCB 릴리스 페이지**: `esmis.nal.usda.gov/publication/weekly-weather-and-crop-bulletin/{YYYY-MM-DD}` (날짜 기반)

### as-is
| 항목 | 상태 |
|------|------|
| wasde CSV | www.usda.gov 단일 의존 + 무효 추측 폴백 2개, 실패 시 graceful skip만 (데이터 없음) |
| wasde_pdf | www.usda.gov URL 패턴 추측 + HEAD 프로빙, 실행 1460s, PDF 0건 |
| wwcb | www.usda.gov 직접 다운로드 + URL 패턴 추측, 실행 2001s, PDF 0건 |
| wwcb_images | `fitz`(PyMuPDF) 모듈 미설치로 즉시 실패 |
| export_sales | 재시도 대기 1m/5m/10m/15m×5회 → 서버 500 시 실행 5.2시간 |

### to-be
| 항목 | 상태 |
|------|------|
| 신규 `common/esmis.py` | 공식 Cornell API + ESMIS 페이지 클라이언트 (릴리스 목록/파일 URL/날짜 조회) |
| wasde CSV | OCE CSV 우선(circuit breaker ~60s) → ESMIS XML 폴백. US 밀/옥수수/대두 테이블 파싱, 141 레코드 검증 완료, 124s |
| wasde_pdf | Cornell API가 정확한 PDF URL 제공 → 추측/프로빙 전면 제거 |
| wwcb | ESMIS 날짜 기반 릴리스 페이지 → PDF 링크 추출. 추측 패턴 제거 |
| wwcb_images | PyMuPDF 1.28.0 설치 완료 |
| export_sales | 재시도 30s/60s/120s×3회 (최대 ~3.5분) |

### XML 파서 범위 (명시적 제한)
- 파싱 대상: sr11(US 밀), sr12 matrix2(US 옥수수), sr15 matrix1(US 대두) — region='US'
- World 테이블(sr18/22/28)과 대두박/대두유(sr15 matrix2/3)는 미파싱 (CSV 복구 시 자동 보완)
- 월별 스냅샷 누적 방식: 기존 parquet과 병합, (commodity, obs_date, metric, region, marketing_year, report_date) 중복 제거

### 적대적 코드 리뷰 피드백 루프 (2026-07-03, 배포 전 검증)
1차 구현에 대해 자체 코드 리뷰 에이전트(라이브 HTTP 검증 병행)를 실행 — critical 2건 / major 4건 / minor 10건 발견, 전건 수정 또는 처리:

| # | 심각도 | 결함 (as-is) | 수정 (to-be) |
|---|--------|-------------|-------------|
| 1 | critical | Cornell API 301 리다이렉트가 쿼리스트링 유실 → 페이지네이션 무력화 (항상 page 0) | API 베이스를 `esmis.nal.usda.gov/api/v1` 직접 호출로 변경, page0/page1 분리 라이브 재검증 |
| 2 | critical | ESMIS 병합 시 신규 행 `ingested_at=NaT` → pandera가 신규 레코드 전량 드롭 | concat 전에 `validate_and_stamp` 선행 |
| 3 | major | dedupe 키에 report_date 누락 → CSV가 축적한 월별 vintage 파괴 | subset에 `report_date` 추가 |
| 4 | major | WWCB 화요일 고정 프로빙 → 공휴일 주차(수요일 발행) 영구 누락 | 주차별 화→수→월 후보 프로빙 |
| 5 | major | ESMIS 장애 시 예외 전파 (graceful degradation 컨벤션 위반) | wasde/wasde_pdf esmis 호출 try/except + CSV 실패 시 ESMIS 폴백 |
| 6 | major | 변경 이력 문서 (본 문서에 기록됨 — 리뷰 시점 누락 오인) | 본 섹션 |
| 7-15 | minor | 죽은 정규식, 미사용 import, 도달 불가 재시도 대기, manifest 선기록, 각주 다중 미제거, 날짜 파싱 무로그 skip, marketing_year 불일치, USER-CONFIG 마커 누락, docstring 오류 | 전건 수정 |
| 21 | major(기존) | export_sales dedupe에 marketing_year 누락 → 신곡/구곡 중첩 주차 데이터 손실 (이번 변경 이전부터 존재) | subset에 `marketing_year` 추가 |
| 16,17 | info | wasde_pdf 동월 재발행(v2) 미갱신 / CSV 우선 프로빙 비용(~60초) | 수용 (Phase 1 아카이브 목적, CSV가 최고 품질 소스) |

### Exit Condition 진행 기록 (2026-07-03)

| 조건 | 상태 | 근거 |
|------|------|------|
| harness_config_exists | 충족 | Stage 1 |
| verification_history_operational | 충족 | wasde 실패 이력 as-is→to-be 자동 기록 + 해결 마감 (6ce72c83b39c) |
| all_sources_runnable | **충족 (사용자 승인)** | 9/9 수집기 통과 + 샘플 대조 확인 |
| change_loop_closed | **충족 후보 (루프 완주)** | CR 5dd477d6f240: 생성→적용→재수집→verified + 승인 리뷰. 테스트 CR(2802667ecd38)은 rejected 처리, 더미 리뷰 10건 제거. 최종 판정은 사용자 게이트 |
| user_data_verification_gate | **충족 (2026-07-03 05:37)** | 정규화 데이터 보유 5개 소스 전부 admin에서 사용자 승인 (gtr/quickstats/psd/ers_feedgrains/wasde — user_reviews.jsonl 기록 확인). wwcb·wasde_pdf는 원시 수집기(정규화 데이터 없음), wwcb_images는 큐레이션 도구 전수 검토(176 승인/121 제외)로 기검증, export_sales는 외부 장애 보류 |
| user_verified_pipeline | **충족 (사용자 최종 승인 2026-07-03)** | 4단계(수집→데이터→API→대시보드) 확인 완료. export_sales는 'API 계약 공식 Swagger 검증 완료 + FAS opendata 전체 장애로 데이터 대기' 상태로 명시하고 승인 — 복구 시 금요일 크론이 자동 수집. 복구 감지: `/api/esr/datareleasedates` 200 (부검 문서 8절 참조) |

**Stage 3 완결 (2026-07-03)** — Exit conditions 6/6, 평가 원칙 8/8. FAS 심층 조사로 ESRQS 이관 가능성 배제(보고자 포털), opendata API 계약이 공식 Swagger와 일치함을 확인 — 수집기 코드 무결 판정.

### 파이프라인 최종 확인 중 발견·수정 (2026-07-03)

**소스 명칭 이중화로 인한 상태 뷰 정합성 결함** (최초 구현부터 존재, 최종 확인 중 발견):

| 항목 | as-is | to-be |
|------|-------|-------|
| 상태 API 항목 수 | 15개 (정식명 USDA_* + 실행 키 + test_source 혼재, 중복 표시) | canonical 9개 (실행 키 기준 병합) |
| 검증 상태 조인 | manifest 정식명으로 조회 → 실행 키로 기록된 리뷰와 불일치 (USDA_WASDE=not_verified vs wasde=approved) | 실행 키로 통일 — admin Quick Review→preview→review 체인 정상화 |
| 매핑 관리 | 라우터에 `USDA_{key.upper()}` 추측 (export_sales→USDA_FAS_ESR 불일치로 never_run 오표시) | `collector/run.py MANIFEST_SOURCES` 단일 레지스트리 |
| test_source | manifest에 테스트 행 잔존 | 제거 |

**export_sales 상태 확인**: FAS_OPENDATA_API_KEY 정상 설정, FAS OpenData API 자체가 500 반환 (라이브 확인) — www.usda.gov와 별개의 외부 서버 장애. 수집기는 예외 없이 우아하게 저하 (수집 0건, 산출물 없음). 알려진 제약: graceful skip 시 manifest에 시도 기록이 남지 않아 상태가 never_run으로 표시됨.

### admin Run 버튼 무반응 + 콘솔 에러 (2026-07-03, 사용자 보고)

| 항목 | as-is | to-be |
|------|-------|-------|
| Run 버튼 (근본) | 정식명(USDA_WASDE)으로 POST → 서버가 HTTP 200 + `status:"error"` 반환, UI는 응답 무시 → **조용한 no-op** (소스 명칭 이중화 결함의 증상) | canonical 실행 키로 POST — API 레벨 end-to-end 검증 완료 (POST→백그라운드 수집→5초 내 manifest 갱신) |
| Run 버튼 (피드백) | 성공해도 무표시, 2초 후 1회만 새로고침 (수집은 수십 초~수 분) | 시작/오류 배너 표시 + 3/12/30초 단계적 자동 새로고침 |
| 콘솔 에러 | 버튼 핸들러(Run/Approve/Apply/Re-collect/Verify/Reject/Pause/Resume/CR생성)에 catch 없음 → fetch 실패 시 unhandled promise rejection | 전 핸들러 try/catch + 오류 배너로 표면화 |

### export_sales 판정 기록 (2026-07-03, 사용자 지시)

- FAS OpenData API 서버 500 지속 → **FAS 복구 후 재확인, 그 후 파이프라인 승인** (승인 보류)
- 재확인 경로: 주간 스케줄(금 06:00 UTC)에 export_sales 포함 — FAS 복구 시 자동 수집됨. 수동 확인은 admin Run 버튼 또는 `python -m collector.run --source export_sales`

### admin 데이터 미리보기 모달 추가 (2026-07-03, 사용자 질문 "어디서 확인?"으로 결함 발견)

| 항목 | as-is | to-be |
|------|-------|-------|
| 데이터 확인 UI | `getDataPreview` API 클라이언트만 존재, **어느 페이지도 미사용** — "확인 후 Approve"를 요구하면서 확인할 화면이 없음 | Quick Review 카드에 Preview 버튼 → 모달 (샘플 행 테이블 + 행/컬럼 수 + 스키마 배지 + 이상치 플래그) → 모달 내 "확인 완료 — Approve" |
| 원시 수집기 처리 | — | 정규화 데이터 없는 소스(wwcb 등)는 안내 배너 표시 |

배포 게이트 `verify_pipeline.py` 8/8 통과 후 반영.

### admin 대시보드 UX 개선 4건 (2026-07-03, 사용자 제안)

| # | as-is | to-be |
|---|-------|-------|
| 1. Run 진행 표시 | POST 응답 즉시 버튼 복원 — 백그라운드 수집 중임을 알 수 없음 | Run 시점 last_attempt 기준선 저장 → 5초 폴링 → 완료 시 자동 배너. 카드에 파란 "collecting" 상태 + 스피너 애니메이션, 진행 중 Run 버튼 비활성 |
| 2. 상태 색상 구분 | 카드 배경색만으로 상태 표현 | 진한 단색 상태 배지 신설: collecting(파랑)/success(초록)/failed(빨강)/stale(주황)/never_run(회색) — 검증 pill과 시각적으로 분리 |
| 3. 미리보기 잘림 | 오래된 20행, 좁은 모달, 긴 값 확인 불가 | 서버측 최신순 정렬(report_date/obs_date desc) + 50행 + max-w-6xl 모달 + 고정 헤더 + 셀 truncate/hover 툴팁 + 안내문 |
| 4. 실패/재시도 표시 | retry만 소문자 텍스트, 검증 실패 건수 미표시 | `unresolved_failures` 필드 신설(API) → 빨간 "검증실패 N건" 배지, Retries 강조색, rejected 검증 상태 색 추가 |

**운영 사고 기록**: 백엔드 수정 반영 확인 중 좀비 리스너 발견 — 죽은 PID(10016)가 :8000 소켓을 점유한 채 **구버전 코드로 계속 응답** (SO_REUSEADDR 이중 바인딩). 전체 python 프로세스 정리 → 포트 해제 확인 → 단일 서버 재기동으로 해결. 교훈: 서버 재시작 후에는 반드시 신규 필드/동작으로 실제 반영을 확인할 것 (배포 게이트가 이를 잡아냄).

### Swagger(OpenAPI) 문서 구성 (2026-07-03, 사용자 요청)

| 항목 | as-is | to-be |
|------|-------|-------|
| API 버전 | 0.1.0 | **0.2.0** |
| 앱 설명 | 1줄 영문 | 마크다운 — 데이터 흐름, 9개 소스 표(주기 포함), ESMIS 폴백, Phase 1 인증 정책, 소스 키 규칙 |
| 태그 메타데이터 | 없음 | 6개 태그(collector/grain/images/schedule/verification/health) 한글 설명 |
| 오퍼레이션 설명 | 31개 중 17개 | **31/31 (100%)** — grain 3종(가격/수급/재고 카테고리 설명), verification 11종(승인 게이트·CR 루프 상태 전이 설명), health |
| 검증 | — | /docs·/redoc 200 렌더 확인, 배포 게이트 8/8 통과 |

접근: Swagger UI `http://localhost:8000/docs`, ReDoc `http://localhost:8000/redoc`

### Stage 3 재확정 (2026-07-03, 사용자 최종 판정)

부검(autopsy_stage1-3.md)의 감사 지적 3건을 R1~R3로 해소하고 사용자가 추가 확인 후 **Stage 3 완결을 재확정**.
- 재확정 근거: export_sales 침묵 실패 제거(실동작 검증), harness.yaml 배선, 해결 기록 시스템 경로 확보, 게이트 8/8
- 잔여 백로그 R4~R7은 차기 작업 시 우선 검토 항목으로 유지
- 부검 문서의 "정직한 점수 ~4/6" 지적 사항 중 구조적 결함은 해소, '루프 기록 소급' 건은 이력 사실 그대로 문서에 보존 (은폐하지 않음)

### 부검 백로그 R1~R3 이행 (2026-07-03, 사용자 승인)

| # | as-is (감사 발견) | to-be |
|---|------------------|-------|
| R1 | export_sales가 전 실패를 삼키고 "ok" 반환 — manifest 기록 0, 감시 불가. seed 기준 'skipped' 미구현 | 키 미설정→`manifest.record_skipped()`(신규, status='skipped'), 요청 전부 실패→RuntimeError로 가시화. **실동작 검증**: FAS 장애 중 실행 → status=failed + manifest 기록 + 검증 이력 자동 생성 확인. 대시보드 skipped 색상(보라) 추가 |
| R2 | harness.yaml runtime_rules 4그룹 중 3개 장식 (코드 미소비) | 배선 완료: `manifest._max_retries()`←retry_policy, preview sample_rows/z-score←verification, 스케줄러 크론←schedule_triggers. TestClient로 propagation 검증 (preview 기본 20행 = harness 값) |
| R3 | `update_history`(해결 기록)가 API 어디서도 호출 불가 — 해결 이력이 손기록 | `PUT /api/verification/history/{id}/resolve` 신규 (404/400 계약 검증) + admin 상세 패널에 미해결 이력 '해결 처리' 폼 |

배포 게이트 8/8 재통과. R4~R7은 백로그 유지.

### 커밋 전 최종 리뷰 (2026-07-03)

리뷰 에이전트 최종 위생 점검 결과 및 조치:

| 발견 | 심각도 | 조치 |
|------|--------|------|
| requirements-lock에 apscheduler/pyyaml 누락 | **커밋 차단** | lock 재생성 스크립트의 정규식 버그(`uvicorn[standard]`의 `]`에서 배열 캡처 조기 종료) → tomllib 파싱으로 교체, 42개 재생성 |
| imagehash/pytesseract 미설치 (이미지 해시 필터가 조용히 비활성) | **커밋 차단** | venv에 설치 + lock 포함 |
| pyproject 상한이 검증 환경과 충돌 (pandas<3 vs 3.0.3 등) | **커밋 차단** | pandas<4, pyarrow<25, Pillow<13으로 정정. uvicorn[standard]→uvicorn (extras 미설치로 검증됨) |
| 미사용 import 4건 (verification/run/wwcb_images/scheduler) | 정리 | 제거, 게이트 8/8 재통과 |
| CLAUDE.md.bak 잔존 | 정리 | 삭제 |
| 비밀키/대용량 파일/인코딩/문서 상호참조 | 이상 없음 | — |

루트 README.md 신설 (사람용 개요 — Quick Start, 소스 표, 문서 색인).

### Stage 3 마감 평가 (2026-07-03)

- **평가 원칙 8/8 충족** (seed.yaml evaluation_principles 대비, 근거는 Stage 3 보고서 참조)
- **Exit conditions 4/6 충족**: harness_config_exists, verification_history_operational, all_sources_runnable(승인), change_loop_closed(승인)
- **잔여 2건**: user_data_verification_gate(admin Quick Review 사용자 승인), user_verified_pipeline(FAS 복구 후 export_sales 재확인 → 사용자 최종 승인)
- requirements-lock.txt 재생성: pip freeze 오염(공유 venv 119개) → pyproject 의존성 폐쇄 기반 curated 35개 (PyMuPDF 포함)
- FAS OpenData API 상태 재확인 (2026-07-03): 여전히 500 — 외부 대기 유지

### 최종 승인 (2026-07-03)

- 사용자 검증 샘플 대조 확인 완료 → **ESMIS 전환·주간 스케줄 변경·all_sources_runnable 충족 승인**
- 검증 샘플: https://claude.ai/code/artifact/87dfbe58-b0d4-48d6-939e-37ec9eb8b640
- **부검 자료**: [`postmortem_2026-07_usda_outage.md`](postmortem_2026-07_usda_outage.md) — 사건 개요/타임라인/근본 원인(5 Whys)/알려진 제약/재발 방지. 추후 수집 문제 발생 시 최우선 참조 문서

### 운영 정책 반영 (2026-07-03, 사용자 문의 대응)

| 항목 | as-is | to-be |
|------|-------|-------|
| ESMIS 크롤 정책 | 전 호스트 1초 간격 (robots.txt 미확인) | robots.txt `Crawl-delay: 10` 실측 확인 → esmis.nal.usda.gov / usda.library.cornell.edu 호스트별 10초 간격 적용 (`common/http.py` `_HOST_MIN_INTERVAL_SEC`) |
| API 키 | — | ESMIS/Cornell API 무인증 확인 (키 불필요, 쿼터 문서 없음 — crawl-delay가 유일한 명시 정책) |
| wasde_pdf 증분 | 매 실행 since까지 전 페이지 순회 | 페이지 전체가 이미 수집된 경우 조기 종료 → 주기 실행 시 API 호출 ~2회 |
| 주간 스케줄 | 월요일 06:00 UTC (발행 후 최대 6일 지연) | 금요일 06:00 UTC (WWCB 화/수, Export Sales·GTR 목 발행 → 당주 내 수집) |

---

## 프로세스 결함 이력

| 일시 | 결함 | 근본 원인 | 조치 |
|------|------|----------|------|
| 2026-07-02 v2 배포 | JSON 내보내기 미작동 | 자체 검수 미수행, Artifact 샌드박스 제약 미대조 | feedback memory 기록, 배포 전 검증 프로토콜 수립 |
| 2026-07-02 v1~v3 전체 | as-is/to-be 변경 이력 미기록 | seed.yaml 명시 제약 무시, 기존 추적 시스템 미활용 | 본 문서 소급 작성, feedback memory 추가 |
| 2026-07-02 | 검증 없는 추측성 폴백 URL 배포 | 공식 문서 미조사, 데이터 소스 신뢰성 검증 생략 | 공식 API 전환, 소스 추가 시 라이브 검증 의무화 |
| 2026-07-03 | **피드백 루프가 Run 버튼 결함을 통과시킴** | ① 리뷰 범위를 수정 파일로 한정 (통합 경계 미검사) ② HTTP 200만 확인 (시맨틱 미단언) ③ 사용자 상호작용 미실행 | `scripts/verify_pipeline.py` 시맨틱 e2e 검증 스크립트 신설 (8체크, 배포 게이트) — CLAUDE.md Testing 등재, feedback memory 강화 |
