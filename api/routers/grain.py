"""Grain data API endpoints — prices, supply, inventory, GTR indices."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query

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

# USER-CONFIG: metric category patterns — each list entry is matched with str.contains()
METRIC_CATEGORIES: dict[str, list[str]] = {
    "price": [
        "price_received",
        "price_spread__",
        "loan_rate",
    ],
    "supply": [
        "total_supply",
        "production",
        "domestic_consumption",
        "imports",
    ],
    "stock": [
        "beginning_stocks",
        "ending_stocks",
    ],
}

# USER-CONFIG: GTR weekly index metrics to show on dashboard (base year 2000)
GTR_INDEX_METRICS = [
    "transport_cost__truck",
    "transport_cost__rail_1",
    "transport_cost__barge",
    "transport_cost__gulf_ocean_vessel",
    "transport_cost__pacific",
]

# USER-CONFIG: human-readable labels for GTR index metrics
GTR_METRIC_LABELS = {
    "transport_cost__truck": "Truck",
    "transport_cost__rail_1": "Rail",
    "transport_cost__barge": "Barge",
    "transport_cost__gulf_ocean_vessel": "Gulf Ocean",
    "transport_cost__pacific": "Pacific",
}


def _load_all_grain(backend: DataBackend) -> pd.DataFrame:
    files = backend.list_files("normalized/structured", "*.parquet")
    if not files:
        return pd.DataFrame()

    frames = []
    for f in files:
        try:
            df = backend.read_parquet(f)
            if not df.empty:
                frames.append(df)
        except Exception:
            log.debug("Failed to read %s", f)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    if "obs_date" in combined.columns:
        combined["obs_date"] = pd.to_datetime(combined["obs_date"], errors="coerce")
    return combined


def _filter_by_commodity(df: pd.DataFrame, commodity: str) -> pd.DataFrame:
    mapped = COMMODITY_MAP.get(commodity.lower(), commodity.upper())
    return df[df["commodity"] == mapped]


def _filter_by_metric_category(df: pd.DataFrame, category: str) -> pd.DataFrame:
    patterns = METRIC_CATEGORIES.get(category, [])
    if not patterns:
        return df
    mask = pd.Series(False, index=df.index)
    for pattern in patterns:
        mask |= df["metric"].str.contains(pattern, case=False, na=False)
    return df[mask]


def _filter_by_date(
    df: pd.DataFrame,
    from_date: str | None = None,
    to_date: str | None = None,
) -> pd.DataFrame:
    if "obs_date" not in df.columns:
        return df
    # as-is: 파싱 불가 from/to 문자열 → pandas 비교 예외 → 500 (2026-07-09 점검, 전 엔드포인트 공통)
    # to-be: 사전 검증 후 422 반환
    for label, value in (("from", from_date), ("to", to_date)):
        if value:
            try:
                pd.Timestamp(value)
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=422, detail=f"invalid {label} date: {value!r} (YYYY-MM-DD)"
                )
    if from_date:
        df = df[df["obs_date"] >= from_date]
    if to_date:
        df = df[df["obs_date"] <= to_date]
    return df.sort_values("obs_date")


_DEFAULT_RECORD_COLUMNS = [
    "obs_date", "commodity", "metric", "value", "unit", "source", "report_date",
]


def _to_records(
    df: pd.DataFrame, columns: list[str] | None = None
) -> list[dict[str, Any]]:
    # as-is: fieldwork 엔드포인트가 날짜 직렬화 로직을 복제 (2026-07-09 점검)
    # to-be: columns 파라미터화로 단일 직렬화 경로 공유
    columns = columns or _DEFAULT_RECORD_COLUMNS
    available = [c for c in columns if c in df.columns]
    result = df[available].copy()
    for col in result.select_dtypes(include=["datetime64"]).columns:
        result[col] = result[col].dt.strftime("%Y-%m-%d")
    return result.to_dict("records")


@router.get("/grain/fieldwork")
async def grain_fieldwork(
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    state: str | None = Query(None, description="주 코드 (예: IA). 생략 시 전체"),
    backend: DataBackend = Depends(get_data_backend),
) -> list[dict[str, Any]]:
    """주(state)별 노동 가능 일수 (FIELDWORK — DAYS SUITABLE, days/week).

    QuickStats fieldwork_days 프로파일 데이터. obs_date는 해당 주(week)의 월요일.
    predict-models TB2 v2가 WWCB 지도 추출값의 자동 대조 정답으로 사용.
    """
    # as-is: 전 소스 parquet 로드 후 필터 + 직렬화 복제 (2026-07-09 점검)
    # to-be: quickstats.parquet만 로드(FIELDWORK 유일 소스) + _to_records 공유
    try:
        df = backend.read_parquet("normalized/structured/quickstats.parquet")
    except Exception:
        return []
    if df.empty:
        return []
    df = df[(df["commodity"] == "FIELDWORK")
            & df["metric"].str.contains("days_week", na=False)]
    if state:
        df = df[df["region"] == state.upper()]
    df = _filter_by_date(df, from_date, to_date)
    return _to_records(
        df, columns=["obs_date", "region", "metric", "value", "unit", "report_date"]
    )


@router.get("/grain/prices")
async def grain_prices(
    commodity: str = Query(..., description="corn, soybeans, or wheat"),
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    backend: DataBackend = Depends(get_data_backend),
) -> list[dict[str, Any]]:
    """가격 계열 지표 (price_received, price_spread, loan_rate 등).

    전체 정규화 parquet에서 price 카테고리 metric을 commodity/기간으로
    필터링해 반환. from/to는 YYYY-MM-DD.
    """
    df = _load_all_grain(backend)
    if df.empty:
        return []
    df = _filter_by_commodity(df, commodity)
    df = _filter_by_metric_category(df, "price")
    df = _filter_by_date(df, from_date, to_date)
    return _to_records(df)


@router.get("/grain/supply")
async def grain_supply(
    commodity: str = Query(...),
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    backend: DataBackend = Depends(get_data_backend),
) -> list[dict[str, Any]]:
    """수급 계열 지표 (production, total_supply, imports, domestic_consumption).

    WASDE/PSD/QuickStats 등 정규화 데이터에서 supply 카테고리 metric을 반환.
    """
    df = _load_all_grain(backend)
    if df.empty:
        return []
    df = _filter_by_commodity(df, commodity)
    df = _filter_by_metric_category(df, "supply")
    df = _filter_by_date(df, from_date, to_date)
    return _to_records(df)


@router.get("/grain/inventory")
async def grain_inventory(
    commodity: str = Query(...),
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    backend: DataBackend = Depends(get_data_backend),
) -> list[dict[str, Any]]:
    """재고 계열 지표 (beginning_stocks, ending_stocks)."""
    df = _load_all_grain(backend)
    if df.empty:
        return []
    df = _filter_by_commodity(df, commodity)
    df = _filter_by_metric_category(df, "stock")
    df = _filter_by_date(df, from_date, to_date)
    return _to_records(df)


@router.get("/gtr/indices")
async def gtr_indices(
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    backend: DataBackend = Depends(get_data_backend),
) -> list[dict[str, Any]]:
    """GTR weekly transportation cost index data (Table 1)."""
    files = backend.list_files("normalized/structured", "*gtr*.parquet")
    if not files:
        return []

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
    combined = combined[combined["metric"].isin(GTR_INDEX_METRICS)]

    if "obs_date" in combined.columns:
        combined["obs_date"] = pd.to_datetime(combined["obs_date"], errors="coerce")
        combined = _filter_by_date(combined, from_date, to_date)

    combined["metric_label"] = combined["metric"].map(GTR_METRIC_LABELS)

    columns = ["obs_date", "commodity", "metric", "metric_label", "value", "unit", "source", "report_date"]
    available = [c for c in columns if c in combined.columns]
    result = combined[available].copy()
    for col in result.select_dtypes(include=["datetime64"]).columns:
        result[col] = result[col].dt.strftime("%Y-%m-%d")
    return result.to_dict("records")


@router.get("/grain/available")
async def grain_available(
    backend: DataBackend = Depends(get_data_backend),
) -> dict[str, Any]:
    """Return available data categories per commodity and date ranges."""
    df = _load_all_grain(backend)
    if df.empty:
        return {"commodities": {}, "gtr": False}

    result: dict[str, Any] = {"commodities": {}, "gtr": False}

    for commodity_label, commodity_code in {"corn": "CORN", "soybeans": "SOYBEAN", "wheat": "WHEAT"}.items():
        cdf = df[df["commodity"] == commodity_code]
        if cdf.empty:
            result["commodities"][commodity_label] = {"has_price": False, "has_supply": False, "has_stock": False, "date_range": None}
            continue

        categories: dict[str, bool] = {}
        for cat, patterns in METRIC_CATEGORIES.items():
            mask = pd.Series(False, index=cdf.index)
            for p in patterns:
                mask |= cdf["metric"].str.contains(p, case=False, na=False)
            categories[f"has_{cat}"] = bool(mask.any())

        date_min = cdf["obs_date"].min()
        date_max = cdf["obs_date"].max()
        date_range = None
        if pd.notna(date_min) and pd.notna(date_max):
            date_range = [str(date_min.date()), str(date_max.date())]

        result["commodities"][commodity_label] = {**categories, "date_range": date_range}

    gtr_files = backend.list_files("normalized/structured", "*gtr*.parquet")
    result["gtr"] = len(gtr_files) > 0

    return result
