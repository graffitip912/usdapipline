# Stage 1~3 종합 부검 (2026-07-03)

> 방법: (1) 시스템 현황 증거 실측, (2) **독립 적대 감사** — "Exit 6/6, 원칙 8/8, 게이트 8/8" 주장을
> 반박하는 것을 목표로 별도 에이전트가 명세 vs 코드/데이터를 대조.
> 원칙: 문서의 주장을 신뢰하지 않고 아티팩트로만 판정.
> 관련: [`postmortem_2026-07_usda_outage.md`](postmortem_2026-07_usda_outage.md) (장애 사건 부검),
> [`changelog_curation_tool.md`](changelog_curation_tool.md) (변경 이력)

---

## 1. 시스템 현황 실측 (2026-07-03)

| 자산 | 실측값 |
|------|--------|
| 정규화 parquet 5종 | psd 77,595 / gtr 16,277 / quickstats 13,001 / ers_feedgrains 8,593 / wasde 141행 |
| 원시 PDF | wasde 29건(25MB) + wwcb 46건(512MB) |
| 추출 이미지 | 1,030개 PNG (`data/assets/wwcb/images/` — dataset.jsonl의 image_path는 `data/` 기준 상대경로) |
| 큐레이션 데이터셋 | 176건 승인 (사용자 전수 검토) |
| 검증 스토어 | history 2건(전건 해결), reviews 6건(전건 approved), CR 2건(verified 1/rejected 1) |
| git | main = origin/main (3a2fbdd, 61de6d5 push 완료) |

부검 중 발견·즉시 조치: wwcb_images fitz 실패 이력(cb8d6830)이 미해결로 방치 → to_be 해결 기록 마감.

## 2. 독립 감사: 주장 vs 실제 (핵심 결과)

**감사 결론: "Exit 6/6"은 과장. 정직한 점수 약 4/6. 파이프라인 자체는 실재하고 건강함
(8/9 소스 데이터 실증, 게이트 8/8은 진짜 시맨틱 검증으로 확인됨).**

| Exit Condition | 주장 | 감사 판정 | 근거 |
|----------------|------|----------|------|
| harness_config_exists | 충족 | **부분 반박** | 파일은 존재하나 **runtime_rules 4개 그룹 중 3개가 장식** — change_request_policy만 코드가 소비. weekly 크론이 3곳에서 상충했음(Mon/Fri) → 부검 중 동기화 완료. retry_policy·verification 임계값은 선언만 되고 하드코딩과 미연결 |
| all_sources_runnable | 충족(승인) | **기준 미달** | 9개 전부 import·실행 가능하나, 기준의 `status='skipped'`가 **코드에 존재하지 않음**. export_sales는 전 실패를 삼키고 "ok" 반환 — manifest 기록 0, 장애 중에도 감시 불가 |
| verification_history_operational | 충족 | 충족 (경고) | 자동 기록은 실증됨(fitz 사건). 단 `update_history`(해결 기록)는 **API 어디서도 호출 불가** — 해결 기록 2건 모두 코드 외부에서 직접 작성됨 |
| user_data_verification_gate | 충족 | **약한 충족** | 승인 6건 존재하나 5건이 11초 내 연타(요약·비고 공란) — 게이트는 있으나 AC-3의 "직접 확인" 증거력 얇음. 미리보기 모달은 승인 이후에야 추가됨 |
| change_loop_closed | 충족(승인) | **기록은 소급** | CR 5dd477의 생성→verified가 **30ms** — API 상태 전이를 밟지 않은 사후 백필. 실질 루프(장애→ESMIS 전환→재수집→샘플 승인)는 실제로 있었으나 기계가 만든 이력이 아님 |
| user_verified_pipeline | 충족(승인) | 충족 (문서 기준) | 승인 기록 존재. 단 export_sales는 데이터 1행도 실증된 적 없음(계약 검증만) |

**제약 준수**: 무료/USDA-only ✓, 외부 LLM 없음 ✓, USER-CONFIG 53곳 ✓, data/ gitignore ✓.
부분 위반 1건: `manifest.py`가 정적 `DATA_DIR` 상수로 DataBackend를 우회 (백엔드 전환 시 manifest만 로컬 잔류).

**게이트 8/8**: 감사자가 직접 재실행해 **정당성 확인** (시맨틱 검증 실재). 약점: check B가 소스 키 집합만 단언 — export_sales "never_run"이 조용히 통과.

## 3. 결함 연대기 (Stage 1~3 전체, 12건)

