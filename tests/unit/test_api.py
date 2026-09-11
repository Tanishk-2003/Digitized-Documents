"""Unit and integration tests for the FastAPI service and background worker (IMPLEMENTATION_PLAN.md P9)."""
from __future__ import annotations

import io
import time
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from pharma_di.api.app import create_app
from pharma_di.api.routes_documents import get_db
from pharma_di.config import clear_config_cache, load_column_mappings
from pharma_di.persist.db import get_engine
from pharma_di.persist.models import Base, Correction, Document, Product, ReviewRecord, Transaction
from pharma_di.persist.repository import save_document
from pharma_di.schemas.canonical import (
    CanonicalRow,
    DocumentRecord,
    DocumentType,
    ProductRecord,
    ReviewStatus,
    TransactionRecord,
)
from pharma_di.schemas.validation import RowValidationResult
from pharma_di.workers.jobs import JobManager, JobStatus


@pytest.fixture()
def test_db_session(tmp_path) -> Session:
    engine = get_engine(f"sqlite:///{tmp_path / 'api_test.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture()
def client(test_db_session: Session) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: test_db_session
    with TestClient(app) as test_client:
        yield test_client


def _seed_sample_doc(session: Session, document_id="doc6-api-test", review_status=ReviewStatus.needs_review):
    document_record = DocumentRecord(
        document_id=document_id,
        distributor_id="marg-pharma",
        distributor_name="Marg Pharma Distributor",
        company_name="Zorvia Healthcare",
        document_type=DocumentType.product_level,
        source_file="doc6.jpg",
        page_number=1,
        page_count=1,
    )
    products = [ProductRecord(product_name_raw="COSKLOT REG TAB.", hsn_code="30049099", rate=408.86)]
    transactions = [TransactionRecord(opening_qty=16.0, opening_value=6541.76)]
    rows = [
        CanonicalRow(
            document_type=DocumentType.product_level,
            distributor_id="marg-pharma",
            distributor_name="Marg Pharma Distributor",
            company_name="Zorvia Healthcare",
            product_name_raw="COSKLOT REG TAB.",
            hsn_code="30049099",
            rate=408.86,
            opening_quantity=16.0,
            opening_value=6541.76,
            source_document="doc6.jpg",
            page_number=1,
            extraction_confidence={"opening_quantity": 0.98},
            review_status=review_status,
            review_reasons=["r2_totals_discrepancy"] if review_status == ReviewStatus.needs_review else [],
        )
    ]
    validation_results = [RowValidationResult(document_id=document_id, row_index=0, rule_results=[])]
    save_document(session, document_record, products, transactions, rows, validation_results)


def test_health_check_endpoint(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "pharma-di-api"


def test_root_endpoint(client: TestClient):
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert "endpoints" in data
    assert "/api/documents/upload" in data["endpoints"]


from PIL import Image


def test_job_manager_lifecycle(tmp_path: Path):
    manager = JobManager(max_workers=1)
    dummy_file = tmp_path / "test.jpg"
    Image.new("RGB", (100, 100), color=(255, 255, 255)).save(dummy_file, format="JPEG")

    job = manager.submit_job(dummy_file, document_id="test-doc-123")
    assert job.job_id.startswith("job-")
    assert job.document_id == "test-doc-123"

    retrieved = manager.get_job(job.job_id)
    assert retrieved is not None
    assert retrieved.job_id == job.job_id

    jobs = manager.list_jobs()
    assert any(j.job_id == job.job_id for j in jobs)

    manager.shutdown(wait=False)


def test_upload_document_returns_accepted(client: TestClient, tmp_path: Path):
    img_buf = io.BytesIO()
    Image.new("RGB", (100, 100), color=(255, 255, 255)).save(img_buf, format="JPEG")
    img_buf.seek(0)
    files = {"file": ("test_doc.jpg", img_buf, "image/jpeg")}

    resp = client.post("/api/documents/upload", files=files)
    assert resp.status_code == 202
    data = resp.json()
    assert "job_id" in data
    assert data["status"] in ("queued", "processing", "completed")
    assert data["source_file"].endswith(".jpg")


def test_upload_invalid_file_extension_rejected(client: TestClient):
    files = {"file": ("malicious.exe", io.BytesIO(b"bad content"), "application/octet-stream")}
    resp = client.post("/api/documents/upload", files=files)
    assert resp.status_code == 400
    assert "Unsupported file format" in resp.json()["detail"]


def test_get_job_status_not_found(client: TestClient):
    resp = client.get("/api/jobs/job-nonexistent")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


def test_list_documents(client: TestClient, test_db_session: Session):
    _seed_sample_doc(test_db_session, document_id="doc-list-1")
    _seed_sample_doc(test_db_session, document_id="doc-list-2")

    resp = client.get("/api/documents")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2
    doc_ids = [d["document_id"] for d in data]
    assert "doc-list-1" in doc_ids
    assert "doc-list-2" in doc_ids


def test_get_document_detail_success_and_not_found(client: TestClient, test_db_session: Session):
    _seed_sample_doc(test_db_session, document_id="doc-detail-1")

    resp = client.get("/api/documents/doc-detail-1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["document"]["document_id"] == "doc-detail-1"
    assert data["document"]["distributor_name"] == "Marg Pharma Distributor"
    assert len(data["canonical_rows"]) == 1
    assert data["canonical_rows"][0]["product_name_raw"] == "COSKLOT REG TAB."

    resp404 = client.get("/api/documents/doc-nonexistent")
    assert resp404.status_code == 404


def test_export_document_excel_endpoint(client: TestClient, test_db_session: Session):
    _seed_sample_doc(test_db_session, document_id="doc-excel-1")

    resp = client.get("/api/documents/doc-excel-1/export/excel")
    assert resp.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in resp.headers["content-type"]
    assert len(resp.content) > 0


def test_review_queue_endpoint(client: TestClient, test_db_session: Session):
    _seed_sample_doc(test_db_session, document_id="doc-review-1", review_status=ReviewStatus.needs_review)

    resp = client.get("/api/review-queue")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    matching = next((item for item in data if item["document_id"] == "doc-review-1"), None)
    assert matching is not None
    assert matching["flagged_rows_count"] == 1
    assert "r2_totals_discrepancy" in matching["distinct_review_reasons"]


def test_approve_document_endpoint(client: TestClient, test_db_session: Session):
    _seed_sample_doc(test_db_session, document_id="doc-approve-1", review_status=ReviewStatus.needs_review)

    resp = client.post("/api/review/doc-approve-1/approve", json={"notes": "Approved by QC manager"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "approved"
    assert data["updated_rows"] == 1

    # Verify review record in DB updated
    rev = test_db_session.query(ReviewRecord).join(Transaction).filter(Transaction.document_id == "doc-approve-1").first()
    assert rev.review_status == "approved"


def test_correct_document_endpoint(client: TestClient, test_db_session: Session, tmp_path: Path):
    _seed_sample_doc(test_db_session, document_id="doc-correct-1", review_status=ReviewStatus.needs_review)
    txn = test_db_session.query(Transaction).filter(Transaction.document_id == "doc-correct-1").first()

    payload = {
        "column_mappings": [{"source_header": "NEW_CUSTOM_HDR", "canonical_field": "opening_quantity"}],
        "row_corrections": [
            {
                "transaction_id": txn.id,
                "field_name": "opening_quantity",
                "original_value": "16.0",
                "corrected_value": "20.0",
            }
        ],
        "notes": "Fixed OCR mistyped opening quantity",
    }

    resp = client.post("/api/review/doc-correct-1/correct", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "corrected"
    assert data["updated_rows"] == 1
    assert any("NEW_CUSTOM_HDR" in m for m in data["promoted_mappings"])

    # Check Correction record in DB
    corrs = test_db_session.query(Correction).filter(Correction.transaction_id == txn.id).all()
    assert len(corrs) == 1
    assert corrs[0].field_name == "opening_quantity"
    assert corrs[0].corrected_value == "20.0"

    # Check updated review status
    rev = test_db_session.query(ReviewRecord).filter(ReviewRecord.transaction_id == txn.id).first()
    assert rev.review_status == "human_corrected"

    # Verify column mapping alias was promoted
    mappings = load_column_mappings()
    assert "new_custom_hdr" in [a.lower() for a in mappings.get("opening_quantity", {}).get("aliases", [])]
