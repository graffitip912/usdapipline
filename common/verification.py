"""Verification history, change requests, and user reviews.

Ontology entities for AC-3 (data verification + failure history)
and AC-6 (change request loop). Storage via JSONL files under
data/meta/verification/ through DataBackend.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from common.data_access import DataBackend, get_backend

log = logging.getLogger(__name__)

_VERIFICATION_DIR = "meta/verification"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Pydantic models — ontology entities
# ---------------------------------------------------------------------------

class VerificationHistory(BaseModel):
    history_id: str = Field(default_factory=_uuid)
    source: str
    failed_at: str = Field(default_factory=_now_iso)
    failure_reason: str
    as_is: dict[str, Any] = Field(default_factory=dict)
    to_be: dict[str, Any] | None = None
    resolved_at: str | None = None
    resolution_method: str = ""
    linked_change_request: str | None = None


class ChangeRequest(BaseModel):
    request_id: str = Field(default_factory=_uuid)
    requested_by: str = "user"
    requested_at: str = Field(default_factory=_now_iso)
    target_source: str
    change_type: Literal["method", "content", "schema", "schedule"]
    description: str
    status: Literal["pending", "applied", "verified", "rejected"] = "pending"
    linked_verification: str | None = None
    resolved_at: str | None = None


class UserReview(BaseModel):
    review_id: str = Field(default_factory=_uuid)
    source: str
    reviewed_at: str = Field(default_factory=_now_iso)
    reviewer: str = "user"
    auto_validation_passed: bool
    sample_summary: dict[str, Any] = Field(default_factory=dict)
    user_verdict: Literal["approved", "change_requested", "rejected"]
    remarks: str = ""
    linked_change_request: str | None = None


# ---------------------------------------------------------------------------
# VerificationStore — JSONL-backed persistence
# ---------------------------------------------------------------------------

class VerificationStore:
    """Read/write verification entities via DataBackend."""

    _HISTORY_FILE = f"{_VERIFICATION_DIR}/verification_history.jsonl"
    _CR_FILE = f"{_VERIFICATION_DIR}/change_requests.jsonl"
    _REVIEW_FILE = f"{_VERIFICATION_DIR}/user_reviews.jsonl"

    def __init__(self, backend: DataBackend | None = None):
        self._backend = backend or get_backend()

    # -- low-level JSONL helpers ------------------------------------------

    def _read_jsonl(self, rel_path: str) -> list[dict[str, Any]]:
        path = Path(self._backend.resolve_path(rel_path))
        if not path.exists():
            return []
        results: list[dict[str, Any]] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError:
                        log.warning("Skipping malformed JSONL line in %s", rel_path)
        return results

    def _append_jsonl(self, rel_path: str, record: dict[str, Any]) -> None:
        path = Path(self._backend.resolve_path(rel_path))
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def _rewrite_jsonl(self, rel_path: str, records: list[dict[str, Any]]) -> None:
        path = Path(self._backend.resolve_path(rel_path))
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    # -- VerificationHistory ----------------------------------------------

    def list_history(self, source: str | None = None) -> list[VerificationHistory]:
        rows = self._read_jsonl(self._HISTORY_FILE)
        if source:
            rows = [r for r in rows if r.get("source") == source]
        return [VerificationHistory(**r) for r in rows]

    def add_history(self, entry: VerificationHistory) -> None:
        self._append_jsonl(self._HISTORY_FILE, entry.model_dump())
        log.info("Verification failure recorded: source=%s reason=%s",
                 entry.source, entry.failure_reason[:80])

    def update_history(
        self,
        history_id: str,
        to_be: dict[str, Any],
        resolved_at: str | None = None,
        resolution_method: str = "",
    ) -> bool:
        rows = self._read_jsonl(self._HISTORY_FILE)
        updated = False
        for row in rows:
            if row.get("history_id") == history_id:
                row["to_be"] = to_be
                row["resolved_at"] = resolved_at or _now_iso()
                row["resolution_method"] = resolution_method
                updated = True
                break
        if updated:
            self._rewrite_jsonl(self._HISTORY_FILE, rows)
        return updated

    # -- ChangeRequest ----------------------------------------------------

    def list_change_requests(
        self,
        source: str | None = None,
        status: str | None = None,
    ) -> list[ChangeRequest]:
        rows = self._read_jsonl(self._CR_FILE)
        if source:
            rows = [r for r in rows if r.get("target_source") == source]
        if status:
            rows = [r for r in rows if r.get("status") == status]
        return [ChangeRequest(**r) for r in rows]

    def add_change_request(self, cr: ChangeRequest) -> None:
        self._append_jsonl(self._CR_FILE, cr.model_dump())
        log.info("Change request created: id=%s source=%s type=%s",
                 cr.request_id, cr.target_source, cr.change_type)

    def update_change_request(
        self,
        request_id: str,
        status: str | None = None,
        linked_verification: str | None = None,
        resolved_at: str | None = None,
    ) -> bool:
        rows = self._read_jsonl(self._CR_FILE)
        updated = False
        for row in rows:
            if row.get("request_id") == request_id:
                if status:
                    row["status"] = status
                if linked_verification:
                    row["linked_verification"] = linked_verification
                if resolved_at or status in ("verified", "rejected"):
                    row["resolved_at"] = resolved_at or _now_iso()
                updated = True
                break
        if updated:
            self._rewrite_jsonl(self._CR_FILE, rows)
        return updated

    # -- UserReview -------------------------------------------------------

    def list_reviews(self, source: str | None = None) -> list[UserReview]:
        rows = self._read_jsonl(self._REVIEW_FILE)
        if source:
            rows = [r for r in rows if r.get("source") == source]
        return [UserReview(**r) for r in rows]

    def add_review(self, review: UserReview) -> None:
        self._append_jsonl(self._REVIEW_FILE, review.model_dump())
        log.info("User review recorded: source=%s verdict=%s",
                 review.source, review.user_verdict)

    # -- Composite queries ------------------------------------------------

    def get_source_verification_status(self, source: str) -> dict[str, Any]:
        reviews = self.list_reviews(source)
        open_crs = self.list_change_requests(source=source, status="pending") + \
                   self.list_change_requests(source=source, status="applied")
        history = self.list_history(source)

        last_review = reviews[-1] if reviews else None
        unresolved = [h for h in history if not h.resolved_at]
        last_failure = unresolved[-1] if unresolved else None

        if last_review and last_review.user_verdict == "rejected":
            verification_status = "rejected"
        elif last_review and last_review.user_verdict == "approved" and not open_crs:
            verification_status = "approved"
        elif open_crs:
            verification_status = "change_requested"
        elif last_review:
            verification_status = "pending_review"
        else:
            verification_status = "not_verified"

        return {
            "verification_status": verification_status,
            "last_review_verdict": last_review.user_verdict if last_review else None,
            "last_review_at": last_review.reviewed_at if last_review else None,
            "last_verification_failure": last_failure.failure_reason if last_failure else None,
            "open_change_requests": len(open_crs),
            "total_history_entries": len(history),
            "unresolved_failures": len(unresolved),
        }
