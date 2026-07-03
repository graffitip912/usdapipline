"""Verification, change request, and user review API endpoints.

Covers AC-3 (data verification + user confirmation gate),
AC-4 (monitoring with verification status), and
AC-6 (change request loop).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from api.deps import get_data_backend
from collector.run import run_source, SOURCES
from common.harness_config import get_change_request_policy, get_verification_config
from common.schema import validate_with_report
from common.verification import (
    ChangeRequest,
    UserReview,
    VerificationStore,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/verification", tags=["verification"])


def _get_store() -> VerificationStore:
    return VerificationStore(get_data_backend())


# ---------------------------------------------------------------------------
# Verification history
# ---------------------------------------------------------------------------

@router.get("/history")
async def list_verification_history(source: str | None = None) -> list[dict[str, Any]]:
    """검증 실패 이력 목록 (as-is→to-be 추적, AC-5).

    각 항목은 failure_reason, as_is/to_be 스냅샷, resolved_at,
    resolution_method를 포함. source(실행 키)로 필터 가능.
    """
    store = _get_store()
    entries = store.list_history(source)
    return [e.model_dump() for e in entries]


@router.get("/history/{history_id}")
async def get_verification_history(history_id: str) -> dict[str, Any]:
    """검증 실패 이력 단건 조회 (history_id는 12자리 hex)."""
    store = _get_store()
    entries = store.list_history()
    for e in entries:
        if e.history_id == history_id:
            return e.model_dump()
    raise HTTPException(status_code=404, detail="History entry not found")


class ResolveHistoryBody(BaseModel):
    to_be: dict[str, Any]
    resolution_method: str = ""


@router.put("/history/{history_id}/resolve")
async def resolve_verification_history(
    history_id: str, body: ResolveHistoryBody,
) -> dict[str, Any]:
    """검증 실패 이력을 해결 처리 (as-is→to-be 마감).

    to_be에 해결 후 상태를 기록하고 resolved_at을 스탬프.
    시스템 경로로 해결 이력을 남기기 위한 엔드포인트 (감사 R3).
    """
    if not body.to_be:
        raise HTTPException(400, "to_be must not be empty")
    store = _get_store()
    ok = store.update_history(
        history_id,
        to_be=body.to_be,
        resolution_method=body.resolution_method,
    )
    if not ok:
        raise HTTPException(404, "History entry not found")
    return {"status": "resolved", "history_id": history_id}


# ---------------------------------------------------------------------------
# User reviews (AC-3: user confirmation gate)
# ---------------------------------------------------------------------------

class ReviewRequest(BaseModel):
    source: str
    user_verdict: str  # "approved" | "change_requested" | "rejected"
    remarks: str = ""
    linked_change_request: str | None = None


@router.post("/review")
async def submit_review(body: ReviewRequest) -> dict[str, Any]:
    """사용자 데이터 검증 리뷰 제출 (AC-3 승인 게이트).

    verdict가 approved면 해당 소스의 검증이 완료 상태로 전환.
    change_requested면 linked_change_request 필수. 자동 스키마 검증
    결과(auto_validation_passed)를 함께 기록.
    """
    if body.user_verdict not in ("approved", "change_requested", "rejected"):
        raise HTTPException(400, "user_verdict must be: approved, change_requested, rejected")
    if body.user_verdict == "change_requested" and not body.linked_change_request:
        raise HTTPException(400, "linked_change_request required when verdict is change_requested")

    store = _get_store()
    backend = get_data_backend()

    auto_passed = False
    norm_path = f"normalized/structured/{body.source}.parquet"
    if backend.exists(norm_path):
        try:
            df = backend.read_parquet(norm_path)
            _, report = validate_with_report(df, body.source)
            auto_passed = report["schema_pass"]
        except Exception:
            pass

    review = UserReview(
        source=body.source,
        auto_validation_passed=auto_passed,
        sample_summary={},
        user_verdict=body.user_verdict,
        remarks=body.remarks,
        linked_change_request=body.linked_change_request,
    )
    store.add_review(review)
    return review.model_dump()


@router.get("/reviews")
async def list_reviews(source: str | None = None) -> list[dict[str, Any]]:
    """사용자 리뷰 기록 목록 (승인/변경요청/거부 이력). source로 필터 가능."""
    store = _get_store()
    reviews = store.list_reviews(source)
    return [r.model_dump() for r in reviews]


# ---------------------------------------------------------------------------
# Source verification summary
# ---------------------------------------------------------------------------

@router.get("/summary/{source}")
async def verification_summary(source: str) -> dict[str, Any]:
    """소스별 검증 상태 요약 — verification_status(approved/change_requested/
    pending_review/rejected/not_verified), 미해결 실패 수, 열린 CR 수."""
    store = _get_store()
    return store.get_source_verification_status(source)


# ---------------------------------------------------------------------------
# Data preview (AC-3: user confirmation support)
# ---------------------------------------------------------------------------

@router.get("/preview/{source}")
async def data_preview(source: str, sample_rows: int | None = None) -> dict[str, Any]:
    """Preview collected data for user verification.

    sample_rows 기본값과 이상치 z-score 임계값은 harness.yaml
    (runtime_rules.verification)에서 읽음.
    """
    v_conf = get_verification_config()
    if sample_rows is None:
        sample_rows = int(v_conf.get("preview_sample_rows", 20))
    z_threshold = float(v_conf.get("anomaly_zscore_threshold", 3.0))

    backend = get_data_backend()
    norm_path = f"normalized/structured/{source}.parquet"

    if not backend.exists(norm_path):
        raise HTTPException(404, f"No normalized data for source: {source}")

    df = backend.read_parquet(norm_path)
    _, report = validate_with_report(df, source)

    # 최신 데이터 우선 — 주기 수집 시 사용자는 최근 갱신분을 확인해야 함
    sort_col = next((c for c in ("report_date", "obs_date") if c in df.columns), None)
    df_view = df.sort_values(sort_col, ascending=False) if sort_col else df
    sample = df_view.head(sample_rows).fillna("").to_dict("records")

    anomalies: list[dict[str, Any]] = []
    for col in df.select_dtypes(include="number").columns:
        series = df[col].dropna()
        if len(series) > 10:
            mean, std = series.mean(), series.std()
            if std > 0:
                z_scores = ((series - mean) / std).abs()
                outliers = z_scores[z_scores > z_threshold]
                for idx in outliers.index[:5]:
                    anomalies.append({
                        "column": col,
                        "index": int(idx),
                        "value": float(df.at[idx, col]),
                        "z_score": round(float(z_scores[idx]), 2),
                    })

    return {
        "source": source,
        "row_count": len(df),
        "column_names": df.columns.tolist(),
        "sample_rows": sample,
        "stats": report.get("sample_stats", {}),
        "schema_validation": report["schema_pass"],
        "anomalies": anomalies[:20],
    }


# ---------------------------------------------------------------------------
# Change requests (AC-6: change request loop)
# ---------------------------------------------------------------------------

class ChangeRequestBody(BaseModel):
    target_source: str
    change_type: str  # "method" | "content" | "schema" | "schedule"
    description: str


@router.post("/change-request")
async def create_change_request(body: ChangeRequestBody) -> dict[str, Any]:
    """수집 변경 요청(CR) 생성 (AC-6 루프의 시작).

    루프: 생성(pending) → apply(applied) → re-collect → verify(verified/rejected).
    change_type: method(수집 방법) | content(내용) | schema | schedule.
    """
    if body.change_type not in ("method", "content", "schema", "schedule"):
        raise HTTPException(400, "change_type must be: method, content, schema, schedule")

    store = _get_store()
    cr = ChangeRequest(
        target_source=body.target_source,
        change_type=body.change_type,
        description=body.description,
    )
    store.add_change_request(cr)
    return cr.model_dump()


@router.get("/change-requests")
async def list_change_requests(
    source: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """변경 요청 목록. source/status(pending|applied|verified|rejected) 필터 가능."""
    store = _get_store()
    crs = store.list_change_requests(source=source, status=status)
    return [cr.model_dump() for cr in crs]


@router.put("/change-request/{request_id}/apply")
async def apply_change_request(request_id: str) -> dict[str, str]:
    """CR을 applied 상태로 전환 — 변경 사항이 코드/설정에 반영되었음을 표시.
    이후 re-collect 호출이 가능해짐."""
    store = _get_store()
    ok = store.update_change_request(request_id, status="applied")
    if not ok:
        raise HTTPException(404, "Change request not found")
    return {"status": "applied", "request_id": request_id}


@router.post("/change-request/{request_id}/re-collect")
async def re_collect(
    request_id: str,
    background_tasks: BackgroundTasks,
    since: int = 2010,
    force: bool = True,
) -> dict[str, str]:
    """applied 상태 CR의 대상 소스를 백그라운드로 재수집.

    harness.yaml의 max_loop_iterations(10) 초과 시 400 — 새 CR을 생성해야 함.
    """
    store = _get_store()
    crs = store.list_change_requests()
    target_cr = None
    for cr in crs:
        if cr.request_id == request_id:
            target_cr = cr
            break
    if not target_cr:
        raise HTTPException(404, "Change request not found")
    if target_cr.status != "applied":
        raise HTTPException(400, "Change request must be in 'applied' status to re-collect")
    if target_cr.target_source not in SOURCES:
        raise HTTPException(400, f"Unknown source: {target_cr.target_source}")

    policy = get_change_request_policy()
    max_iterations = policy["max_loop_iterations"]
    reviews = store.list_reviews(source=target_cr.target_source)
    loop_count = sum(1 for r in reviews if r.linked_change_request == request_id)
    if loop_count >= max_iterations:
        raise HTTPException(
            400,
            f"Change request {request_id} has reached the maximum of "
            f"{max_iterations} loop iterations. Create a new change request "
            f"or request manual override.",
        )

    background_tasks.add_task(run_source, target_cr.target_source, since, force)
    return {"status": "re-collecting", "source": target_cr.target_source, "request_id": request_id}


class VerifyChangeBody(BaseModel):
    user_verdict: str  # "verified" | "rejected"
    remarks: str = ""


@router.put("/change-request/{request_id}/verify")
async def verify_change_request(request_id: str, body: VerifyChangeBody) -> dict[str, Any]:
    """재수집 결과에 대한 사용자 최종 판정 (AC-6 루프의 종결).

    verified면 CR이 종결되고 연동 승인 리뷰가 자동 기록됨. rejected면
    새 CR을 생성해 루프를 다시 돌리거나 skip을 판정.
    """
    if body.user_verdict not in ("verified", "rejected"):
        raise HTTPException(400, "user_verdict must be: verified, rejected")

    store = _get_store()
    ok = store.update_change_request(request_id, status=body.user_verdict)
    if not ok:
        raise HTTPException(404, "Change request not found")

    crs = store.list_change_requests()
    target_cr = None
    for cr in crs:
        if cr.request_id == request_id:
            target_cr = cr
            break

    if target_cr and body.user_verdict == "verified":
        review = UserReview(
            source=target_cr.target_source,
            auto_validation_passed=True,
            user_verdict="approved",
            remarks=f"Change request {request_id} verified: {body.remarks}",
            linked_change_request=request_id,
        )
        store.add_review(review)

    return {"status": body.user_verdict, "request_id": request_id}
