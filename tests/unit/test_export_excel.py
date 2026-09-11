"""P8 unit tests for export/excel.py — CLAUDE.md checklist: "Output matches
canonical schema exactly (no ad hoc renamed columns)."""
from __future__ import annotations

import json

import openpyxl
import pandas as pd
import pytest
from sqlalchemy.orm import Session

from pharma_di.export.excel import CANONICAL_COLUMNS, export_to_excel
from pharma_di.persist.db import get_engine
from pharma_di.persist.models import Base
from pharma_di.persist.repository import save_document
from pharma_di.schemas.canonical import CanonicalRow, DocumentRecord, DocumentType, ProductRecord, ReviewStatus, TransactionRecord
from pharma_di.schemas.validation import RowValidationResult


@pytest.fixture()
def session(tmp_path) -> Session:
    engine = get_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _seed_one_row(session, document_id="doc6-test"):
    document_record = DocumentRecord(
        document_id=document_id,
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
            distributor_name="Marg Pharma Distributor",
            company_name="Zorvia Healthcare",
            product_name_raw="COSKLOT REG TAB.",
            hsn_code="30049099",
            rate=408.86,
            opening_quantity=16.0,
            opening_value=6541.76,
            source_field_breakdown={"sales_return_quantity": {"Market Return": 2.0, "Return Outward": 1.0}},
            source_document="doc6.jpg",
            page_number=1,
            extraction_confidence={"opening_quantity": 0.98},
            review_status=ReviewStatus.auto_accepted,
        )
    ]
    validation_results = [RowValidationResult(document_id=document_id, row_index=0, rule_results=[])]
    save_document(session, document_record, products, transactions, rows, validation_results)


def test_columns_are_derived_from_canonical_row_and_nothing_else():
    assert CANONICAL_COLUMNS == list(CanonicalRow.model_fields.keys())


def test_export_writes_an_xlsx_with_exact_canonical_columns_and_real_values(session, tmp_path):
    _seed_one_row(session)
    output_path = export_to_excel(session, tmp_path / "out.xlsx", document_id="doc6-test")

    assert output_path.exists()
    df = pd.read_excel(output_path)
    assert list(df.columns) == CANONICAL_COLUMNS
    assert len(df) == 1
    assert df.iloc[0]["product_name_raw"] == "COSKLOT REG TAB."
    assert df.iloc[0]["opening_quantity"] == 16.0

    # hsn_code is an identifier, not a quantity — pd.read_excel's own
    # numeric-string inference (verified separately: it, not to_excel,
    # is what turns an all-digit column into int64 on *read*) would
    # obscure a real regression here, so check the actual stored cell
    # type via openpyxl directly rather than through that inference layer.
    wb = openpyxl.load_workbook(output_path)
    ws = wb.active
    header = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    hsn_col = header.index("hsn_code") + 1
    hsn_cell = ws.cell(row=2, column=hsn_col)
    assert hsn_cell.data_type == "s", f"hsn_code must be stored as text, not a number (data_type={hsn_cell.data_type!r})"
    assert hsn_cell.value == "30049099"


def test_dict_valued_fields_are_serialized_to_valid_json_strings(session, tmp_path):
    _seed_one_row(session)
    output_path = export_to_excel(session, tmp_path / "out.xlsx", document_id="doc6-test")

    df = pd.read_excel(output_path)
    breakdown = json.loads(df.iloc[0]["source_field_breakdown"])
    assert breakdown == {"sales_return_quantity": {"Market Return": 2.0, "Return Outward": 1.0}}
    confidence = json.loads(df.iloc[0]["extraction_confidence"])
    assert confidence == {"opening_quantity": 0.98}


def test_export_for_unknown_document_id_produces_header_only_file(session, tmp_path):
    _seed_one_row(session)  # a real row exists, but for a different document_id
    output_path = export_to_excel(session, tmp_path / "empty.xlsx", document_id="does-not-exist")

    df = pd.read_excel(output_path)
    assert list(df.columns) == CANONICAL_COLUMNS
    assert len(df) == 0


def test_export_with_no_document_id_filter_includes_every_document(session, tmp_path):
    _seed_one_row(session, document_id="doc-a")
    _seed_one_row(session, document_id="doc-b")
    output_path = export_to_excel(session, tmp_path / "all.xlsx")

    df = pd.read_excel(output_path)
    assert len(df) == 2
