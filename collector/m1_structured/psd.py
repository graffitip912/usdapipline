"""USDA FAS PSD Online – Production, Supply, and Distribution.

Downloads bulk CSV ZIPs for grains and oilseeds from the PSD database,
filters for corn/wheat/soybeans, and normalizes to the unified schema.

API docs: https://apps.fas.usda.gov/psdonline/app/index.html
No authentication required.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd

from common import manifest
from common.http import fetch
from common.schema import validate_and_stamp
from common.storage import RAW_DIR, ensure_dirs, norm_path, sha256_bytes, sha256_file

log = logging.getLogger(__name__)

SOURCE = "USDA_FAS_PSD"

BULK_DOWNLOADS = {
    "grains": "https://apps.fas.usda.gov/psdonline/downloads/psd_grains_pulses_csv.zip",
    "oilseeds": "https://apps.fas.usda.gov/psdonline/downloads/psd_oilseeds_csv.zip",
}

COMMODITY_CODES = {
    "440000": "CORN",
    "410000": "WHEAT",
    "2222000": "SOYBEAN",
}

ATTRIBUTE_NORM = {
    "Area Harvested": "area_harvested",
    "Area Planted": "area_planted",
    "Beginning Stocks": "beginning_stocks",
    "Domestic Consumption": "domestic_consumption",
    "Ending Stocks": "ending_stocks",
    "Exports": "exports",
    "Feed Dom. Consumption": "feed_domestic",
    "Feed Waste Dom. Cons.": "feed_waste_domestic",
    "Food Use Dom. Cons.": "food_use_domestic",
    "FSI Consumption": "fsi_consumption",
    "Imports": "imports",
    "Production": "production",
    "SME": "sme",
    "Total Distribution": "total_distribution",
    "Total Dom. Cons.": "total_domestic",
    "Total Supply": "total_supply",
    "TY Exports": "ty_exports",
    "TY Imp. from U.S.": "ty_imports_from_us",
    "TY Imports": "ty_imports",
    "Yield": "yield",
}


def _raw_dir() -> Path:
    return RAW_DIR / "psd"


def collect(since: int = 2010, force: bool = False) -> None:
    ensure_dirs()
    all_frames: list[pd.DataFrame] = []

    for group_name, url in BULK_DOWNLOADS.items():
        try:
            df = _download_and_parse(group_name, url, since, force)
            if df is not None and not df.empty:
                all_frames.append(df)
        except Exception:
            log.exception("PSD: failed to process %s", group_name)

    if all_frames:
        merged = pd.concat(all_frames, ignore_index=True)
        merged = merged.sort_values("obs_date").drop_duplicates(
            subset=["commodity", "obs_date", "metric", "region", "marketing_year"],
            keep="last",
        )
        merged = validate_and_stamp(merged, SOURCE)
        out = norm_path("psd.parquet")
        merged.to_parquet(out, index=False, compression="zstd")
        manifest.upsert(
            source=SOURCE,
            artifact_type="normalized_parquet",
            period=f"{since}-present",
            path=out,
            sha256=sha256_file(out),
        )
        log.info("PSD: wrote %d normalized records to %s", len(merged), out)
    else:
        log.warning("PSD: no records collected")


def _download_and_parse(
    group_name: str, url: str, since: int, force: bool,
) -> pd.DataFrame | None:
    log.info("PSD: downloading %s bulk CSV from %s", group_name, url)
    resp = fetch(url, stream=True, timeout=300)
    zip_bytes = resp.content
    zip_hash = sha256_bytes(zip_bytes)

    raw_zip = _raw_dir() / f"psd_{group_name}.zip"
    raw_zip.parent.mkdir(parents=True, exist_ok=True)

    if not force and manifest.has_unchanged(SOURCE, zip_hash):
        norm_file = norm_path("psd.parquet")
        if norm_file.exists():
            log.info("PSD: %s unchanged, skipping", group_name)
            return None
        log.info("PSD: %s unchanged but normalized missing, re-parsing", group_name)

    raw_zip.write_bytes(zip_bytes)
    manifest.upsert(
        source=SOURCE,
        artifact_type="raw_csv_zip",
        period=f"{since}-present",
        path=raw_zip,
        sha256=zip_hash,
    )

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
        if not csv_names:
            log.warning("PSD: no CSV found in %s", group_name)
            return None

        frames = []
        for csv_name in csv_names:
            with zf.open(csv_name) as f:
                df = pd.read_csv(f, low_memory=False)
                frames.append(df)

        df_all = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    if df_all.empty:
        return None

    return _normalize(df_all, since)


def _normalize(df: pd.DataFrame, since: int) -> pd.DataFrame:
    cols = {c: c.strip() for c in df.columns}
    df = df.rename(columns=cols)

    commodity_col = _find_col(df.columns, ["Commodity_Code", "commodity_code"])
    country_col = _find_col(df.columns, ["Country_Name", "country_name", "Country"])
    attribute_col = _find_col(df.columns, ["Attribute_Description", "attribute_description", "Attribute"])
    value_col = _find_col(df.columns, ["Value", "value"])
    year_col = _find_col(df.columns, ["Market_Year", "market_year", "Year"])
    unit_col = _find_col(df.columns, ["Unit_Description", "unit_description", "Unit"])
    month_col = _find_col(df.columns, ["Month", "month", "Calendar_Year"])

    if commodity_col is None or value_col is None:
        log.error("PSD: cannot identify required columns. Found: %s", list(df.columns))
        return pd.DataFrame()

    commodity_code_col = commodity_col
    if commodity_code_col:
        df[commodity_code_col] = df[commodity_code_col].astype(str).str.strip()
        df = df[df[commodity_code_col].isin(COMMODITY_CODES.keys())]

    if df.empty:
        return pd.DataFrame()

    records = []
    for _, row in df.iterrows():
        val_str = str(row.get(value_col, "")).replace(",", "").strip()
        if not val_str or val_str in ("", "NA", "None", "nan"):
            continue
        try:
            value = float(val_str)
        except ValueError:
            continue

        code = str(row.get(commodity_code_col, "")).strip()
        commodity = COMMODITY_CODES.get(code)
        if commodity is None:
            continue

        my = str(row.get(year_col, "")).strip() if year_col else ""
        try:
            year_int = int(my.split("/")[0]) if "/" in my else int(my)
        except (ValueError, IndexError):
            continue
        if year_int < since:
            continue

        obs_date = datetime(year_int, 9, 1)

        raw_attr = str(row.get(attribute_col, "")).strip() if attribute_col else "unknown"
        metric_slug = ATTRIBUTE_NORM.get(
            raw_attr,
            re.sub(r"[^a-z0-9]+", "_", raw_attr.lower()).strip("_"),
        )
        metric = f"psd__{metric_slug}"

        region = str(row.get(country_col, "World")).strip() if country_col else "World"
        unit = str(row.get(unit_col, "")).strip() if unit_col else ""

        records.append({
            "obs_date": obs_date,
            "marketing_year": my,
            "commodity": commodity,
            "region": region,
            "metric": metric,
            "value": value,
            "unit": unit,
            "source": SOURCE,
            "report_date": obs_date,
        })

    return pd.DataFrame(records)


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
