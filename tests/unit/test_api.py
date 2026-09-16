"""Unit and integration tests for the FastAPI service and background worker (IMPLEMENTATION_PLAN.md P9)."""
from __future__ import annotations

import io
import time
from pathlib import Path

import yaml
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from pharma_di.api import routes_review as routes_review_module
from pharma_di.api.app import create_app
from pharma_di.api.routes_documents import get_db
from pharma_di.config import load_settings
from pharma_di.mapping.update import add_column_alias
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
from pharma_di.workers import jobs as jobs_module
from pharma_di.workers.jobs import JobManager, JobStatus


@pytest.fixture()
def test_db_session(tmp_path) -> Session:
    engine = get_engine(f"sqlite:///{tmp_path / 'api_test.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture()
def isolated_column_mappings_path(tmp_path, monkeypatch) -> Path:
    """P11: the real /api/review/{id}/correct route promotes a confirmed
    alias straight into config/column_mappings.yaml (mapping/update.py::
    add_column_alias, called with its default mappings_file=None, which
    resolves to the real repo file). Found this session: with no isolation,
    every test run through this route permanently wrote a fake alias into
    the real, committed dictionary — confirmed two such aliases (
    "new_custom_hdr", "p10_test_hdr") were already sitting in the real file
    as a result. add_column_alias() is imported by name into routes_review.py
    (`from pharma_di.mapping.update import add_column_alias`), so patching
    config.load_settings alone wouldn't reach that call site — monkeypatching
    the name where it's actually called (routes_review_module.add_column_alias)
    to always target this tmp copy is the direct fix, not a `load_settings`
    chase across every module that imports it."""
    real_path = load_settings().resolve_path("column_mappings")
    tmp_mappings_path = tmp_path / "column_mappings.yaml"
    tmp_mappings_path.write_text(real_path.read_text(encoding="utf-8"), encoding="utf-8")

    def _isolated_add_column_alias(canonical_field: str, alias: str, mappings_file=None) -> bool:
        return add_column_alias(canonical_field, alias, mappings_file=tmp_mappings_path)

    monkeypatch.setattr(routes_review_module, "add_column_alias", _isolated_add_column_alias)
    return tmp_mappings_path


@pytest.fixture()
def client(test_db_session: Session, isolated_column_mappings_path: Path) -> TestClient:
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


def test_job_manager_marks_a_completed_run_with_recorded_errors_as_failed(monkeypatch, tmp_path: Path):
    """P16: workers/jobs.py::_run_job used to set job.status to
    JobStatus.completed on EITHER side of a
    `JobStatus.completed if not final_state.errors else JobStatus.completed`
    ternary — a dead branch that could never actually mark a job failed once
    the graph itself ran to completion, no matter what final_state.errors
    held. Verified here by stubbing compiled_graph() so the pipeline itself
    isn't exercised — this is a unit test of JobManager's own status logic,
    not of what makes the real pipeline record an error."""

    class _FakeGraph:
        def invoke(self, state):
            return {"source_file": state.source_file, "document_id": state.document_id, "errors": ["boom"]}

    monkeypatch.setattr(jobs_module, "compiled_graph", lambda: _FakeGraph())

    manager = JobManager(max_workers=1)
    dummy_file = tmp_path / "test.jpg"
    dummy_file.write_bytes(b"not a real image, never reaches OCR since compiled_graph is stubbed")

    job = manager.submit_job(dummy_file, document_id="test-doc-errors")

    deadline = time.time() + 5
    while time.time() < deadline:
        current = manager.get_job(job.job_id)
        if current.status != JobStatus.queued and current.status != JobStatus.processing:
            break
        time.sleep(0.05)

    final = manager.get_job(job.job_id)
    assert final.errors == ["boom"]
    assert final.status == JobStatus.failed

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


def test_export_document_final_output_endpoint(client: TestClient, test_db_session: Session):
    _seed_sample_doc(test_db_session, document_id="doc-final-1")

    resp = client.get("/api/documents/doc-final-1/export/final")
    assert resp.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in resp.headers["content-type"]
    assert len(resp.content) > 0


def test_export_document_final_output_endpoint_404s_for_unknown_document(client: TestClient):
    resp = client.get("/api/documents/does-not-exist/export/final")
    assert resp.status_code == 404


def test_export_all_final_output_endpoint(client: TestClient, test_db_session: Session):
    _seed_sample_doc(test_db_session, document_id="doc-final-a")
    _seed_sample_doc(test_db_session, document_id="doc-final-b")

    resp = client.get("/api/export/final")
    assert resp.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in resp.headers["content-type"]
    assert len(resp.content) > 0


def test_list_final_output_endpoint_returns_all_rows_across_documents(client: TestClient, test_db_session: Session):
    """P16: the JSON counterpart to /export/final — the same rows, as data,
    for the new final-output table view (the export routes only ever
    returned .xlsx files; nothing returned this data as JSON before)."""
    _seed_sample_doc(test_db_session, document_id="doc-list-final-a")
    _seed_sample_doc(test_db_session, document_id="doc-list-final-b")

    resp = client.get("/api/final-output")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert {row["file_name"] for row in data} == {"doc6.jpg"}
    row = data[0]
    assert set(row.keys()) == {
        "id", "stockist_distributor_name", "address", "product_name",
        "opening_qty", "closing_qty", "dump_qty", "scan_date", "file_name",
        "scan_by", "update_by", "updated_on",
    }
    assert row["product_name"] == "COSKLOT REG TAB."
    assert row["opening_qty"] == 16.0


def test_list_final_output_endpoint_filters_by_document_id(client: TestClient, test_db_session: Session):
    _seed_sample_doc(test_db_session, document_id="doc-list-final-c")
    _seed_sample_doc(test_db_session, document_id="doc-list-final-d")

    resp = client.get("/api/final-output", params={"document_id": "doc-list-final-c"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["file_name"] == "doc6.jpg"


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

    # Verify review record in DB updated. P16: the stored review_status now
    # correctly lands on a real ReviewStatus enum member (human_corrected —
    # the closest fit for "a human acted on this row", since the canonical
    # schema's own closed enum has no distinct "approved without change"
    # state) instead of the literal string "approved", which was never a
    # valid member and would fail validation anywhere this field gets
    # re-parsed as ReviewStatus. The response envelope's own status="approved"
    # is a separate, free-form field and is untouched by this fix.
    rev = test_db_session.query(ReviewRecord).join(Transaction).filter(Transaction.document_id == "doc-approve-1").first()
    assert rev.review_status == ReviewStatus.human_corrected.value


def test_correct_document_endpoint(
    client: TestClient, test_db_session: Session, tmp_path: Path, isolated_column_mappings_path: Path
):
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

    # P14: the uniform final output table should say a human touched this
    # row too, not just the Correction audit log / review_status.
    test_db_session.refresh(txn)
    assert txn.final_output.update_by == "human_reviewer"
    assert txn.final_output.updated_on is not None

    # Verify column mapping alias was promoted — read the isolated tmp copy
    # directly (not load_column_mappings(), which would read the real repo
    # file this fixture deliberately keeps untouched; see
    # isolated_column_mappings_path's own docstring).
    mappings = yaml.safe_load(isolated_column_mappings_path.read_text(encoding="utf-8"))
    assert "new_custom_hdr" in [a.lower() for a in mappings.get("opening_quantity", {}).get("aliases", [])]
