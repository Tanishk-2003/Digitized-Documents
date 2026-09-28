"""Document ingestion, job tracking, and retrieval routes (IMPLEMENTATION_PLAN.md P9)."""
from __future__ import annotations

from pathlib import Path
import shutil
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from pharma_di.config import REPO_ROOT
from pharma_di.export.excel import export_final_output_to_excel, export_to_excel
from pharma_di.persist.db import get_session
from pharma_di.persist.models import Document, ReviewRecord, Transaction
from pharma_di.persist.repository import load_canonical_rows, load_final_output_rows
from pharma_di.schemas.api import (
    DocumentDetailResponse,
    DocumentSummaryResponse,
    JobResponse,
    JobStatus,
    OverviewResponse,
)
from pharma_di.schemas.final_output import FinalStockSaleRow
from pharma_di.workers.jobs import default_job_manager

router = APIRouter(prefix="/api", tags=["documents"])

_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".pdf"}


def get_db():
    session = get_session()
    try:
        yield session
    finally:
        session.close()


@router.post(
    "/documents/upload",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload document for asynchronous pipeline processing",
)
async def upload_document(
    file: UploadFile = File(...),
    debug: bool = Query(default=False, description="Enable verbose pipeline debug trace"),
) -> JobResponse:
    ext = Path(file.filename or "upload.jpg").suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{ext}'. Allowed extensions: {', '.join(_ALLOWED_EXTENSIONS)}",
        )

    upload_dir = REPO_ROOT / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename_clean = f"{Path(file.filename or 'doc').stem}_{uuid.uuid4().hex[:6]}{ext}"
    dest_path = upload_dir / filename_clean

    with dest_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    job = default_job_manager.submit_job(dest_path, debug=debug)
    return job


@router.get(
    "/jobs/{job_id}",
    response_model=JobResponse,
    summary="Get background processing status of a document job",
)
async def get_job_status(job_id: str) -> JobResponse:
    job = default_job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found")
    return job


@router.get(
    "/jobs",
    response_model=list[JobResponse],
    summary="List all submitted processing jobs",
)
async def list_jobs() -> list[JobResponse]:
    return default_job_manager.list_jobs()


@router.get(
    "/documents",
    response_model=list[DocumentSummaryResponse],
    summary="List all persisted documents",
)
async def list_documents(session: Session = Depends(get_db)) -> list[DocumentSummaryResponse]:
    documents = session.query(Document).order_by(Document.created_at.desc()).all()
    summaries: list[DocumentSummaryResponse] = []

    for doc in documents:
        total_rows = session.query(Transaction).filter(Transaction.document_id == doc.id).count()
        needs_review_count = (
            session.query(ReviewRecord)
            .join(Transaction)
            .filter(Transaction.document_id == doc.id, ReviewRecord.review_status == "needs_review")
            .count()
        )
        summaries.append(
            DocumentSummaryResponse(
                document_id=doc.id,
                distributor_id=doc.distributor_id,
                distributor_name=doc.distributor_name,
                company_name=doc.company_name,
                statement_from=str(doc.statement_from) if doc.statement_from else None,
                statement_to=str(doc.statement_to) if doc.statement_to else None,
                document_type=doc.document_type,
                source_file=doc.source_file,
                page_number=doc.page_number,
                page_count=doc.page_count,
                row_count=total_rows,
                needs_review_count=needs_review_count,
            )
        )
    return summaries


def _statement_bucket(doc: DocumentSummaryResponse) -> str:
    """Mirrors ui/src/statementLanguage.js::deriveStatementStatus exactly —
    kept in sync deliberately (a Python backend and a JS frontend can't
    literally share the function, but every screen showing a statement's
    status, including this aggregate, must agree on what "exception" vs.
    "review" vs. "approved" means for the same underlying document)."""
    if not doc.distributor_name or doc.row_count == 0:
        return "exception"
    if doc.needs_review_count > 0:
        return "review"
    return "approved"


