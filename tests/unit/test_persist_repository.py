"""P8 unit tests for persist/repository.py — the save/load path both
`persist` and `review_queue` graph nodes share (see graph/nodes.py's
`_persist_document` for why both call it rather than only `persist`)."""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.orm import Session

from pharma_di.persist.db import get_engine
from pharma_di.persist.models import Base
from pharma_di.persist.repository import load_canonical_rows, load_final_output_rows, save_document
from pharma_di.schemas.canonical import CanonicalRow, DocumentRecord, DocumentType, ProductRecord, ReviewStatus, TransactionRecord
from pharma_di.schemas.validation import RowValidationResult, RuleId, RuleResult


@pytest.fixture()
def session(tmp_path) -> Session:
    engine = get_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _document_record(document_id="doc6-test", **overrides) -> DocumentRecord:
    kwargs = dict(
        document_id=document_id,
        distributor_id="marg-pharma",
        distributor_name="Marg Pharma Distributor",
        company_name="Zorvia Healthcare",
        statement_from=dt.date(2025, 3, 1),
        statement_to=dt.date(2025, 3, 31),
        document_type=DocumentType.product_level,
        source_file="doc6.jpg",
        page_number=1,
        page_count=1,
    )
    kwargs.update(overrides)
    return DocumentRecord(**kwargs)


def _product_level_fixture(document_id="doc6-test"):
    # Real doc6.jpg row 0 figures (CLAUDE.md finding #4 / this session's own
    # verified R4 test): 16 * 408.86 = 6541.76.
    document_record = _document_record(document_id)
    products = [ProductRecord(product_name_raw="COSKLOT REG TAB.", hsn_code="30049099", rate=408.86)]
    transactions = [TransactionRecord(opening_qty=16.0, opening_value=6541.76, closing_qty=10.0, closing_value=4088.60)]
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
            closing_quantity=10.0,
            closing_value=4088.60,
            source_field_breakdown={},
            source_document="doc6.jpg",
            page_number=1,
            extraction_confidence={"opening_quantity": 0.98},
            review_status=ReviewStatus.auto_accepted,
            review_reasons=[],
            null_field_reasons={"received_quantity": "no source column resolved to this field"},
        )
    ]
    validation_results = [
        RowValidationResult(
            document_id=document_id,
            row_index=0,
            rule_results=[RuleResult(rule_id=RuleId.r4_rate_coherence, passed=True, detail="opening: 16*408.86==6541.76")],
        )
    ]
    return document_record, products, transactions, rows, validation_results


def test_save_and_load_product_level_document_round_trips_real_values(session):
    document_record, products, transactions, rows, validation_results = _product_level_fixture()
    save_document(session, document_record, products, transactions, rows, validation_results)

    loaded = load_canonical_rows(session, document_id="doc6-test")
    assert len(loaded) == 1
    row = loaded[0]
    assert row["distributor_name"] == "Marg Pharma Distributor"
    assert row["product_name_raw"] == "COSKLOT REG TAB."
    assert row["hsn_code"] == "30049099"
    assert row["rate"] == 408.86
    assert row["opening_quantity"] == 16.0
    assert row["opening_value"] == 6541.76
    assert row["source_document"] == "doc6.jpg"
    assert row["page_number"] == 1
    assert row["review_status"] == "auto_accepted"
    assert row["extraction_confidence"] == {"opening_quantity": 0.98}
    assert row["null_field_reasons"] == {"received_quantity": "no source column resolved to this field"}
    assert row["review_reasons"] == []


def test_save_document_summary_only_writes_no_product_rows(session):
    document_record = _document_record("doc3-test", document_type=DocumentType.summary)
    row = CanonicalRow(
        document_type=DocumentType.summary,
        distributor_name="Nabin Drug Centre",
        company_name="Eris Lifescience",
        product_id=None,
        product_name_raw=None,
        hsn_code=None,
        opening_value=109599.61,
        closing_value=47912.00,
        source_document="doc3.jpg",
        page_number=1,
        null_field_reasons={"opening_quantity": "no quantities on this page — value-only summary"},
    )
    validation_result = RowValidationResult(document_id="doc3-test", row_index=0, rule_results=[])

    save_document(session, document_record, [], [], [row], [validation_result])

    loaded = load_canonical_rows(session, document_id="doc3-test")
    assert len(loaded) == 1
    assert loaded[0]["product_id"] is None
    assert loaded[0]["product_name_raw"] is None
    assert loaded[0]["opening_value"] == 109599.61
    assert loaded[0]["closing_value"] == 47912.00