| # | 결함 | 발견 경로 | 근본 원인 |
|---|------|----------|----------|
| 1 | 큐레이션 v2 JSON 내보내기 무동작 | 사용자 | 샌드박스 제약 미대조, 자체 검수 생략 |
| 2 | as-is/to-be 이력 미기록 | 사용자 | 명시 제약 무시, 기존 추적 시스템 미활용 |
| 3 | WASDE 13분 블로킹 | 사용자 | 조기 탈출 없는 재시도 루프 |
| 4 | 추측성 폴백 URL 3종 전부 무효 | 사용자 지적 후 조사 | 공식 문서 미조사, 무검증 배포 |
| 5 | Cornell 301 페이지네이션 무력화 + 병합 NaT 전량 드롭 (critical 2) | 리뷰 에이전트 | "기본 호출만 검증" — 페이지네이션·병합 경로 미실행 |
| 6 | 소스 명칭 이중화 (상태 15개, 검증 조인 불일치) | 최종 확인 중 | 설계 시 단일 레지스트리 부재 |
| 7 | Run 버튼 조용한 no-op | 사용자 | #6의 증상 + HTTP 200 && error body 패턴 |
| 8 | 콘솔 unhandled rejection | 사용자 | 핸들러 catch 부재 |
| 9 | 좀비 서버가 구코드 응답 | 반영 확인 중 | SO_REUSEADDR 이중 바인딩, 재시작 후 미검증 |
| 10 | lock 정규식 버그 + 의존성 2종 미설치 + pyproject 상한 충돌 | 리뷰 에이전트 | `]` 파싱, 조용한 기능 비활성(imagehash) |
| 11 | 데이터 확인 UI 부재 (preview API 미사용) | 사용자 질문 | 기능을 "API 존재"로 완료 처리 |
| 12 | 감사 발견 4종: export_sales 침묵 실패 / harness.yaml 장식화 / 루프 기록 소급 / record_success no-op | 적대 감사 | 아래 패턴 분석 |

## 4. 메타 패턴 분석 — 12건을 관통하는 5개 패턴

1. **실행하지 않고 눈으로 확인** (#1,5,7,9,11): "코드가 있다/200이 온다"를 "동작한다"로 착각.
   → 대책 적용됨: `scripts/verify_pipeline.py` 시맨틱 게이트 + 배포 전 실행 의무화
2. **선언과 런타임의 괴리 (spec-code drift)** (#6,12-harness,12-skipped): 명세(YAML/문서)가 코드와
   따로 진화. 선언을 소비하는 코드가 없으면 반드시 벌어짐.
   → **잔존 리스크** — harness.yaml 배선 or 축소 필요 (백로그 R2)
3. **조용한 실패 (silent failure)** (#7,10,12-export,12-record_success): 오류를 삼키고 정상 신호 반환.
   가장 위험한 부류 — 감시가 불가능해짐.
   → **잔존 리스크** — export_sales skipped 상태 구현 필요 (백로그 R1)
4. **사후 기록 (record-after-the-fact)** (#2,12-루프): 시스템이 만든 이력이 아닌 손으로 쓴 이력은
   추적성 가치가 낮고, 기계 경로가 실사용 검증을 받지 못함.
   → **잔존 리스크** — update_history API 노출 + CR 루프를 실제 API로 완주 (백로그 R3)
5. **외부 의존 취약성** (#3,4): USDA 인프라 장애 2건이 파이프라인 설계 결함을 노출.
   → 대책 적용됨: 공식 아카이브 폴백, circuit breaker, crawl-delay, 증분 수집

## 5. 부검 중 즉시 조치 완료

- weekly 크론 3중 상충 동기화 (harness.yaml / harness_config.py 기본값 / run.py docstring → 전부 금요일)
- wwcb_images fitz 실패 이력 해결 마감 (미해결 0건)

## 6. 개선 백로그 (우선순위 — 사용자 판정 대상)

| # | 항목 | 이유 | 규모 |
|---|------|------|------|
| R1 | export_sales `skipped`/`no_data` 상태 구현 + 시도 manifest 기록 | 침묵 실패 제거, AC-2/4 충족 가능화, seed 기준의 'skipped' 이행 | 중 |
| R2 | harness.yaml 배선 (retry_policy·verification 임계값을 코드가 소비) 또는 정직한 축소 | spec-code drift 해소 | 중 |
| R3 | `update_history` API 엔드포인트 + admin 해결 기록 UI | 해결 이력을 시스템 경로로 | 소 |
| R4 | `record_success` 구현 (성공 시 실패 행 정리) | 비연속 실패의 stale 오판정, --retry-failed 재큐잉 버그 | 소 |
| R5 | 게이트 check B에 소스별 건강 단언 (최소: 데이터 보유 소스의 success 확인) | never_run 조용한 통과 방지 | 소 |
| R6 | manifest의 DataBackend 경유 | Phase 2 백엔드 전환 대비 | 소 |
| R7 | review 제출 시 sample_summary 자동 채움 (preview 요약 첨부) | 러버스탬프 승인의 증거력 보강 | 소 |

## 7. 판정

- **파이프라인 실체**: 건전. 데이터 실증(115,607 정규화 행 + PDF 75건 + 이미지 1,030개),
  게이트 시맨틱 검증 정당, 제약 준수.
- **Stage 3 "완결" 주장**: 감사 기준으로 exit ~4/6. 특히 (a) export_sales 침묵 실패,
  (b) harness.yaml 장식화, (c) 루프 기록 소급은 문서상 충족과 실제 사이의 갭.
- **권고**: R1~R3를 이행한 뒤 Stage 3 완결을 재확정하거나, 현재 완결을 유지하되 본 부검을
  공식 유보 조항(known caveats)으로 채택 — **판정은 사용자 게이트**.
