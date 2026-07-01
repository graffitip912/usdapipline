"""USDA NASS QuickStats API – Grain Stocks, Crop Progress/Condition, Production.

Handles the 50,000-row limit by splitting queries by commodity x year range.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from common import manifest
from common.http import fetch
from common.schema import validate_and_stamp
from common.storage import RAW_DIR, ensure_dirs, norm_path, sha256_bytes, sha256_file

log = logging.getLogger(__name__)

load_dotenv()

SOURCE = "USDA_NASS_QUICKSTATS"
API_BASE = "https://quickstats.nass.usda.gov/api"
API_GET = f"{API_BASE}/api_GET/"
API_COUNT = f"{API_BASE}/get_counts/"

COMMODITIES = ["CORN", "SOYBEANS", "WHEAT"]
COMMODITY_NORM = {"CORN": "CORN", "SOYBEANS": "SOYBEAN", "WHEAT": "WHEAT"}

QUERY_PROFILES: list[dict] = [
    {
        "name": "grain_stocks",
        "params": {
            "source_desc": "SURVEY",
            "sector_desc": "CROPS",
            "statisticcat_desc": "STOCKS",
            "agg_level_desc": "NATIONAL",
        },
        "metric_prefix": "stocks",
    },
    {
        "name": "crop_progress",
        "params": {
            "source_desc": "SURVEY",
            "sector_desc": "CROPS",
            "statisticcat_desc": "PROGRESS",
            "freq_desc": "WEEKLY",
        },
        "metric_prefix": "progress",
    },
    {
        "name": "crop_condition",
        "params": {
            "source_desc": "SURVEY",
            "sector_desc": "CROPS",
            "statisticcat_desc": "CONDITION",
            "freq_desc": "WEEKLY",
        },
        "metric_prefix": "condition",
    },
    {
        "name": "production",
        "params": {
            "source_desc": "SURVEY",
            "sector_desc": "CROPS",
            "statisticcat_desc": "PRODUCTION",
            "agg_level_desc": "NATIONAL",
        },
        "metric_prefix": "production",
    },
    {
        "name": "yield",
        "params": {
            "source_desc": "SURVEY",
            "sector_desc": "CROPS",
            "statisticcat_desc": "YIELD",
            "agg_level_desc": "NATIONAL",
        },
        "metric_prefix": "yield",
    },
    {
        "name": "area_planted",
        "params": {
            "source_desc": "SURVEY",
            "sector_desc": "CROPS",
            "statisticcat_desc": "AREA PLANTED",
            "agg_level_desc": "NATIONAL",
        },
        "metric_prefix": "area_planted",
    },
    {
        "name": "area_harvested",
        "params": {
            "source_desc": "SURVEY",
            "sector_desc": "CROPS",
            "statisticcat_desc": "AREA HARVESTED",
            "agg_level_desc": "NATIONAL",
        },
        "metric_prefix": "area_harvested",
    },
]


def _api_key() -> str:
    key = os.getenv("NASS_QUICKSTATS_API_KEY", "")
    if not key:
        raise RuntimeError(
            "NASS_QUICKSTATS_API_KEY not set. "
            "Get one at https://quickstats.nass.usda.gov/api"
        )
    return key


def _get_count(params: dict) -> int:
    resp = fetch(API_COUNT, params={**params, "key": _api_key()})
    try:
        data = resp.json()
    except ValueError:
        log.error("QuickStats: invalid JSON from count API")
        return 0
    return int(data.get("count", 0))


def _api_get(params: dict) -> list[dict]:
    resp = fetch(API_GET, params={**params, "key": _api_key(), "format": "JSON"})
    try:
        data = resp.json()
    except ValueError:
        log.error("QuickStats: invalid JSON from data API")
        return []
    if "error" in data:
        log.warning("QuickStats API error: %s", data["error"])
        return []
    return data.get("data", [])


def _fetch_profile_commodity(
    profile: dict, commodity: str, since: int
) -> list[dict]:
    """Fetch one (profile, commodity) pair, splitting by year if >50k rows."""
    params = {
        **profile["params"],
        "commodity_desc": commodity,
        "year__GE": str(since),
    }

    count = _get_count(params)
    log.info(
        "QuickStats: %s / %s since %d -> %d rows",
        profile["name"], commodity, since, count,
    )

    if count == 0:
        return []

    if count <= 50_000:
        return _api_get(params)

    all_rows: list[dict] = []
    year = since
    current_year = datetime.utcnow().year
    while year <= current_year:
        year_end = min(year + 4, current_year)
        chunk_params = {**params, "year__GE": str(year), "year__LE": str(year_end)}
        chunk_count = _get_count(chunk_params)
        if chunk_count > 50_000:
            for y in range(year, year_end + 1):
                single_params = {**params, "year__GE": str(y), "year__LE": str(y)}
                all_rows.extend(_api_get(single_params))
        elif chunk_count > 0:
            all_rows.extend(_api_get(chunk_params))
        year = year_end + 1

    return all_rows


def _parse_obs_date(row: dict) -> datetime | None:
    year = row.get("year")
    ref = row.get("reference_period_desc", "").upper().strip()
    if not year:
        return None
    try:
        year = int(year)
    except ValueError:
        return None

    month_map = {
        "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
        "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
        "FIRST OF JAN": 1, "FIRST OF MAR": 3, "FIRST OF JUN": 6,
        "FIRST OF SEP": 9,
    }

    if ref in month_map:
        return datetime(year, month_map[ref], 1)

    if ref in ("YEAR", "ANNUAL"):
        return datetime(year, 1, 1)

    week_match = re.search(r"WEEK\s*#?\s*(\d+)", ref)
    if week_match:
        week_num = int(week_match.group(1))
        try:
            return datetime.strptime(f"{year}-W{week_num:02d}-1", "%Y-W%W-%w")
        except ValueError:
            return datetime(year, 1, 1)

    if ref.startswith("MARKETING YEAR"):
        return datetime(year, 9, 1)

    return datetime(year, 1, 1)


def _parse_report_date(row: dict, obs_date: datetime) -> datetime:
    """Use load_time as report_date to distinguish multiple estimate releases."""
    load_time = row.get("load_time", "")
    if load_time:
        try:
            return pd.to_datetime(load_time).to_pydatetime()
        except Exception:
            pass
    return obs_date


def _normalize_rows(rows: list[dict], profile: dict) -> pd.DataFrame:
    records = []
    for row in rows:
        val_str = str(row.get("Value", "")).replace(",", "").strip()
        if val_str in ("", "(D)", "(Z)", "(NA)", "(S)", "(X)"):
            continue
        try:
            value = float(val_str)
        except ValueError:
            continue

        obs_date = _parse_obs_date(row)
        if obs_date is None:
            continue

        commodity_raw = row.get("commodity_desc", "").upper()
        commodity = COMMODITY_NORM.get(commodity_raw, commodity_raw)

        short_desc = row.get("short_desc", "")
        metric_slug = re.sub(r"[^a-z0-9]+", "_", short_desc.lower()).strip("_")
        metric = f"{profile['metric_prefix']}__{metric_slug}"

        region = row.get("state_alpha", "US")
        if row.get("agg_level_desc") == "NATIONAL":
            region = "US"

        unit = row.get("unit_desc", "")
        report_date = _parse_report_date(row, obs_date)

        records.append({
            "obs_date": obs_date,
            "marketing_year": row.get("begin_code"),
            "commodity": commodity,
            "region": region,
            "metric": metric,
            "value": value,
            "unit": unit,
            "source": SOURCE,
            "report_date": report_date,
        })

    return pd.DataFrame(records)


def collect(since: int = 2010, force: bool = False) -> None:
    ensure_dirs()
    norm_file = norm_path("quickstats.parquet")
    all_frames: list[pd.DataFrame] = []

    for profile in QUERY_PROFILES:
        for commodity in COMMODITIES:
            try:
                raw_path = (
                    RAW_DIR / "quickstats"
                    / f"{profile['name']}_{commodity.lower()}_{since}.json"
                )

                rows = None
                raw_bytes = None
                raw_hash = None

                if raw_path.exists():
                    raw_bytes = raw_path.read_bytes()
                    raw_hash = sha256_bytes(raw_bytes)

                if raw_hash and not force and manifest.has_unchanged(SOURCE, raw_hash):
                    if norm_file.exists():
                        log.info(
                            "QuickStats: %s/%s unchanged, normalized exists",
                            profile["name"], commodity,
                        )
                        continue
                    log.info(
                        "QuickStats: %s/%s raw cached but normalized missing, re-normalizing",
                        profile["name"], commodity,
                    )
                    rows = json.loads(raw_bytes)
                else:
                    rows = _fetch_profile_commodity(profile, commodity, since)
                    if not rows:
                        continue

                    raw_bytes = json.dumps(rows, indent=2).encode()
                    raw_hash = sha256_bytes(raw_bytes)

                    raw_path.parent.mkdir(parents=True, exist_ok=True)
                    raw_path.write_bytes(raw_bytes)
                    manifest.upsert(
                        source=SOURCE,
                        artifact_type="raw_json",
                        period=f"{since}-present",
                        path=raw_path,
                        sha256=raw_hash,
                    )

                df = _normalize_rows(rows, profile)
                if not df.empty:
                    all_frames.append(df)

                log.info(
                    "QuickStats: %s/%s -> %d records",
                    profile["name"], commodity, len(df),
                )
            except Exception:
                log.exception(
                    "QuickStats: failed %s/%s", profile["name"], commodity
                )

    if all_frames:
        merged = pd.concat(all_frames, ignore_index=True)
        merged = merged.sort_values("report_date").drop_duplicates(
            subset=["commodity", "obs_date", "metric"], keep="last",
        )
        merged = validate_and_stamp(merged, SOURCE)
        merged.to_parquet(norm_file, index=False, compression="zstd")
        manifest.upsert(
            source=SOURCE,
            artifact_type="normalized_parquet",
            period=f"{since}-present",
            path=norm_file,
            sha256=sha256_file(norm_file),
        )
        log.info("QuickStats: wrote %d normalized records to %s", len(merged), norm_file)
    else:
        log.warning("QuickStats: no records collected")
