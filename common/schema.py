"""Normalized time-series schema (long / tidy, single unified table)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd
import pandera.pandas as pa
from pandera.typing.pandas import Series
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# as-is: 곡물 3종 + 합산 / to-be: FIELDWORK 추가 (노동가능일수 — 곡물 아닌 환경 지표,
# predict-models TB2 v2 이미지 추출값 자동 대조용 정답 데이터)
# SOIL(수분도)·DROUGHT(가뭄도 USDM)는 지도분석 v2 지표 (2026-07-10)
VALID_COMMODITIES = ["CORN", "SOYBEAN", "WHEAT", "ALL_GRAINS", "FIELDWORK", "SOIL", "DROUGHT"]


# ---------------------------------------------------------------------------
# Pydantic model – per-record validation & serialization
# ---------------------------------------------------------------------------
class GrainRecord(BaseModel):
    obs_date: date
    marketing_year: Optional[str] = None
    commodity: str
    region: str
    metric: str
    value: float
    unit: str
    source: str
    report_date: date
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Pandera schema – DataFrame-level validation before Parquet write
# ---------------------------------------------------------------------------
class GrainSchema(pa.DataFrameModel):
    obs_date: Series[pa.DateTime]
    marketing_year: Series[str] = pa.Field(nullable=True)
    commodity: Series[str] = pa.Field(isin=VALID_COMMODITIES)
    region: Series[str]
    metric: Series[str]
    value: Series[float]
    unit: Series[str]
    source: Series[str]
    report_date: Series[pa.DateTime]
    ingested_at: Series[pa.DateTime]

    class Config:
        coerce = True


def clip_dates(
    df: pd.DataFrame, col: str = "obs_date",
    min_year: int = 1980, max_year: int | None = None,
) -> pd.DataFrame:
    """Remove rows where *col* falls outside [min_year, max_year]."""
    if max_year is None:
        max_year = datetime.now(timezone.utc).year + 5
    df[col] = pd.to_datetime(df[col], errors="coerce")
    before = len(df)
    mask = df[col].notna() & (df[col].dt.year >= min_year) & (df[col].dt.year <= max_year)
    df = df.loc[mask].copy()
    dropped = before - len(df)
    if dropped:
        log.warning("clip_dates: dropped %d rows with %s outside %d-%d", dropped, col, min_year, max_year)
    return df


def validate_and_stamp(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Add ingested_at, coerce types, validate, and return cleaned df.

    On validation failure: logs violations, drops bad rows, returns the rest.
    """
    df = df.copy()
    if "ingested_at" not in df.columns:
        df["ingested_at"] = pd.Timestamp.now("UTC")
    if "source" not in df.columns:
        df["source"] = source
    for col in ("obs_date", "report_date", "ingested_at"):
        df[col] = pd.to_datetime(df[col], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])

    df = clip_dates(df, "obs_date")
    df = clip_dates(df, "report_date")

    try:
        GrainSchema.validate(df, lazy=True)
    except pa.errors.SchemaErrors as exc:
        failure_cases = exc.failure_cases
        log.warning(
            "Schema validation: %d failure(s) - dropping bad rows. Sample: %s",
            len(failure_cases),
            failure_cases.head(5).to_dict("records"),
        )
        bad_indices = set(failure_cases["index"].dropna().astype(int))
        df = df.drop(index=bad_indices, errors="ignore")
        if df.empty:
            log.error("Schema validation: all rows failed - returning empty DataFrame")
            return df
        GrainSchema.validate(df, lazy=True)

    return df


def validate_with_report(
    df: pd.DataFrame, source: str,
) -> tuple[pd.DataFrame, dict]:
    """Run validation and return (cleaned_df, report).

    The report dict contains structured validation results for
    verification history and user review preview.
    """
    row_count_before = len(df)
    report: dict = {
        "source": source,
        "schema_pass": True,
        "row_count_before": row_count_before,
        "row_count_after": 0,
        "dropped_count": 0,
        "error_details": [],
        "sample_stats": {},
    }

    df_copy = df.copy()
    if "ingested_at" not in df_copy.columns:
        df_copy["ingested_at"] = pd.Timestamp.now("UTC")
    if "source" not in df_copy.columns:
        df_copy["source"] = source
    for col in ("obs_date", "report_date", "ingested_at"):
        df_copy[col] = pd.to_datetime(df_copy[col], errors="coerce")
    df_copy["value"] = pd.to_numeric(df_copy["value"], errors="coerce")
    df_copy = df_copy.dropna(subset=["value"])
    df_copy = clip_dates(df_copy, "obs_date")
    df_copy = clip_dates(df_copy, "report_date")

    try:
        GrainSchema.validate(df_copy, lazy=True)
    except pa.errors.SchemaErrors as exc:
        failure_cases = exc.failure_cases
        report["schema_pass"] = False
        report["error_details"] = failure_cases.head(20).to_dict("records")

        bad_indices = set(failure_cases["index"].dropna().astype(int))
        df_copy = df_copy.drop(index=bad_indices, errors="ignore")
        if not df_copy.empty:
            try:
                GrainSchema.validate(df_copy, lazy=True)
                report["schema_pass"] = True
            except pa.errors.SchemaErrors:
                report["schema_pass"] = False

    report["row_count_after"] = len(df_copy)
    report["dropped_count"] = row_count_before - len(df_copy)

    numeric_cols = df_copy.select_dtypes(include="number").columns.tolist()
    for col in numeric_cols:
        series = df_copy[col].dropna()
        if not series.empty:
            report["sample_stats"][col] = {
                "min": float(series.min()),
                "max": float(series.max()),
                "mean": round(float(series.mean()), 4),
                "null_pct": round(float(df_copy[col].isna().mean()) * 100, 2),
            }

    return df_copy, report
