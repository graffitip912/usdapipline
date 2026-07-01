"""WASDE – World Agricultural Supply and Demand Estimates (CSV).

Monthly comprehensive CSV from USDA OCE containing S&D balance sheet data
for corn, soybeans, and wheat (US + World), 2010-present.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from common import manifest
from common.http import download_file, fetch, head_ok
from common.schema import validate_and_stamp
from common.storage import RAW_DIR, ensure_dirs, norm_path, sha256_file

log = logging.getLogger(__name__)

SOURCE = "USDA_WASDE"

URL_TEMPLATE = (
    "https://www.usda.gov/sites/default/files/documents/"
    "oce-wasde-report-data-{year}-{month:02d}.csv"
)

COMMODITY_FILTER = {"CORN", "SOYBEANS", "SOYBEAN OIL", "SOYBEAN MEAL", "WHEAT"}

COMMODITY_NORM = {
    "CORN": "CORN",
    "SOYBEANS": "SOYBEAN",
    "SOYBEAN OIL": "SOYBEAN",
    "SOYBEAN MEAL": "SOYBEAN",
    "WHEAT": "WHEAT",
}

METRIC_NORM = {
    "AREA PLANTED": "area_planted",
    "AREA HARVESTED": "area_harvested",
    "YIELD PER HARVESTED ACRE": "yield",
    "BEGINNING STOCKS": "beginning_stocks",
    "PRODUCTION": "production",
    "IMPORTS": "imports",
    "SUPPLY, TOTAL": "supply_total",
    "FEED & RESIDUAL": "feed_residual",
    "FOOD, SEED & INDUSTRIAL": "food_seed_industrial",
    "DOMESTIC, TOTAL": "domestic_total",
    "EXPORTS": "exports",
    "USE, TOTAL": "use_total",
    "ENDING STOCKS": "ending_stocks",
    "AVG. FARM PRICE": "avg_farm_price",
    "CRUSH": "crush",
    "TOTAL DOMESTIC": "domestic_total",
    "TOTAL USE": "use_total",
    "TOTAL SUPPLY": "supply_total",
    "FOOD": "food",
    "SEED": "seed",
}


def _discover_latest_csv_url() -> str | None:
    """Try recent 18 months to find the latest published CSV."""
    now = datetime.utcnow()
    for months_back in range(0, 18):
        year = now.year
        month = now.month - months_back
        while month <= 0:
            month += 12
            year -= 1
        url = URL_TEMPLATE.format(year=year, month=month)
        if head_ok(url, timeout=15):
            log.info("WASDE: found CSV at %s", url)
            return url
    return None


def collect(since: int = 2010, force: bool = False) -> None:
    ensure_dirs()

    url = _discover_latest_csv_url()
    if url is None:
        raise RuntimeError("WASDE: could not find any CSV in last 18 months")

    filename = url.rsplit("/", 1)[-1]
    dest = RAW_DIR / "wasde" / filename
    download_file(url, dest)
    file_hash = sha256_file(dest)

    if not force and manifest.has_unchanged(SOURCE, file_hash):
        log.info("WASDE: CSV unchanged, skipping normalization")
        return

    manifest.upsert(
        source=SOURCE,
        artifact_type="raw_csv",
        period=f"{since}-present",
        path=dest,
        sha256=file_hash,
    )
    log.info("WASDE: saved raw CSV -> %s", dest)

    df_raw = _read_csv(dest)
    if df_raw is None or df_raw.empty:
        log.warning("WASDE: CSV parsed but empty after filtering")
        return

    df_norm = _normalize(df_raw, since)
    if df_norm.empty:
        log.warning("WASDE: no records after normalization")
        return

    df_norm = _add_derived_metrics(df_norm)
    df_norm = validate_and_stamp(df_norm, SOURCE)
    out = norm_path("wasde.parquet")
    df_norm.to_parquet(out, index=False, compression="zstd")
    manifest.upsert(
        source=SOURCE,
        artifact_type="normalized_parquet",
        period=f"{since}-present",
        path=out,
        sha256=sha256_file(out),
    )
    log.info("WASDE: wrote %d normalized records -> %s", len(df_norm), out)


def _read_csv(path: Path) -> pd.DataFrame | None:
    """Read WASDE comprehensive CSV with flexible encoding/delimiter detection."""
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            df = pd.read_csv(path, encoding=encoding, low_memory=False)
            if len(df.columns) >= 5:
                log.debug("WASDE: CSV parsed with encoding=%s (%d cols)", encoding, len(df.columns))
                return df
        except (UnicodeDecodeError, pd.errors.ParserError, ValueError) as exc:
            log.debug("WASDE: encoding %s failed for %s: %s", encoding, path.name, exc)
            continue
    log.error("WASDE: unable to parse CSV at %s", path)
    return None


def _normalize(df: pd.DataFrame, since: int) -> pd.DataFrame:
    """Convert WASDE CSV rows -> unified long/tidy schema."""
    cols_lower = {c: c.lower().strip() for c in df.columns}
    df = df.rename(columns=cols_lower)
    col_names = list(df.columns)

    commodity_col = _find_col(col_names, ["commodity", "commodity_desc"])
    attribute_col = _find_col(col_names, ["attribute", "attribute_desc", "item"])
    value_col = _find_col(col_names, ["value", "amount"])
    unit_col = _find_col(col_names, ["unit", "unit_desc", "units"])
    year_col = _find_col(col_names, [
        "marketing year", "market year", "marketyear",
        "marketing_year", "market_year", "year",
    ])
    region_col = _find_col(col_names, ["region", "country", "area"])
    report_date_col = _find_col(col_names, [
        "report date", "report_date", "reportdate", "release date",
        "release_date", "releasedate", "report_month",
    ])

    if commodity_col is None or value_col is None:
        log.error(
            "WASDE: cannot identify required columns. Found: %s", col_names
        )
        return pd.DataFrame()

    if commodity_col:
        df = df[df[commodity_col].astype(str).str.upper().isin(COMMODITY_FILTER)]

    records = []
    for _, row in df.iterrows():
        val_str = str(row.get(value_col, "")).replace(",", "").strip()
        if not val_str or val_str in ("NA", "", "None", "nan"):
            continue
        try:
            value = float(val_str)
        except ValueError:
            continue

        raw_commodity = str(row.get(commodity_col, "")).upper().strip()
        commodity = COMMODITY_NORM.get(raw_commodity, raw_commodity)
        if commodity not in ("CORN", "SOYBEAN", "WHEAT"):
            continue

        raw_attribute = str(row.get(attribute_col, "")).upper().strip() if attribute_col else "UNKNOWN"
        metric = METRIC_NORM.get(raw_attribute, re.sub(r"[^a-z0-9]+", "_", raw_attribute.lower()).strip("_"))
        metric = f"wasde__{metric}"

        unit = str(row.get(unit_col, "")).strip() if unit_col else ""
        region = str(row.get(region_col, "US")).strip() if region_col else "US"

        my = str(row.get(year_col, "")).strip() if year_col else None
        obs_date = _parse_marketing_year_date(my, since)
        if obs_date is None:
            continue
        if obs_date.year < since:
            continue

        report_date = obs_date
        if report_date_col:
            rd_str = str(row.get(report_date_col, "")).strip()
            try:
                report_date = pd.to_datetime(rd_str)
            except Exception:
                pass

        records.append({
            "obs_date": obs_date,
            "marketing_year": my,
            "commodity": commodity,
            "region": region,
            "metric": metric,
            "value": value,
            "unit": unit,
            "source": SOURCE,
            "report_date": report_date,
        })

    return pd.DataFrame(records)


def _add_derived_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Compute stocks-to-use ratio from ending_stocks and use_total."""
    stocks = df[df["metric"] == "wasde__ending_stocks"].copy()
    use = df[df["metric"] == "wasde__use_total"].copy()
    if stocks.empty or use.empty:
        return df

    merge_keys = ["commodity", "marketing_year", "region", "obs_date"]
    merged = stocks.merge(
        use[merge_keys + ["value"]],
        on=merge_keys,
        suffixes=("_stocks", "_use"),
        how="inner",
    )
    merged = merged[merged["value_use"] > 0]
    if merged.empty:
        return df

    derived = merged.copy()
    derived["value"] = derived["value_stocks"] / derived["value_use"]
    derived["metric"] = "wasde__stocks_to_use_ratio"
    derived["unit"] = "ratio"
    derived = derived.drop(columns=["value_stocks", "value_use"], errors="ignore")

    return pd.concat([df, derived[df.columns]], ignore_index=True)


def _find_col(columns: list[str], candidates: list[str]) -> str | None:
    for cand in candidates:
        for col in columns:
            if cand == col or cand.replace(" ", "_") == col or cand.replace("_", " ") == col:
                return col
    for cand in candidates:
        for col in columns:
            if cand in col:
                return col
    return None


def _parse_marketing_year_date(my: str | None, since: int) -> datetime | None:
    if not my:
        return None
    my = my.strip()

    m = re.match(r"(\d{4})/(\d{2,4})", my)
    if m:
        return datetime(int(m.group(1)), 9, 1)

    m = re.match(r"(\d{4})-(\d{2,4})", my)
    if m:
        return datetime(int(m.group(1)), 9, 1)

    m = re.match(r"(\d{4})", my)
    if m:
        return datetime(int(m.group(1)), 1, 1)

    try:
        return pd.to_datetime(my).to_pydatetime()
    except Exception:
        return None
