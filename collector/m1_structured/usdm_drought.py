"""USDM 가뭄 통계 수집 — 주(state)별 D0~D4 면적 % (지도분석 v2 가뭄도).

as-is: 가뭄 수치 데이터 없음 (WWCB 지도 이미지뿐 — 색 영역이라 수치 추출 불가)
to-be: USDM 공식 API에서 주별·주간 가뭄 심각도 면적 % 수집 (2000~ 이력 제공)
       → drought__d0plus/d2plus_area_pct. 향후 가뭄 이미지 색 면적 추출의 골든셋.

API: usdmdataservices.unl.edu — aoi는 주 FIPS 숫자 코드(실측: 약어는 빈 응답).
statisticsType=1(누적): d0 = D0 이상 면적 %, d2 = D2 이상(심각+) 면적 %.
증분 4원칙 준수: 병합 보존 + 스탬프 + 안정 정렬·전체 키 dedup + 원자적 교체.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

import pandas as pd

from common import manifest
from common.http import get_session
from common.schema import validate_and_stamp
from common.storage import ensure_dirs, norm_path, sha256_file

log = logging.getLogger(__name__)

SOURCE = "USDM_DROUGHT"
API = ("https://usdmdataservices.unl.edu/api/StateStatistics/"
       "GetDroughtSeverityStatisticsByAreaPercent")

# 본토 48주 FIPS 코드 (USDM aoi 파라미터)
STATE_FIPS = {
    "AL": 1, "AZ": 4, "AR": 5, "CA": 6, "CO": 8, "CT": 9, "DE": 10, "FL": 12,
    "GA": 13, "ID": 16, "IL": 17, "IN": 18, "IA": 19, "KS": 20, "KY": 21,
    "LA": 22, "ME": 23, "MD": 24, "MA": 25, "MI": 26, "MN": 27, "MS": 28,
    "MO": 29, "MT": 30, "NE": 31, "NV": 32, "NH": 33, "NJ": 34, "NM": 35,
    "NY": 36, "NC": 37, "ND": 38, "OH": 39, "OK": 40, "OR": 41, "PA": 42,
    "RI": 44, "SC": 45, "SD": 46, "TN": 47, "TX": 48, "UT": 49, "VT": 50,
    "VA": 51, "WA": 53, "WV": 54, "WI": 55, "WY": 56,
}

# USER-CONFIG: 수집 지표 — (metric 이름, USDM 응답 키)
METRICS = [
    ("drought__d0plus_area_pct", "d0"),   # 이상 건조 이상 면적 %
    ("drought__d2plus_area_pct", "d2"),   # 심각 가뭄 이상 면적 %
]


def collect(since: int = 2010, force: bool = False) -> None:
    ensure_dirs()
    norm_file = norm_path("usdm_drought.parquet")
    end = datetime.utcnow().strftime("%m/%d/%Y")
    start = f"1/1/{since}"

    records: list[dict] = []
    failed: list[str] = []
    for st, fips in STATE_FIPS.items():
        try:
            # Accept 헤더 없으면 XML 반환 (실측) — JSON 명시 필수
            resp = get_session().get(
                API,
                params={"aoi": str(fips), "startdate": start, "enddate": end,
                        "statisticsType": "1"},
                headers={"Accept": "application/json"},
                timeout=120,
            )
            resp.raise_for_status()
            rows = resp.json()
        except Exception:
            log.exception("USDM: %s(%d) 조회 실패", st, fips)
            failed.append(st)
            continue
        for r in rows:
            obs = r["mapDate"][:10]
            for metric, key in METRICS:
                records.append({
                    "obs_date": datetime.strptime(obs, "%Y-%m-%d"),
                    "marketing_year": None,
                    "commodity": "DROUGHT",
                    "region": r["stateAbbreviation"],
                    "metric": metric,
                    "value": float(r[key]),
                    "unit": "PCT AREA",
                    "source": SOURCE,
                    "report_date": datetime.strptime(obs, "%Y-%m-%d"),
                })
        log.info("USDM: %s -> %d rows", st, len(rows))

    if not records:
        raise RuntimeError("USDM: 수집 0건 — API 장애 의심")

    merged = pd.DataFrame(records)
    if norm_file.exists():
        try:
            existing = pd.read_parquet(norm_file)
            if not existing.empty:
                merged = pd.concat([existing, merged], ignore_index=True)
                if "ingested_at" in merged.columns:
                    merged["ingested_at"] = merged["ingested_at"].fillna(
                        pd.Timestamp.now(tz="UTC"))
        except Exception:
            log.error("USDM: 기존 parquet 읽기 실패 — 쓰기 중단 (유실 방지)")
            return
    merged = merged.sort_values("report_date", kind="stable").drop_duplicates(
        subset=["commodity", "obs_date", "metric", "region"], keep="last")
    merged = validate_and_stamp(merged, SOURCE)
    tmp = norm_file.with_suffix(".parquet.tmp")
    merged.to_parquet(tmp, index=False, compression="zstd")
    os.replace(tmp, norm_file)
    manifest.upsert(source=SOURCE, artifact_type="normalized_parquet",
                    period=f"{since}-present", path=norm_file,
                    sha256=sha256_file(norm_file))
    log.info("USDM: wrote %d rows to %s", len(merged), norm_file)

    if failed:
        raise RuntimeError(f"USDM 부분 실패: {', '.join(failed)} (성공분은 저장됨)")
