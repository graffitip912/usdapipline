"""End-to-end semantic verification of the pipeline's user-facing surface.

Why this exists (2026-07-03): the admin Run button was silently broken for
weeks — the UI sent manifest source names, the API returned HTTP 200 with
{"status": "error"}, and every "verification" that only checked status codes
passed. Rule: HTTP 200 is NOT success; every check here asserts SEMANTIC
success (response contents + observable state change), and every UI-invoked
API path is exercised with the exact parameters the UI sends.

Run: python scripts/verify_pipeline.py          (API on :8000 required,
                                                 dashboard on :3000 optional)
Exit code 0 = all pass, 1 = any failure.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows cp949 콘솔에서도 한글/대시 출력이 깨지지 않도록
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API = "http://localhost:8000"
DASH = "http://localhost:3000"
ROOT = Path(__file__).resolve().parent.parent

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# A. UI -> API contract: every path called in dashboard/src/lib/api.ts must
#    exist in the FastAPI route table (catches route renames/mismatches).
# ---------------------------------------------------------------------------

def check_ui_api_contract() -> None:
    print("\n[A] UI->API 계약 (api.ts 호출 경로 vs FastAPI 라우트)")
    api_ts = (ROOT / "dashboard/src/lib/api.ts").read_text(encoding="utf-8")
    raw = re.findall(r"fetchApi(?:<[^>]*>)?\(\s*[`\"'](/api/[^`\"']+)", api_ts)

    openapi = requests.get(f"{API}/openapi.json", timeout=15).json()
    routes = list(openapi["paths"].keys())

    def matches(ui: str) -> bool:
        # `${...}` 이후는 파라미터/쿼리 템플릿(중첩 리터럴 포함)이므로
        # 고정 접두부 + 와일드카드로 라우트와 대조
        prefix = ui.split("${")[0].split("?")[0]
        pattern = "^" + re.escape(prefix) + (".*" if prefix != ui else "$")
        for route in routes:
            if re.match(pattern, route):
                return True
        return False

    ui_paths = sorted(set(raw))
    missing = [p for p in ui_paths if not matches(p)]
    check("api.ts 모든 경로가 API 라우트에 존재", not missing,
          f"{len(ui_paths)}개 확인" + (f", 누락: {missing}" if missing else ""))


# ---------------------------------------------------------------------------
# B. Collector status: exactly the 9 canonical run keys, no duplicates.
# ---------------------------------------------------------------------------

def check_collector_status() -> list[dict]:
    print("\n[B] 수집기 상태 (canonical 9개)")
    from collector.run import SOURCES

    rows = requests.get(f"{API}/api/collector/status", timeout=15).json()
    got = [r["source"] for r in rows]
    check("소스 목록 == 실행 키 9개 (중복/이물 없음)",
          sorted(got) == sorted(SOURCES.keys()), f"got={sorted(got)}")
    return rows


# ---------------------------------------------------------------------------
# C. Run button semantics: POST run -> status=="started" -> manifest
#    last_attempt actually changes (observable state change).
# ---------------------------------------------------------------------------

def _observe_change(src: str, before: str | None, max_wait: int) -> bool:
    for _ in range(max_wait // 5):
        time.sleep(5)
        after = {r["source"]: r["last_attempt"]
                 for r in requests.get(f"{API}/api/collector/status", timeout=15).json()}
        if after.get(src) != before:
            return True
    return False


def check_run_button() -> None:
    print("\n[C] Run 버튼 시맨틱 (요청 수락 + 상태 변화 관찰)")
    src = "quickstats"  # USER-CONFIG: fastest collector for the e2e run test

    snapshot = {r["source"]: r["last_attempt"]
                for r in requests.get(f"{API}/api/collector/status", timeout=15).json()}
    before = snapshot.get(src)

    # 1단계: UI와 동일한 호출 (데이터 미변경 시 수집기가 정상적으로 skip할 수 있음)
    resp = requests.post(f"{API}/api/collector/run/{src}", timeout=15).json()
    check(f"POST run/{src} -> status=='started'", resp.get("status") == "started",
          str(resp))

    changed = _observe_change(src, before, max_wait=30)
    if not changed:
        # 2단계: skip 경로였다면 force로 전체 체인(수집→manifest 기록)을 실증
        requests.post(f"{API}/api/collector/run/{src}?force=true", timeout=15)
        # USER-CONFIG: 외부 API(NASS) 지연을 감안한 관찰 한도
        changed = _observe_change(src, before, max_wait=150)
        detail = "force 실행으로 확인 (1단계는 캐시 skip)"
    else:
        detail = "1단계에서 즉시 확인"
    check(f"{src} 수집 체인 상태 변화 관찰", changed, detail)

    # semantic error contract: unknown source must be reported as error
    bad = requests.post(f"{API}/api/collector/run/USDA_WASDE", timeout=15).json()
    check("잘못된 소스명 -> status=='error' 반환", bad.get("status") == "error", str(bad))


# ---------------------------------------------------------------------------
# D. Verification chain the admin UI uses: preview -> (review contract).
# ---------------------------------------------------------------------------

def check_verification_chain(status_rows: list[dict]) -> None:
    print("\n[D] 검증 체인 (preview가 UI의 소스 키로 동작)")
    ok_sources, no_data = [], []
    for row in status_rows:
        src = row["source"]
        r = requests.get(f"{API}/api/verification/preview/{src}", timeout=60)
        if r.status_code == 200 and r.json().get("row_count", 0) > 0:
            ok_sources.append(src)
        else:
            no_data.append(src)
    # 구조화 데이터가 있어야 하는 소스들은 preview가 반드시 동작해야 함
    required = {"gtr", "quickstats", "wasde", "psd", "ers_feedgrains"}
    missing = required - set(ok_sources)
    check("구조화 5개 소스 preview 데이터 존재", not missing,
          f"ok={ok_sources}, 데이터 없음(원시 수집기/외부장애 포함)={no_data}")


# ---------------------------------------------------------------------------
# E. Schedule pause/resume round-trip (reversible mutation).
# ---------------------------------------------------------------------------

def check_schedule_roundtrip() -> None:
    print("\n[E] 스케줄 pause/resume 왕복")
    requests.post(f"{API}/api/schedule/pause", timeout=15)
    paused = all(s["paused"] for s in requests.get(f"{API}/api/schedule", timeout=15).json())
    requests.post(f"{API}/api/schedule/resume", timeout=15)
    resumed = all(not s["paused"] for s in requests.get(f"{API}/api/schedule", timeout=15).json())
    check("pause -> 전체 paused / resume -> 전체 active", paused and resumed)


# ---------------------------------------------------------------------------
# F. Dashboard pages reachable (client-rendered; smoke only).
# ---------------------------------------------------------------------------

def check_dashboard() -> None:
    print("\n[F] 대시보드 페이지 (smoke)")
    try:
        codes = {p: requests.get(f"{DASH}{p}", timeout=30).status_code
                 for p in ["/", "/grain", "/images", "/admin"]}
        check("4개 페이지 200", all(c == 200 for c in codes.values()), str(codes))
    except requests.ConnectionError:
        check("대시보드 접근", False, ":3000 미기동 — npm run dev 후 재실행")


def main() -> int:
    print("=" * 60)
    print("파이프라인 시맨틱 검증 (HTTP 200 != 성공)")
    print("=" * 60)
    try:
        requests.get(f"{API}/api/health", timeout=10)
    except requests.ConnectionError:
        print("API 서버(:8000)가 실행 중이어야 합니다: python -m uvicorn api.main:app")
        return 1

    check_ui_api_contract()
    rows = check_collector_status()
    check_run_button()
    check_verification_chain(rows)
    check_schedule_roundtrip()
    check_dashboard()

    failed = [r for r in RESULTS if not r[1]]
    print("\n" + "=" * 60)
    print(f"결과: {len(RESULTS) - len(failed)}/{len(RESULTS)} 통과")
    for name, _, detail in failed:
        print(f"  FAIL: {name} {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
