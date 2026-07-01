"""Normalized time-series schema (long / tidy, single unified table)."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import pandas as pd
import pandera.pandas as pa
from pandera.typing.pandas import Series
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

VALID_COMMODITIES = ["CORN", "SOYBEAN", "WHEAT", "ALL_GRAINS"]


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
    ingested_at: datetime = Field(default_factory=datetime.utcnow)


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
        max_year = datetime.utcnow().year + 5
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
        df["ingested_at"] = pd.Timestamp.utcnow()
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