@router.get(
    "/overview",
    response_model=OverviewResponse,
    summary="Aggregate counts and recent statements for the Overview page",
)
async def get_overview(session: Session = Depends(get_db)) -> OverviewResponse:
    """UI-UX-Implementation.md Phase B.1. Reuses list_documents's own
    per-document classification (not a second, parallel query) so this
    never drifts from what the Statements/Review Required pages show for
    the same documents."""
    documents = await list_documents(session)

    counts = {"exception": 0, "review": 0, "approved": 0}
    for doc in documents:
        counts[_statement_bucket(doc)] += 1

    processing = sum(
        1 for j in default_job_manager.list_jobs() if j.status in (JobStatus.queued, JobStatus.processing)
    )

    return OverviewResponse(
        received=len(documents),
        processing=processing,
        review_required=counts["review"],
        approved=counts["approved"],
        exceptions=counts["exception"],
        recent=documents[:5],
    )


@router.get(
    "/documents/{document_id}",
    response_model=DocumentDetailResponse,
    summary="Get canonical document records and all transaction rows",
)
async def get_document_detail(
    document_id: str,
    session: Session = Depends(get_db),
) -> DocumentDetailResponse:
    doc = session.get(Document, document_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found in database",
        )

    canonical_rows = load_canonical_rows(session, document_id=document_id)
    needs_review_count = sum(1 for r in canonical_rows if r.get("review_status") == "needs_review")

    summary = DocumentSummaryResponse(
        document_id=doc.id,
        distributor_id=doc.distributor_id,
        distributor_name=doc.distributor_name,
        company_name=doc.company_name,
        statement_from=str(doc.statement_from) if doc.statement_from else None,
        statement_to=str(doc.statement_to) if doc.statement_to else None,
        document_type=doc.document_type,
        source_file=doc.source_file,
        page_number=doc.page_number,
        page_count=doc.page_count,
        row_count=len(canonical_rows),
        needs_review_count=needs_review_count,
    )

    return DocumentDetailResponse(document=summary, canonical_rows=canonical_rows)


@router.get(
    "/final-output",
    response_model=list[FinalStockSaleRow],
    summary="List the uniform 12-column final output table, optionally filtered to one document",
)
async def list_final_output(
    document_id: str | None = Query(default=None, description="Restrict to one document_id"),
    session: Session = Depends(get_db),
) -> list[FinalStockSaleRow]:
    """P16: the JSON counterpart to /export/final below — that route returns
    an .xlsx file; this one returns the same rows as data, for the UI's
    sortable/filterable final-output table view."""
    rows = load_final_output_rows(session, document_id=document_id)
    return [FinalStockSaleRow(**row) for row in rows]


@router.get(
    "/documents/{document_id}/export/excel",
    summary="Download Excel spreadsheet matching the canonical Stock & Sale schema",
)
async def export_document_excel(
    document_id: str,
    session: Session = Depends(get_db),
) -> FileResponse:
    doc = session.get(Document, document_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found in database",
        )

    out_dir = REPO_ROOT / "data" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{document_id}.xlsx"

    export_to_excel(session, out_file, document_id=document_id)

    return FileResponse(
        path=out_file,
        filename=f"{document_id}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get(
    "/documents/{document_id}/export/final",
    summary="Download the uniform 12-column final output table for one document",
)
async def export_document_final_output(
    document_id: str,
    session: Session = Depends(get_db),
) -> FileResponse:
    """P14: the always-uniform reporting export — same 12 columns
    regardless of the source document's original layout (schemas/
    final_output.py::FinalStockSaleRow). Separate route from /export/excel
    above: that one exports the full, detailed canonical schema this
    project's validation/review pipeline depends on; this one exports the
    deliberately narrower view built from it."""
    doc = session.get(Document, document_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found in database",
        )

    out_dir = REPO_ROOT / "data" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{document_id}-final.xlsx"

    export_final_output_to_excel(session, out_file, document_id=document_id)

    return FileResponse(
        path=out_file,
        filename=f"{document_id}-final.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get(
    "/export/final",
    summary="Download the uniform 12-column final output table for every persisted document",
)
async def export_all_final_output(session: Session = Depends(get_db)) -> FileResponse:
    """The bulk counterpart to /documents/{id}/export/final — every
    document currently in the database, not just one pipeline run's."""
    out_dir = REPO_ROOT / "data" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "final_output_all.xlsx"

    export_final_output_to_excel(session, out_file, document_id=None)

    return FileResponse(
        path=out_file,
        filename="final_output_all.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
