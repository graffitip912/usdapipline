"""USDA AMS Grain Transportation Report – xlsx download + normalize.

Downloads GTR dataset xlsx files, saves raw copies, and normalizes
selected tables into the unified long/tidy schema.

Sheet whitelist based on actual xlsx structure analysis (Jun 2026).
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import pandas as pd

from common import manifest
from common.http import download_file
from common.schema import clip_dates, validate_and_stamp
from common.storage import RAW_DIR, ensure_dirs, norm_path, sha256_file

log = logging.getLogger(__name__)

SOURCE = "USDA_AMS_GTR"

GTR_TABLES: dict[str, dict] = {
    "Table1": {
        "url": "https://www.ams.usda.gov/sites/default/files/media/GTRTable1.xlsx",
        "desc": "Grain transportation cost indicators",
    },
    "Table2AB": {
        "url": "https://www.ams.usda.gov/sites/default/files/media/GTRTable2A_B.xlsx",
        "desc": "Interior-export price spreads and futures",
    },
    "Table14": {
        "url": "https://www.ams.usda.gov/sites/default/files/media/GTRTable14.xlsx",
        "desc": "US export inspections cumulative",
    },
    "Table15": {
        "url": "https://www.ams.usda.gov/sites/default/files/media/GTRTable15.xlsx",
        "desc": "Corn top 5 importers",
    },
    "Table16": {
        "url": "https://www.ams.usda.gov/sites/default/files/media/GTRTable16.xlsx",
        "desc": "Soybean top 5 importers",
    },
    "Table17": {
        "url": "https://www.ams.usda.gov/sites/default/files/media/GTRTable17.xlsx",
        "desc": "Wheat top 10 importers",
    },
    "Table18": {
        "url": "https://www.ams.usda.gov/sites/default/files/media/GTRTable18_Figure17_Figure18.xlsx",
        "desc": "Port area export inspections",
    },
}

_COMMODITY_NORM = {
    "CORN": "CORN",
    "SOYBEANS": "SOYBEAN",
    "SOYBEAN": "SOYBEAN",
    "WHEAT": "WHEAT",
    "SORGHUM": "ALL_GRAINS",
    "BARLEY": "ALL_GRAINS",
    "OATS": "ALL_GRAINS",
    "RYE": "ALL_GRAINS",
    "FLAXSEED": "ALL_GRAINS",
    "SUNFLOWER": "ALL_GRAINS",
    "MIXED": "ALL_GRAINS",
}

_SCHEMA_COLS = [
    "obs_date", "marketing_year", "commodity", "region",
    "metric", "value", "unit", "source", "report_date",
]


def _raw_dir() -> Path:
    return RAW_DIR / "gtr"


def collect(since: int = 2010, force: bool = False) -> None:
    ensure_dirs()
    log.info("GTR: downloading %d table files", len(GTR_TABLES))

    all_records: list[pd.DataFrame] = []

    for table_name, info in GTR_TABLES.items():
        try:
            df = _download_and_parse(table_name, info, since, force)
            if df is not None and not df.empty:
                all_records.append(df)
        except Exception:
            log.exception("GTR: failed to process %s", table_name)

    if all_records:
        merged = pd.concat(all_records, ignore_index=True)
        # 증분 쓰기 4원칙 (2026-07-11 사고: since=당해연도 주간 배치가 병합 없이
        # 교체해 16,277→5,032행 축소 — quickstats/usdm과 동일 원칙 적용)
        out = norm_path("gtr.parquet")
        if out.exists():
            try:
                existing = pd.read_parquet(out)
                if not existing.empty:
                    merged = pd.concat([existing, merged], ignore_index=True)
                    if "ingested_at" in merged.columns:
                        merged["ingested_at"] = merged["ingested_at"].fillna(
                            pd.Timestamp.now(tz="UTC"))
            except Exception:
                log.error("GTR: 기존 parquet 읽기 실패 — 쓰기 중단 (유실 방지)")
                return
        merged = merged.sort_values("report_date", kind="stable").drop_duplicates(
            subset=["commodity", "obs_date", "metric", "region"], keep="last")
        merged = validate_and_stamp(merged, SOURCE)
        tmp = out.with_suffix(".parquet.tmp")
        merged.to_parquet(tmp, index=False, compression="zstd")
        os.replace(tmp, out)
        manifest.upsert(
            source=SOURCE,
            artifact_type="normalized_parquet",
            period=f"{since}-present",
            path=out,
            sha256=sha256_file(out),
        )
        log.info("GTR: wrote %d normalized records to %s", len(merged), out)
    else:
        log.warning("GTR: no records normalized")


def _download_and_parse(
    table_name: str, info: dict, since: int, force: bool
) -> pd.DataFrame | None:
    url = info["url"]
    filename = f"{table_name}.xlsx"
    dest = _raw_dir() / filename

    download_file(url, dest)
    file_hash = sha256_file(dest)

    if not force and manifest.has_unchanged(SOURCE, file_hash):
        log.info("GTR: %s unchanged, skipping", table_name)
        return None

    manifest.upsert(
        source=SOURCE,
        artifact_type="raw_xlsx",
        period="rolling",
        path=dest,
        sha256=file_hash,
    )
    log.info("GTR: saved raw %s (%s)", table_name, dest)

    parser = _TABLE_PARSERS.get(table_name)
    if parser is None:
        log.info("GTR: no parser for %s, raw only", table_name)
        return None

    return parser(dest, since)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(
        s.astype(str).str.replace(",", "").str.strip(),
        errors="coerce",
    )


def _find_header_row(df_raw: pd.DataFrame, markers: list[str]) -> int:
    markers_lower = [m.lower() for m in markers]
    for idx, row in df_raw.iterrows():
        vals = " ".join(str(v).lower() for v in row.values if pd.notna(v))
        if any(m in vals for m in markers_lower):
            return idx
    return 0


# ---------------------------------------------------------------------------
# Table 1 – transport cost indicators. Sheet: "Data"
# Header row ~6: Date | Price | Rail | River | Gulf | PNW | ...
# ---------------------------------------------------------------------------

def _parse_table1(path: Path, since: int) -> pd.DataFrame:
    try:
        df_raw = pd.read_excel(path, sheet_name="Data", header=None)
    except Exception:
        log.warning("GTR Table1: 'Data' sheet not found")
        return pd.DataFrame()

    hdr = _find_header_row(df_raw, ["date", "price", "rail"])
    df = pd.read_excel(path, sheet_name="Data", header=hdr)
    df.columns = [str(c).strip() for c in df.columns]

    date_col = next((c for c in df.columns if "date" in c.lower()), None)
    if date_col is None:
        return pd.DataFrame()

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = clip_dates(df, date_col)
    df = df.dropna(subset=[date_col])
    if since:
        df = df[df[date_col].dt.year >= since]

    value_cols = [
        c for c in df.columns
        if c != date_col and not c.startswith("Unnamed")
    ]
    for vc in value_cols:
        df[vc] = _clean_numeric(df[vc])

    melted = df.melt(
        id_vars=[date_col], value_vars=value_cols,
        var_name="metric_raw", value_name="value",
    )
    melted = melted.dropna(subset=["value"])
    melted["metric"] = "transport_cost__" + melted["metric_raw"].str.lower().str.replace(r"[^a-z0-9]", "_", regex=True)
    melted["obs_date"] = melted[date_col]
    melted["commodity"] = "ALL_GRAINS"
    melted["region"] = "US"
    melted["unit"] = "index"
    melted["report_date"] = melted["obs_date"]
    melted["marketing_year"] = None
    melted["source"] = SOURCE
    return melted[_SCHEMA_COLS]


# ---------------------------------------------------------------------------
# Table 2AB – price spreads. Sheet: "Data"
# Col A = date (sparse, forward-fill), Col B = commodity, Col C = route,
# Cols D+ = prices (Origin, Destination, Spread, [6 blank],
#           Origin-Future basis, Dest-Future basis, ...)
# Sheet: "Futures" — CBOT/KC/MPLS 근월물 주간 종가 + 계약월 (2026-07-13 추가)
# ---------------------------------------------------------------------------

# 계약월명 → 월 번호 (GTR 표기 실측: "July", "Sep", "Dec" 등)
_CONTRACT_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _contract_yyyymm(month_name, obs_date) -> float | None:
    """계약월명 + 관측일 → YYYYMM (float — GrainSchema value 채널에 적재).

    연도 추론(결정론): 계약월 번호 >= 관측 월이면 당해, 아니면 익년.
    (근월물은 항상 관측일 이후 최초 도래 월 — CME 3·5·7·9·12월 주기)
    """
    if not isinstance(month_name, str):
        return None
    m = _CONTRACT_MONTHS.get(month_name.strip().lower())
    if m is None:
        return None
    year = obs_date.year if m >= obs_date.month else obs_date.year + 1
    return float(year * 100 + m)


def _parse_table2ab_futures(path: Path, since: int) -> pd.DataFrame:
    """Futures 시트: 근월물 주간 종가 + 계약월.

    거래소-클래스 짝은 파일 자체 베이시스 컬럼 역산으로 확정 (2026-07-13):
    HRW 터미널(KS/Gulf)→KC, HRS 터미널(ND/Portland)→MPLS, 옥수수/대두→CBOT.
    계약월은 GTR 발표 표기를 그대로 수집 (재해석 금지).
    """
    try:
        df = pd.read_excel(path, sheet_name="Futures", header=None, skiprows=3)
    except Exception as exc:
        # 모든 읽기 실패를 'not found'로 오표하지 않음 — 원인 보존 (리뷰 수리)
        log.warning("GTR Table2AB Futures 시트 읽기 실패 (%s): %s",
                    type(exc).__name__, exc)
        return pd.DataFrame()
    if df.shape[1] < 10:
        # 컬럼 구조 개편 신호 — 조용한 빈 DF 금지 (freshness 게이트가 14일 후
        # STALE로 잡긴 하나, 원인은 여기 로그가 말해줘야 함)
        log.warning("GTR Table2AB Futures: 컬럼 %d개(<10) — 시트 구조 변경 의심, 파싱 스킵",
                    df.shape[1])
        return pd.DataFrame()

    df[0] = pd.to_datetime(df[0], errors="coerce")
    df = df.dropna(subset=[0])
    df = clip_dates(df, 0)
    if since:
        df = df[df[0].dt.year >= since]

    # (가격 컬럼, 계약월 컬럼, commodity, region) — 헤더 행 실측 기준
    specs = [
        (6, 9, "CORN", "CBOT"),
        (7, 8, "SOYBEAN", "CBOT"),
        (2, 1, "WHEAT", "KC-HRW"),
        (3, 1, "WHEAT", "MPLS-HRS"),
        # SRW는 참조 전용·판정 미사용 — m7 엔진의 밀 판정 짝은 KC-HRW/MPLS-HRS만
        # (SRW는 다른 기초자산이라 대체 금지, engine.py 상단 블록 참조)
        (5, 1, "WHEAT", "CBOT-SRW"),
    ]
    records = []
    for _, row in df.iterrows():
        obs = row[0]
        for price_col, month_col, commodity, region in specs:
            price = pd.to_numeric(row.get(price_col), errors="coerce")
            if pd.isna(price):
                continue
            base = {
                "obs_date": obs, "marketing_year": None,
                "commodity": commodity, "region": region,
                "source": SOURCE, "report_date": obs,
            }
            records.append({**base, "metric": "futures__nearby_price",
                            "value": float(price), "unit": "$/bu"})
            yyyymm = _contract_yyyymm(row.get(month_col), obs)
            if yyyymm is not None:
                records.append({**base, "metric": "futures__nearby_contract",
                                "value": yyyymm, "unit": "yyyymm"})
    return pd.DataFrame(records)


def _parse_table2ab(path: Path, since: int) -> pd.DataFrame:
    try:
        df = pd.read_excel(path, sheet_name="Data", header=None, skiprows=2)
    except Exception:
        log.warning("GTR Table2AB: 'Data' sheet not found")
        return pd.DataFrame()

    if df.shape[1] < 5:
        return pd.DataFrame()

    df[0] = pd.to_datetime(df[0], errors="coerce")
    df[0] = df[0].ffill()
    df = clip_dates(df, 0)
    df = df.dropna(subset=[0])
    if since:
        df = df[df[0].dt.year >= since]

    commodity_map = {
        "corn": "CORN", "soybean": "SOYBEAN", "soybeans": "SOYBEAN",
        "hrw": "WHEAT", "hrs": "WHEAT", "srw": "WHEAT",
        "hrsw": "WHEAT", "durum": "WHEAT",
    }
    df["commodity"] = (
        df[1].astype(str).str.lower().str.strip()
        .map(commodity_map).fillna("ALL_GRAINS")
    )
    df["region"] = df[2].astype(str).str.strip()

    # 7/8 = GTR 자체 계산 산지/도착지-근월물 베이시스 (2026-07-13 추가).
    # 7(산지)은 전 노선, 8(도착지)은 corn/soybean만 M1 게이트가 재계산과
    # 전수 대조. 밀 도착지 베이시스는 선물 짝이 원천 미확정(KC·시카고 모두
    # 불일치 실측) — 문서 전용·판정 미사용
    price_metrics = {3: "origin_price", 4: "destination_price",
                     5: "price_spread", 7: "origin_future_basis",
                     8: "dest_future_basis"}
    records = []
    for col_idx, metric_name in price_metrics.items():
        if col_idx >= df.shape[1]:
            continue
        df[col_idx] = _clean_numeric(df[col_idx])
        sub = df[[0, "commodity", "region", col_idx]].dropna(subset=[col_idx])
        if sub.empty:
            continue
        records.append(pd.DataFrame({
            "obs_date": sub[0],
            "marketing_year": None,
            "commodity": sub["commodity"],
            "region": sub["region"],
            "metric": f"price_spread__{metric_name}",
            "value": sub[col_idx],
            "unit": "$/bu",
            "source": SOURCE,
            "report_date": sub[0],
        }))

    data_df = pd.concat(records, ignore_index=True) if records else pd.DataFrame()
    fut_df = _parse_table2ab_futures(path, since)
    parts = [d for d in (data_df, fut_df) if not d.empty]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# ---------------------------------------------------------------------------
# Table 14 – export inspections. Sheet: "copy data"
# Header row 1: Date | HRW-Outstd | Accum | SRW-Outstd | ... | CORN-Outstd | SOYBEAN-Outstd
# ---------------------------------------------------------------------------

def _parse_table14(path: Path, since: int) -> pd.DataFrame:
    try:
        df = pd.read_excel(path, sheet_name="copy data", header=1)
    except Exception:
        log.warning("GTR Table14: 'copy data' sheet not found")
        return pd.DataFrame()

    df.columns = [str(c).strip() for c in df.columns]
    if "Date" not in df.columns:
        return pd.DataFrame()

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = clip_dates(df, "Date")
    df = df.dropna(subset=["Date"])
    if since:
        df = df[df["Date"].dt.year >= since]

    commodity_cols = {
        "WHEAT": [c for c in df.columns if any(
            w in c.upper() for w in ("HRW", "SRW", "HRS", "SWW", "DUR", "ALL-")
        ) and c != "Date"],
        "CORN": [c for c in df.columns if "CORN" in c.upper()],
        "SOYBEAN": [c for c in df.columns if "SOYBEAN" in c.upper()],
    }

    records = []
    for commodity, cols in commodity_cols.items():
        for col in cols:
            df[col] = _clean_numeric(df[col])
            sub = df[["Date", col]].dropna(subset=[col])
            if sub.empty:
                continue
            metric_slug = re.sub(r"[^a-z0-9]", "_", col.lower()).strip("_")
            records.append(pd.DataFrame({
                "obs_date": sub["Date"],
                "marketing_year": None,
                "commodity": commodity,
                "region": "US",
                "metric": f"export_inspection__{metric_slug}",
                "value": sub[col],
                "unit": "1000mt",
                "source": SOURCE,
                "report_date": sub["Date"],
            }))

    return pd.concat(records, ignore_index=True) if records else pd.DataFrame()


# ---------------------------------------------------------------------------
# Tables 15-17 – export commitments by country
# "Weekly"/"Sheet1": header row 1 = Country Code | Country Name | Period Ending Date | ...
# "Redesign": header rows 0-3, data row 4+ = Date | Country | YTD current | YTD prev | %chg
# ---------------------------------------------------------------------------

def _parse_weekly_exports(
    path: Path, since: int, commodity: str, sheet_name: str,
) -> pd.DataFrame:
    try:
        df = pd.read_excel(path, sheet_name=sheet_name, header=1)
    except Exception:
        log.debug("GTR: sheet '%s' not found in %s", sheet_name, path.name)
        return pd.DataFrame()

    # Do NOT strip column names — duplicates like "Outstanding Sales" /
    # " Outstanding Sales" would collide and df[col] returns a DataFrame.
    df.columns = [str(c) for c in df.columns]

    date_col = next(
        (c for c in df.columns if "Period Ending Date" in c), None
    )
    if date_col is None:
        return pd.DataFrame()

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col])
    df = clip_dates(df, date_col)
    if since:
        df = df[df[date_col].dt.year >= since]

    country_col = next(
        (c for c in df.columns if "Country Name" in c), None
    )
    my_col = next(
        (c for c in df.columns if "Marketing Year" in c), None
    )

    target_metrics = [
        "Net Sales", "Outstanding Sales", "Weekly Exports",
        "Accumulated Exports", "Total Commitment",
    ]

    used_cols: set[str] = set()
    records = []
    for metric_name in target_metrics:
        actual_col = None
        for c in df.columns:
            if c in used_cols:
                continue
            if c.strip() == metric_name:
                actual_col = c
                break
        if actual_col is None:
            for c in df.columns:
                if c in used_cols:
                    continue
                if metric_name.lower() in c.strip().lower() and not c.strip().endswith(".1"):
                    actual_col = c
                    break
        if actual_col is None:
            continue
        used_cols.add(actual_col)

        vals = _clean_numeric(df[actual_col])
        sub = df.loc[vals.notna()].copy()
        sub["_val"] = vals.loc[vals.notna()]
        if sub.empty:
            continue

        metric_slug = re.sub(r"[^a-z0-9]", "_", metric_name.lower()).strip("_")
        row_df = pd.DataFrame({
            "obs_date": sub[date_col].values,
            "marketing_year": (
                sub[my_col].astype(str).values if my_col and my_col in sub.columns else None
            ),
            "commodity": commodity,
            "region": (
                sub[country_col].astype(str).str.strip().values
                if country_col and country_col in sub.columns else "US"
            ),
            "metric": f"export_commitment__{metric_slug}",
            "value": sub["_val"].values,
            "unit": "1000mt",
            "source": SOURCE,
            "report_date": sub[date_col].values,
        })
        records.append(row_df)

    return pd.concat(records, ignore_index=True) if records else pd.DataFrame()


def _parse_redesign_summary(
    path: Path, since: int, commodity: str, sheet_candidates: list[str],
) -> pd.DataFrame:
    df = None
    for name in sheet_candidates:
        try:
            df = pd.read_excel(path, sheet_name=name, header=None)
            break
        except Exception:
            continue
    if df is None or len(df) < 5:
        return pd.DataFrame()

    data = df.iloc[4:].copy()
    data.columns = range(len(data.columns))

    if data.shape[1] < 4:
        return pd.DataFrame()

    data[0] = pd.to_datetime(data[0], errors="coerce")
    data = data.dropna(subset=[0])
    data = clip_dates(data, 0)
    if since:
        data = data[data[0].dt.year >= since]

    col_metrics = {2: "ytd_current_my", 3: "ytd_prev_my"}
    records = []
    for col_idx, metric_name in col_metrics.items():
        if col_idx >= data.shape[1]:
            continue
        data[col_idx] = _clean_numeric(data[col_idx])
        sub = data[[0, 1, col_idx]].dropna(subset=[col_idx])
        if sub.empty:
            continue
        records.append(pd.DataFrame({
            "obs_date": sub[0].values,
            "marketing_year": None,
            "commodity": commodity,
            "region": sub[1].astype(str).str.strip().values,
            "metric": f"top_importer__{metric_name}",
            "value": sub[col_idx].values,
            "unit": "1000mt",
            "source": SOURCE,
            "report_date": sub[0].values,
        }))

    return pd.concat(records, ignore_index=True) if records else pd.DataFrame()


def _parse_table15(path: Path, since: int) -> pd.DataFrame:
    frames = []
    r = _parse_redesign_summary(path, since, "CORN", ["GTR Corn Table Redesign"])
    if not r.empty:
        frames.append(r)
    w = _parse_weekly_exports(path, since, "CORN", "Weekly")
    if not w.empty:
        frames.append(w)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _parse_table16(path: Path, since: int) -> pd.DataFrame:
    frames = []
    r = _parse_redesign_summary(
        path, since, "SOYBEAN",
        ["GTR Soybean Table Redesign ", "GTR Soybean Table Redesign"],
    )
    if not r.empty:
        frames.append(r)
    w = _parse_weekly_exports(path, since, "SOYBEAN", "Weekly")
    if not w.empty:
        frames.append(w)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _parse_table17(path: Path, since: int) -> pd.DataFrame:
    frames = []
    r = _parse_redesign_summary(path, since, "WHEAT", ["GTR Wheat Table Redesign"])
    if not r.empty:
        frames.append(r)
    w = _parse_weekly_exports(path, since, "WHEAT", "Sheet1")
    if not w.empty:
        frames.append(w)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ---------------------------------------------------------------------------
# Table 18 – port inspections. Sheet: "New Table" (already long format)
# Columns: Week Ending | Date | Grain | TED_Reg | MT
# ---------------------------------------------------------------------------

def _parse_table18(path: Path, since: int) -> pd.DataFrame:
    try:
        df = pd.read_excel(path, sheet_name="New Table", header=0)
    except Exception:
        log.warning("GTR Table18: 'New Table' sheet not found")
        return pd.DataFrame()

    df.columns = [str(c).strip() for c in df.columns]
    if "Week Ending" not in df.columns or "MT" not in df.columns:
        return pd.DataFrame()

    df["Week Ending"] = pd.to_datetime(df["Week Ending"], errors="coerce")
    df = clip_dates(df, "Week Ending")
    df = df.dropna(subset=["Week Ending", "MT", "Grain"])
    if since:
        df = df[df["Week Ending"].dt.year >= since]

    df["MT"] = _clean_numeric(df["MT"])
    df = df.dropna(subset=["MT"])
    df["commodity"] = (
        df["Grain"].astype(str).str.upper().str.strip()
        .map(_COMMODITY_NORM).fillna("ALL_GRAINS")
    )

    return pd.DataFrame({
        "obs_date": df["Week Ending"].values,
        "marketing_year": None,
        "commodity": df["commodity"].values,
        "region": df["TED_Reg"].astype(str).str.strip().values,
        "metric": "port_inspection__mt",
        "value": df["MT"].values,
        "unit": "mt",
        "source": SOURCE,
        "report_date": df["Week Ending"].values,
    })


_TABLE_PARSERS = {
    "Table1": _parse_table1,
    "Table2AB": _parse_table2ab,
    "Table14": _parse_table14,
    "Table15": _parse_table15,
    "Table16": _parse_table16,
    "Table17": _parse_table17,
    "Table18": _parse_table18,
}