def test_resaving_same_document_id_replaces_rather_than_duplicates(session):
    document_record, products, transactions, rows, validation_results = _product_level_fixture()
    save_document(session, document_record, products, transactions, rows, validation_results)

    # Re-run with a corrected rate (e.g. a human correction re-triggered persistence).
    products[0] = products[0].model_copy(update={"rate": 999.0})
    rows[0] = rows[0].model_copy(update={"rate": 999.0})
    save_document(session, document_record, products, transactions, rows, validation_results)

    loaded = load_canonical_rows(session, document_id="doc6-test")
    assert len(loaded) == 1
    assert loaded[0]["rate"] == 999.0


def test_load_without_document_id_returns_rows_from_every_document(session):
    doc_a = _product_level_fixture("doc-a")
    doc_b = _product_level_fixture("doc-b")
    save_document(session, *doc_a)
    save_document(session, *doc_b)

    loaded = load_canonical_rows(session)
    assert {r["source_document"] for r in loaded} == {"doc6.jpg"}
    assert len(loaded) == 2


def test_load_for_unknown_document_id_returns_empty(session):
    assert load_canonical_rows(session, document_id="does-not-exist") == []


# --- P14: FinalOutput (uniform final table) --------------------------------


def test_save_document_writes_a_final_output_row_with_real_address_lookup(session):
    # medico-drug-agency is doc6.jpg's real distributor (config/distributors.yaml)
    # — its address is real, hand-recorded config, not fabricated for this test.
    document_record, products, transactions, rows, validation_results = _product_level_fixture()
    document_record = document_record.model_copy(
        update={"distributor_id": "medico-drug-agency", "distributor_name": "Medico Drug Agency"}
    )
    rows = [r.model_copy(update={"distributor_id": "medico-drug-agency", "distributor_name": "Medico Drug Agency"}) for r in rows]
    save_document(session, document_record, products, transactions, rows, validation_results)

    final_rows = load_final_output_rows(session, document_id="doc6-test")
    assert len(final_rows) == 1
    row = final_rows[0]
    assert row["stockist_distributor_name"] == "Medico Drug Agency"
    assert row["address"] == "Ronaldsay Road, Battala, Agartala, Tripura (W)"
    assert row["product_name"] == "COSKLOT REG TAB."
    assert row["opening_qty"] == 16.0
    assert row["closing_qty"] == 10.0
    assert row["dump_qty"] is None  # not set on this fixture's TransactionRecord — null, not 0
    assert row["file_name"] == "doc6.jpg"
    assert row["scan_by"] == "system"
    assert row["update_by"] == "system"
    assert row["scan_date"] is not None
    assert row["updated_on"] is not None


def test_final_output_address_is_null_for_a_distributor_not_in_config(session):
    # The fixture's own "marg-pharma" id is deliberately not a real
    # config/distributors.yaml entry — same "route to review rather than
    # guess" discipline an unresolved product already follows.
    document_record, products, transactions, rows, validation_results = _product_level_fixture()
    save_document(session, document_record, products, transactions, rows, validation_results)

    final_rows = load_final_output_rows(session, document_id="doc6-test")
    assert final_rows[0]["address"] is None


def test_save_document_summary_only_still_writes_a_final_output_row(session):
    document_record = _document_record(
        "doc3-test",
        document_type=DocumentType.summary,
        distributor_id="nabin-drug-centre",
        distributor_name="Nabin Drug Centre",
    )
    row = CanonicalRow(
        document_type=DocumentType.summary,
        distributor_id="nabin-drug-centre",
        distributor_name="Nabin Drug Centre",
        company_name="Eris Lifescience",
        opening_value=109599.61,
        closing_value=47912.00,
        source_document="doc3.jpg",
        page_number=1,
    )
    validation_result = RowValidationResult(document_id="doc3-test", row_index=0, rule_results=[])

    save_document(session, document_record, [], [], [row], [validation_result])

    final_rows = load_final_output_rows(session, document_id="doc3-test")
    assert len(final_rows) == 1
    assert final_rows[0]["product_name"] is None  # no product on a summary document
    assert final_rows[0]["stockist_distributor_name"] == "Nabin Drug Centre"
    assert final_rows[0]["address"] == "N S Road, Old Motor Stand, Dharmanagar, Tripura North"


def test_resaving_replaces_the_final_output_row_too(session):
    document_record, products, transactions, rows, validation_results = _product_level_fixture()
    save_document(session, document_record, products, transactions, rows, validation_results)

    products[0] = products[0].model_copy(update={"product_name_raw": "CORRECTED NAME"})
    rows[0] = rows[0].model_copy(update={"product_name_raw": "CORRECTED NAME"})
    save_document(session, document_record, products, transactions, rows, validation_results)

    final_rows = load_final_output_rows(session, document_id="doc6-test")
    assert len(final_rows) == 1
    assert final_rows[0]["product_name"] == "CORRECTED NAME"
