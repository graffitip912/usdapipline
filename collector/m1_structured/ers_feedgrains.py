"""USDA ERS Feed Grains Database – Yearbook Tables (all years CSV).

Monthly-updated single CSV covering corn, grain sorghum, barley, and oats.
Pipeline filters primarily for corn.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from common import manifest
from common.http import download_file
from common.schema import validate_and_stamp
from common.storage import RAW_DIR, ensure_dirs, norm_path, sha256_file

log = logging.getLogger(__name__)

SOURCE = "USDA_ERS_FEEDGRAINS"

CSV_URL = "https://www.ers.usda.gov/media/5766/feed-grains-yearbook-tables-all-years.csv"

COMMODITY_FILTER = {"CORN", "GRAIN SORGHUM", "BARLEY", "OATS"}
COMMODITY_NORM = {
    "CORN": "CORN",
    "GRAIN SORGHUM": "ALL_GRAINS",
    "BARLEY": "ALL_GRAINS",
    "OATS": "ALL_GRAINS",
}


def _raw_dir() -> Path:
    return RAW_DIR / "ers_feedgrains"


def collect(since: int = 2010, force: bool = False) -> None:
    ensure_dirs()
    raw_dir = _raw_dir()
    raw_dir.mkdir(parents=True, exist_ok=True)

    dest = raw_dir / "feed-grains-yearbook-all-years.csv"
    log.info("ERS Feed Grains: downloading CSV")
    download_file(CSV_URL, dest)
    file_hash = sha256_file(dest)

    if not force and manifest.has_unchanged(SOURCE, file_hash):
        log.info("ERS Feed Grains: CSV unchanged, skipping normalization")
        return

    manifest.upsert(
        source=SOURCE,
        artifact_type="raw_csv",
        period=f"{since}-present",
        path=dest,
        sha256=file_hash,
    )
    log.info("ERS Feed Grains: saved raw CSV -> %s", dest)

    df_raw = _read_csv(dest)
    if df_raw is None or df_raw.empty:
        log.warning("ERS Feed Grains: CSV empty after reading")
        return

    df_norm = _normalize(df_raw, since)
    if df_norm.empty:
        log.warning("ERS Feed Grains: no records after normalization")
        return

    df_norm = validate_and_stamp(df_norm, SOURCE)
    out = norm_path("ers_feedgrains.parquet")
    df_norm.to_parquet(out, index=False, compression="zstd")
    manifest.upsert(
        source=SOURCE,
        artifact_type="normalized_parquet",
        period=f"{since}-present",
        path=out,
        sha256=sha256_file(out),
    )
    log.info("ERS Feed Grains: wrote %d normalized records -> %s", len(df_norm), out)


def _read_csv(path: Path) -> pd.DataFrame | None:
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            df = pd.read_csv(path, encoding=encoding, low_memory=False)
            if len(df.columns) >= 3:
                log.debug("ERS Feed Grains: CSV parsed with encoding=%s (%d cols)", encoding, len(df.columns))
                return df
        except (UnicodeDecodeError, pd.errors.ParserError, ValueError) as exc:
            log.debug("ERS Feed Grains: encoding %s failed for %s: %s", encoding, path.name, exc)
            continue
    log.error("ERS Feed Grains: unable to parse CSV at %s", path)
    return None


def _normalize(df: pd.DataFrame, since: int) -> pd.DataFrame:
    cols_lower = {c: c.strip() for c in df.columns}
    df = df.rename(columns=cols_lower)
    col_names = [c.lower() for c in df.columns]

    commodity_col = _find_col(df.columns, ["commodity", "commodity_desc", "item"])
    value_col = _find_col(df.columns, ["value", "amount", "quantity"])
    year_col = _find_col(df.columns, [
        "year", "market year", "marketing year", "market_year",
        "sc_year", "fiscal_year",
    ])
    attribute_col = _find_col(df.columns, [
        "attribute", "sc_attribute_desc", "attribute_desc",
        "data item", "sc_commodity_desc",
    ])
    unit_col = _find_col(df.columns, ["unit", "unit_desc", "units", "sc_unit_desc"])
    freq_col = _find_col(df.columns, ["frequency", "freq", "sc_frequency_desc", "timeperiod_desc"])
    period_col = _find_col(df.columns, [
        "timeperiod_id", "period", "month", "sc_month",
    ])

    if value_col is None:
        log.error("ERS Feed Grains: cannot find value column. Found: %s", list(df.columns))
        return pd.DataFrame()

    records = []
    for _, row in df.iterrows():
        val_str = str(row.get(value_col, "")).replace(",", "").strip()
        if not val_str or val_str in ("", "NA", "None", "nan", "--"):
            continue
        try:
            value = float(val_str)
        except ValueError:
            continue

        raw_commodity = str(row.get(commodity_col, "CORN")).upper().strip() if commodity_col else "CORN"
        commodity = COMMODITY_NORM.get(raw_commodity)
        if commodity is None:
            continue

        year_str = str(row.get(year_col, "")).strip() if year_col else ""
        try:
            year_int = int(year_str.split("/")[0]) if "/" in year_str else int(float(year_str))
        except (ValueError, IndexError):
            continue
        if year_int < since:
            continue

        month = 1
        if period_col:
            period_str = str(row.get(period_col, "")).strip()
            month = _parse_month(period_str)

        obs_date = datetime(year_int, month, 1)

        raw_attr = str(row.get(attribute_col, "")).strip() if attribute_col else "unknown"
        metric_slug = re.sub(r"[^a-z0-9]+", "_", raw_attr.lower()).strip("_")
        metric = f"ers_fg__{metric_slug}"

        unit = str(row.get(unit_col, "")).strip() if unit_col else ""

        records.append({
            "obs_date": obs_date,
            "marketing_year": year_str,
            "commodity": commodity,
            "region": "US",
            "metric": metric,
            "value": value,
            "unit": unit,
            "source": SOURCE,
            "report_date": obs_date,
        })

    return pd.DataFrame(records)


def _parse_month(s: str) -> int:
    month_map = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    s_lower = s.lower().strip()
    for abbr, num in month_map.items():
        if abbr in s_lower:
            return num
    try:
        v = int(float(s))
        if 1 <= v <= 12:
            return v
    except (ValueError, TypeError):
        pass
    return 1


def _find_col(columns, candidates: list[str]) -> str | None:
    col_list = list(columns)
    for cand in candidates:
        for col in col_list:
            if cand.lower() == col.lower():
                return col
    for cand in candidates:
        for col in col_list:
            if cand.lower() in col.lower():
                return col
    return None
