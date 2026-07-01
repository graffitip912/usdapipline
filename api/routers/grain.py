"""Grain data API endpoints — prices, supply, inventory, GTR indices."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query

from api.deps import get_data_backend
from common.data_access import DataBackend

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["grain"])

# USER-CONFIG: commodity name mappings for data lookup
COMMODITY_MAP = {
    "corn": "CORN",
    "soybeans": "SOYBEAN",
    "soybean": "SOYBEAN",
    "wheat": "WHEAT",
}


def _filter_grain_data(
    backend: DataBackend,
    commodity: str | None = None,
    metric: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[dict[str, Any]]:
    """Load and filter grain data from normalized parquet files."""
    files = backend.list_files("normalized/structured", "*.parquet")
    if not files:
        return []

    import pandas as pd
    frames = []
    for f in files:
        try:
            df = backend.read_parquet(f)
            if not df.empty:
                frames.append(df)
        except Exception:
            log.debug("Failed to read %s", f)

    if not frames:
        return []

    combined = pd.concat(frames, ignore_index=True)

    if commodity:
        mapped = COMMODITY_MAP.get(commodity.lower(), commodity.upper())
        combined = combined[combined["commodity"] == mapped]

    if metric:
        combined = combined[combined["metric"].str.contains(metric, case=False, na=False)]

    if "obs_date" in combined.columns:
        combined["obs_date"] = pd.to_datetime(combined["obs_date"], errors="coerce")
        if from_date:
            combined = combined[combined["obs_date"] >= from_date]
        if to_date:
            combined = combined[combined["obs_date"] <= to_date]
        combined = combined.sort_values("obs_date")

    columns = ["obs_date", "commodity", "metric", "value", "unit", "source", "report_date"]
    available = [c for c in columns if c in combined.columns]
    result = combined[available].copy()
    for col in result.select_dtypes(include=["datetime64"]).columns:
        result[col] = result[col].dt.strftime("%Y-%m-%d")

    return result.to_dict("records")


@router.get("/grain/prices")
async def grain_prices(
    commodity: str = Query(..., description="corn, soybeans, or wheat"),
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    backend: DataBackend = Depends(get_data_backend),
) -> list[dict[str, Any]]:
    return _filter_grain_data(backend, commodity=commodity, metric="price", from_date=from_date, to_date=to_date)


@router.get("/grain/supply")
async def grain_supply(
    commodity: str = Query(...),
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    backend: DataBackend = Depends(get_data_backend),
) -> list[dict[str, Any]]:
    return _filter_grain_data(backend, commodity=commodity, metric="supply", from_date=from_date, to_date=to_date)


@router.get("/grain/inventory")
async def grain_inventory(
    commodity: str = Query(...),
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    backend: DataBackend = Depends(get_data_backend),
) -> list[dict[str, Any]]:
    return _filter_grain_data(backend, commodity=commodity, metric="stock", from_date=from_date, to_date=to_date)


@router.get("/gtr/indices")
async def gtr_indices(
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    backend: DataBackend = Depends(get_data_backend),
) -> list[dict[str, Any]]:
    """GTR transportation index data."""
    files = backend.list_files("normalized/structured", "*gtr*.parquet")
    if not files:
        return []

    import pandas as pd
    frames = []
    for f in files:
        try:
            df = backend.read_parquet(f)
            if not df.empty:
                frames.append(df)
        except Exception:
            log.debug("Failed to read %s", f)

    if not frames:
        return []

    combined = pd.concat(frames, ignore_index=True)

    if "obs_date" in combined.columns:
        combined["obs_date"] = pd.to_datetime(combined["obs_date"], errors="coerce")
        if from_date:
            combined = combined[combined["obs_date"] >= from_date]
        if to_date:
            combined = combined[combined["obs_date"] <= to_date]
        combined = combined.sort_values("obs_date")

    columns = ["obs_date", "commodity", "metric", "value", "unit", "source", "report_date"]
    available = [c for c in columns if c in combined.columns]
    result = combined[available].copy()
    for col in result.select_dtypes(include=["datetime64"]).columns:
        result[col] = result[col].dt.strftime("%Y-%m-%d")

    return result.to_dict("records")
