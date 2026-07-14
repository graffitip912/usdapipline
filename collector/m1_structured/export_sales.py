"""USDA FAS Export Sales Reporting (ESR) – weekly export commitments.

Uses the FAS Open Data API to fetch weekly export sales data for
corn, wheat, and soybeans. Requires an API key (FAS_OPENDATA_API_KEY).

API docs: https://apps.fas.usda.gov/opendata/swagger/ui/index
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
)

from common import manifest
from common.schema import validate_and_stamp
from common.storage import RAW_DIR, ensure_dirs, norm_path, sha256_bytes, sha256_file

log = logging.getLogger(__name__)
load_dotenv()

SOURCE = "USDA_FAS_ESR"
API_BASE = "https://apps.fas.usda.gov/opendata/api"

GRAIN_KEYWORDS = {
    "wheat": "WHEAT",
    "corn": "CORN",
    "soybean": "SOYBEAN",
    "soybeans": "SOYBEAN",
}


def _api_key() -> str | None:
    key = os.getenv("FAS_OPENDATA_API_KEY", "")
    if not key:
        return None
    return key


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return exc.response.status_code >= 500
    return False


# USER-CONFIG: ESR retry waits (seconds). Kept short so a FAS server outage
# blocks a pipeline run for minutes, not hours (2026-07-02: old schedule
# 1m/5m/10m/15m x5 attempts made a single run take 5+ hours).
# N attempts sleep N-1 times, so len(waits) == attempts - 1.
_RETRY_WAIT_SECONDS = [30, 60]
_RETRY_MAX_ATTEMPTS = 3


def _wait_schedule(retry_state):
    idx = min(retry_state.attempt_number - 1, len(_RETRY_WAIT_SECONDS) - 1)
    return _RETRY_WAIT_SECONDS[idx]


@retry(
    retry=retry_if_exception(_is_retryable),
    wait=_wait_schedule,
    stop=stop_after_attempt(_RETRY_MAX_ATTEMPTS),
    before_sleep=lambda rs: log.warning(
        "ESR: retry %d/%d for %s in %ds (reason: %s)",
        rs.attempt_number, _RETRY_MAX_ATTEMPTS,
        rs.args[0] if rs.args else "?",
        _RETRY_WAIT_SECONDS[min(rs.attempt_number - 1, len(_RETRY_WAIT_SECONDS) - 1)],
        rs.outcome.exception(),
    ),
    reraise=True,
)
def _api_get_with_key(endpoint: str, api_key: str) -> list | dict | None:
    """GET with API key in header. Retries on 5xx / connection errors."""
    from common.http import get_session
    session = get_session()
    url = f"{API_BASE}{endpoint}"
    resp = session.get(url, headers={"API_KEY": api_key}, timeout=120)
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        log.error("ESR: invalid JSON from %s (status %d)", url, resp.status_code)
        return None


def _raw_dir() -> Path:
    return RAW_DIR / "export_sales"


FALLBACK_CODES = {
    "WHEAT": "100",
    "CORN": "101",
    "SOYBEAN": "102",
}


def _discover_commodity_codes(api_key: str) -> dict[str, str]:
    """Fetch commodity list and find codes for wheat, corn, soybeans."""
    try:
        commodities = _api_get_with_key("/esr/commodities", api_key)
    except Exception as exc:
        log.warning("ESR: commodity list unavailable (%s), using fallback codes", exc)
        return dict(FALLBACK_CODES)

    if not isinstance(commodities, list):
        log.warning("ESR: unexpected commodity response, using fallback codes")
        return dict(FALLBACK_CODES)

    codes = {}
    for item in commodities:
        name = str(item.get("commodityName", item.get("name", ""))).lower()
        code = str(item.get("commodityCode", item.get("code", "")))
        for keyword, norm in GRAIN_KEYWORDS.items():
            if keyword in name and norm not in codes:
                codes[norm] = code
                break

    if not codes:
        log.warning("ESR: no grain codes found in API response, using fallback codes")
        return dict(FALLBACK_CODES)

    log.info("ESR: discovered commodity codes: %s", codes)
    return codes


def _current_market_year() -> int:
    now = datetime.now(timezone.utc)
    return now.year if now.month >= 6 else now.year - 1


def collect(since: int = 2010, force: bool = False) -> None:
    ensure_dirs()
    api_key = _api_key()
    if api_key is None:
        log.warning(
            "ESR: FAS_OPENDATA_API_KEY not set, skipping. "
            "Get one at https://apps.fas.usda.gov/opendataweb/home"
        )
        manifest.record_skipped(SOURCE, "FAS_OPENDATA_API_KEY not set")
        return

    commodity_codes = _discover_commodity_codes(api_key)
    if not commodity_codes:
        # Visible failure: run_source records this in manifest + verification history
        raise RuntimeError(
            "ESR: commodity discovery failed — FAS opendata API unreachable"
        )

    raw_dir = _raw_dir()
    raw_dir.mkdir(parents=True, exist_ok=True)

    current_my = _current_market_year()
    all_frames: list[pd.DataFrame] = []
    request_errors = 0

    for commodity, code in commodity_codes.items():
        for year in range(since, current_my + 1):
            try:
                raw_path = raw_dir / f"esr_{commodity.lower()}_{year}.json"

                if raw_path.exists() and not force:
                    raw_bytes = raw_path.read_bytes()
                    raw_hash = sha256_bytes(raw_bytes)
                    if manifest.has_unchanged(SOURCE, raw_hash):
                        norm_file = norm_path("export_sales.parquet")
                        if norm_file.exists():
                            log.debug("ESR: %s/%d unchanged", commodity, year)
                            continue
                        data = json.loads(raw_bytes)
                    else:
                        data = None
                else:
                    data = None

                if data is None:
                    endpoint = (
                        f"/esr/exports/commodityCode/{code}"
                        f"/allCountries/marketYear/{year}"
                    )
                    try:
                        data = _api_get_with_key(endpoint, api_key)
                    except Exception:
                        log.debug("ESR: request failed for %s/%d", commodity, year)
                        request_errors += 1
                        continue

                    if not data:
                        continue

                    raw_bytes = json.dumps(data, indent=2).encode()
                    raw_hash = sha256_bytes(raw_bytes)
                    raw_path.write_bytes(raw_bytes)
                    manifest.upsert(
                        source=SOURCE,
                        artifact_type="raw_json",
                        period=f"{year}",
                        path=raw_path,
                        sha256=raw_hash,
                    )

                df = _normalize_records(data, commodity, year)
                if not df.empty:
                    all_frames.append(df)

                log.info("ESR: %s/%d -> %d records", commodity, year, len(df))

            except Exception:
                log.exception("ESR: failed %s/%d", commodity, year)
                request_errors += 1

    if all_frames:
        merged = pd.concat(all_frames, ignore_index=True)
        merged = merged.sort_values("report_date").drop_duplicates(
            subset=["commodity", "obs_date", "metric", "region", "marketing_year"],
            keep="last",
        )
        merged = validate_and_stamp(merged, SOURCE)
        out = norm_path("export_sales.parquet")
        merged.to_parquet(out, index=False, compression="zstd")
        manifest.upsert(
            source=SOURCE,
            artifact_type="normalized_parquet",
            period=f"{since}-present",
            path=out,
            sha256=sha256_file(out),
        )
        log.info("ESR: wrote %d normalized records to %s", len(merged), out)
    elif request_errors > 0:
        # Nothing collected AND requests failed -> surface as a real failure
        # instead of a silent "ok" (audit finding R1, 2026-07-03)
        raise RuntimeError(
            f"ESR: no data collected — {request_errors} request failures "
            f"(FAS opendata outage?)"
        )
    else:
        log.info("ESR: no new data (all cached/unchanged)")


def _normalize_records(
    data: list[dict], commodity: str, market_year: int,
) -> pd.DataFrame:
    if not isinstance(data, list):
        return pd.DataFrame()

    records = []
    for row in data:
        week_ending = row.get("weekEndingDate", row.get("reportingDate", ""))
        if not week_ending:
            continue
        try:
            obs_date = pd.to_datetime(week_ending).to_pydatetime()
        except Exception:
            continue

        country = str(row.get("countryDescription", row.get("country", "World"))).strip()

        metric_fields = {
            "currentWeeklyExports": "weekly_exports",
            "accumulatedExports": "accumulated_exports",
            "outstandingSales": "outstanding_sales",
            "grossNewSales": "gross_new_sales",
            "currentNetSales": "net_sales",
            "totalCommitment": "total_commitment",
            "netSales": "net_sales",
            "weeklyExports": "weekly_exports",
        }

        for field, metric_slug in metric_fields.items():
            val = row.get(field)
            if val is None:
                continue
            try:
                value = float(str(val).replace(",", ""))
            except (ValueError, TypeError):
                continue

            records.append({
                "obs_date": obs_date,
                "marketing_year": str(market_year),
                "commodity": commodity,
                "region": country,
                "metric": f"esr__{metric_slug}",
                "value": value,
                "unit": "mt",
                "source": SOURCE,
                "report_date": obs_date,
            })

    return pd.DataFrame(records)
