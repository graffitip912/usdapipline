"""WASDE – World Agricultural Supply and Demand Estimates (CSV).

Monthly comprehensive CSV from USDA OCE containing S&D balance sheet data
for corn, soybeans, and wheat (US + World), 2010-present.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import pandas as pd

from common import esmis, manifest
from common.http import download_file, head_ok
from common.schema import validate_and_stamp
from common.storage import RAW_DIR, ensure_dirs, norm_path, sha256_file

log = logging.getLogger(__name__)

SOURCE = "USDA_WASDE"

# Primary: OCE consolidated historical CSV (2010-present, richest format).
# Fallback: official ESMIS/Cornell API XML (per-release, see _collect_from_esmis).
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
    """Try recent 18 months to find the latest published OCE CSV.

    Circuit-breaker: after 3 consecutive failures www.usda.gov is
    considered unreachable and we fall back to ESMIS (see collect()).
    """
    # USER-CONFIG: max consecutive timeouts before falling back to ESMIS
    max_consecutive_failures = 3
    consecutive_failures = 0

    now = datetime.utcnow()
    for months_back in range(0, 18):
        year = now.year
        month = now.month - months_back
        while month <= 0:
            month += 12
            year -= 1
        url = URL_TEMPLATE.format(year=year, month=month)
        if head_ok(url, timeout=10):
            log.info("WASDE: found CSV at %s", url)
            return url
        consecutive_failures += 1
        if consecutive_failures >= max_consecutive_failures:
            log.warning(
                "WASDE: %d consecutive HEAD failures on www.usda.gov — will use ESMIS fallback",
                consecutive_failures,
            )
            return None
    return None


def collect(since: int = 2010, force: bool = False) -> None:
    ensure_dirs()

    url = _discover_latest_csv_url()
    if url is not None:
        try:
            _collect_from_csv(url, since, force)
            return
        except Exception:
            log.exception("WASDE: CSV path failed — falling back to ESMIS")

    log.info("WASDE: collecting from official ESMIS archive")
    _collect_from_esmis(since, force)


def _collect_from_csv(url: str, since: int, force: bool) -> None:
    filename = url.rsplit("/", 1)[-1]
    dest = RAW_DIR / "wasde" / filename
    download_file(url, dest)
    file_hash = sha256_file(dest)

    if not force and manifest.has_unchanged(SOURCE, file_hash):
        log.info("WASDE: CSV unchanged, skipping normalization")
        return

    df_raw = _read_csv(dest)
    if df_raw is None or df_raw.empty:
        log.warning("WASDE: CSV parsed but empty after filtering")
        return

    df_norm = _normalize(df_raw, since)
    if df_norm.empty:
        log.warning("WASDE: no records after normalization")
        return

    manifest.upsert(
        source=SOURCE,
        artifact_type="raw_csv",
        period=f"{since}-present",
        path=dest,
        sha256=file_hash,
    )
    log.info("WASDE: saved raw CSV -> %s", dest)

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


# ---------------------------------------------------------------------------
# ESMIS fallback — official USDA archive (esmis.nal.usda.gov via Cornell API)
# ---------------------------------------------------------------------------

# XML sub-report -> (commodity, matrix element) for U.S. supply & demand tables.
# Verified against wasde0626v2.xml: sr11=US wheat, sr12 matrix2=US corn,
# sr15 matrix1=US soybeans.
_XML_US_TABLES = {
    "sr11": ("WHEAT", "matrix1"),
    "sr12": ("CORN", "matrix2"),
    "sr15": ("SOYBEAN", "matrix1"),
}

# Extra aliases for XML attribute spellings not in METRIC_NORM
_XML_METRIC_ALIASES = {
    "FEED AND RESIDUAL": "feed_residual",
    "CRUSHINGS": "crush",
    "AVG. FARM PRICE": "avg_farm_price",
    "ETHANOL & BY-PRODUCTS": "ethanol_byproducts",
}

_XML_UNIT_BY_METRIC = {
    "area_planted": "Million Acres",
    "area_harvested": "Million Acres",
    "yield": "Bushels",
    "avg_farm_price": "$/bu",
}
_XML_DEFAULT_UNIT = "Million Bushels"


def _collect_from_esmis(since: int, force: bool) -> None:
    """Download the latest WASDE XML from the official ESMIS archive and
    merge its U.S. corn/soybean/wheat tables into the normalized parquet."""
    try:
        releases = esmis.release_files("wasde")
    except Exception:
        log.exception("WASDE: ESMIS API unreachable")
        return
    if not releases:
        log.error("WASDE: ESMIS API returned no releases")
        return

    report_date, files = releases[0]
    xml_url = esmis.pick_file(files, "xml")
    if xml_url is None:
        log.error("WASDE: latest ESMIS release has no XML file: %s", files)
        return

    dest = RAW_DIR / "wasde" / xml_url.rsplit("/", 1)[-1]
    try:
        download_file(xml_url, dest)
    except Exception:
        log.exception("WASDE: ESMIS XML download failed: %s", xml_url)
        return
    file_hash = sha256_file(dest)

    if not force and manifest.has_unchanged(SOURCE, file_hash) and norm_path("wasde.parquet").exists():
        log.info("WASDE: ESMIS XML unchanged, skipping normalization")
        return

    df_new = _normalize_xml(dest, since, report_date)
    if df_new.empty:
        log.warning("WASDE: no records parsed from ESMIS XML")
        return

    # Raw manifest only after successful normalization, so a parse failure
    # does not mark the hash as ingested and permanently skip this release.
    manifest.upsert(
        source=SOURCE,
        artifact_type="raw_xml_esmis",
        period=report_date.strftime("%Y-%m"),
        path=dest,
        sha256=file_hash,
    )
    log.info("WASDE: saved ESMIS XML -> %s", dest)

    df_new = _add_derived_metrics(df_new)
    # Stamp/validate BEFORE merging: concat with an already-stamped parquet
    # would leave new rows with ingested_at=NaT and pandera would drop them.
    df_new = validate_and_stamp(df_new, SOURCE)

    # Merge with existing normalized data. report_date is part of the key so
    # monthly report vintages accumulate instead of overwriting each other.
    out = norm_path("wasde.parquet")
    if out.exists():
        df_old = pd.read_parquet(out)
        df_new = pd.concat([df_old, df_new], ignore_index=True)
        df_new = df_new.drop_duplicates(
            subset=["commodity", "obs_date", "metric", "region",
                    "marketing_year", "report_date"],
            keep="last",
        )

    df_new.to_parquet(out, index=False, compression="zstd")
    manifest.upsert(
        source=SOURCE,
        artifact_type="normalized_parquet",
        period=f"{since}-present",
        path=out,
        sha256=sha256_file(out),
    )
    log.info("WASDE: wrote %d normalized records (ESMIS) -> %s", len(df_new), out)


def _clean_xml_attribute(raw: str) -> str:
    """'Avg. Farm Price ($/bu)  2/' -> 'AVG. FARM PRICE'"""
    s = re.sub(r"\([^)]*\)", "", raw)          # drop parenthesised units
    s = re.sub(r"(?:\s*\d+/)+\s*$", "", s)      # drop trailing footnote refs (may repeat)
    return re.sub(r"\s+", " ", s).strip().upper()


def _canonical_marketing_year(raw: str) -> str:
    """'2025/26 Est.' / '2026/27 Proj.' -> '2025/26' (shared by CSV/XML paths
    so the merge dedupe key stays consistent)."""
    return re.sub(r"\s*(Est\.|Proj\.)\s*$", "", raw).strip()


def _clean_xml_value(raw: str) -> float | None:
    s = raw.replace(",", "").replace("*", "").strip()
    if not s or s.upper() in ("NA", "NONE", "---"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _normalize_xml(path: Path, since: int, report_date: datetime) -> pd.DataFrame:
    """Parse U.S. S&D tables from a WASDE ESMIS XML into the unified schema.

    Year columns may repeat (previous vs. current projection); document
    order guarantees the last occurrence is the current report's value.
    """
    root = ET.parse(path).getroot()
    records: list[dict] = []

    for sr_name, (commodity, matrix_name) in _XML_US_TABLES.items():
        sr = root.find(sr_name)
        rep = sr.find("Report") if sr is not None else None
        matrix = rep.find(matrix_name) if rep is not None else None
        if matrix is None:
            log.warning("WASDE XML: table %s/%s not found", sr_name, matrix_name)
            continue

        for ag in matrix.iter():
            if not (ag.tag.startswith("attribute") and ag.attrib):
                continue
            attr_key = _clean_xml_attribute(next(iter(ag.attrib.values())))
            metric_slug = METRIC_NORM.get(attr_key) or _XML_METRIC_ALIASES.get(attr_key)
            if metric_slug is None:
                metric_slug = re.sub(r"[^a-z0-9]+", "_", attr_key.lower()).strip("_")

            # last cell per marketing year == current projection
            year_values: dict[str, float] = {}
            for yg in ag.iter():
                my_raw = next(
                    (v for k, v in yg.attrib.items() if k.startswith("market_year")),
                    None,
                )
                if my_raw is None:
                    continue
                my = _canonical_marketing_year(my_raw)
                for cell in yg.iter("Cell"):
                    val = _clean_xml_value(next(iter(cell.attrib.values()), ""))
                    if val is not None:
                        year_values[my] = val

            for my, value in year_values.items():
                obs_date = _parse_marketing_year_date(my, since)
                if obs_date is None or obs_date.year < since:
                    continue
                records.append({
                    "obs_date": obs_date,
                    "marketing_year": my,
                    "commodity": commodity,
                    "region": "US",
                    "metric": f"wasde__{metric_slug}",
                    "value": value,
                    "unit": _XML_UNIT_BY_METRIC.get(metric_slug, _XML_DEFAULT_UNIT),
                    "source": SOURCE,
                    "report_date": report_date,
                })

    return pd.DataFrame(records)


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

        my = _canonical_marketing_year(str(row.get(year_col, ""))) if year_col else None
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
