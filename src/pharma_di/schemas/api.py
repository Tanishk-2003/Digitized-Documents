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


class DocumentDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: DocumentSummaryResponse
    canonical_rows: list[dict[str, Any]] = Field(default_factory=list)


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
    distinct_review_reasons: list[str] = Field(default_factory=list)


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
