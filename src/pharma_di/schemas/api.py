"""API response and request schemas (IMPLEMENTATION_PLAN.md P9).
Pydantic v2 schemas for document upload, job status polling, review queue,
and correction operations.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from pharma_di.schemas.canonical import ReviewStatus
from pharma_di.schemas.validation import RuleId


class JobStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class JobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    document_id: str
    source_file: str
    status: JobStatus = JobStatus.queued
    progress_stage: str | None = None
    trace: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    routed_to_review: bool | None = None
    persisted: bool | None = None


class DocumentSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    distributor_id: str | None = None
    distributor_name: str | None = None
    company_name: str | None = None
    statement_from: str | None = None
    statement_to: str | None = None
    document_type: str | None = None
    source_file: str | None = None
    page_number: int | None = 1
    page_count: int | None = 1
    row_count: int = 0
    needs_review_count: int = 0


class OverviewResponse(BaseModel):
    """UI-UX-Implementation.md Phase B.1: aggregate counts for the Overview
    page — a read-only rollup over the same data list_documents already
    exposes per-document, not a new source of truth. `received` is every
    document ever persisted (no calendar-period scoping — no real single
    period applies across documents spanning several different statement
    periods in this dataset today; a true period-scoped view is closer to
    the brief's own explicitly-deferred "analytics" territory than this
    pass's "reframe the existing flow" scope). `exceptions` (no identified
    distributor, or zero rows) is its own bucket, not folded into
    review_required, matching the Statements/Review Required pages'
    deriveStatementStatus classification exactly."""

    model_config = ConfigDict(extra="forbid")

    received: int = 0
    processing: int = 0
    review_required: int = 0
    approved: int = 0
    exceptions: int = 0
    recent: list[DocumentSummaryResponse] = Field(default_factory=list)


class DocumentDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: DocumentSummaryResponse
    canonical_rows: list[dict[str, Any]] = Field(default_factory=list)


class ReviewReasonSummary(BaseModel):
    """UI-UX-Implementation.md Phase A.2: one flagged document's review
    reasons grouped by rule (R1-R7), replacing the old
    ReviewQueueItem.distinct_review_reasons (a deduplicated set of raw,
    pre-formatted sentences — e.g. "1 field(s) below 0.85: worst is
    dump_quantity at 0.83" — with no way for a UI to tell rules apart or
    phrase them in business language). Counting and grouping by rule_id is
    a structural aggregation, not a language choice, so it stays here in
    the backend; the friendly label PER rule_id (e.g. "quantity values are
    uncertain") is a UI-copy concern and lives in the frontend instead,
    keeping `sample_detail` available for anyone who wants the original
    technical wording."""

    model_config = ConfigDict(extra="forbid")

    rule_id: RuleId
    count: int
    sample_detail: str


class ReviewQueueItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    distributor_name: str | None = None
    company_name: str | None = None
    statement_period: str | None = None
    document_type: str | None = None
    source_file: str | None = None
    total_rows: int = 0
    flagged_rows_count: int = 0
    review_reason_summary: list[ReviewReasonSummary] = Field(default_factory=list)


class ApproveDocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str | None = None


class ApproveDocumentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    status: str = "approved"
    updated_rows: int = 0


class ColumnMappingCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_header: str
    canonical_field: str


class CorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column_mappings: list[ColumnMappingCorrection] = Field(default_factory=list)
    row_corrections: list[dict[str, Any]] = Field(default_factory=list)
    notes: str | None = None


class CorrectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    status: str = "corrected"
    promoted_mappings: list[str] = Field(default_factory=list)
    updated_rows: int = 0
