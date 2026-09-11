"""P0: lock in the invariants the plan actually depends on, not just "does
Pydantic accept valid input". Each test here maps to a specific checklist
line or design decision in CLAUDE.md / IMPLEMENTATION_PLAN.md.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from pharma_di.schemas.canonical import (
    CanonicalRow,
    DocumentRecord,
    DocumentType,
    ProductRecord,
    ReviewStatus,
    TransactionRecord,
)
from pharma_di.schemas.layout import BBox, HeaderNode
from pharma_di.schemas.mapping import ColumnMapping, MappingDecision, MappingStatus
from pharma_di.schemas.ocr import OcrToken


# --- OCR: per-token confidence bounds ---------------------------------------


def test_ocr_token_confidence_must_be_in_unit_range():
    OcrToken(text="foo", bbox=BBox(x0=0, y0=0, x1=1, y1=1), confidence=0.5)  # ok
    with pytest.raises(ValidationError):
        OcrToken(text="foo", bbox=BBox(x0=0, y0=0, x1=1, y1=1), confidence=1.5)


# --- Layout: hierarchical header path -> normalized key ---------------------


def test_header_node_normalized_key_matches_dictionary_path_format():
    node = HeaderNode(path=["OPENING", "QTY."], bbox=BBox(x0=0, y0=0, x1=1, y1=1))
    assert node.normalized_key == "opening|qty."


# --- Mapping: "no column is ever guessed" is a structural invariant ---------


def test_unresolved_mapping_cannot_carry_a_canonical_field():
    header = HeaderNode(path=["DUMP", "QTY."], bbox=BBox(x0=0, y0=0, x1=1, y1=1))
    with pytest.raises(ValidationError):
        MappingDecision(source_header=header, canonical_field="expired_quantity", status=MappingStatus.unresolved)


def test_unresolved_mapping_with_no_field_is_valid():
    header = HeaderNode(path=["DUMP", "QTY."], bbox=BBox(x0=0, y0=0, x1=1, y1=1))
    decision = MappingDecision(source_header=header, canonical_field=None, status=MappingStatus.unresolved)
    assert decision.canonical_field is None


def test_resolved_mapping_requires_a_canonical_field():
    header = HeaderNode(path=["OPENING", "QTY."], bbox=BBox(x0=0, y0=0, x1=1, y1=1))
    with pytest.raises(ValidationError):
        MappingDecision(source_header=header, canonical_field=None, status=MappingStatus.exact)


def _decision(path, field, status):
    header = HeaderNode(path=path, bbox=BBox(x0=0, y0=0, x1=1, y1=1))
    return MappingDecision(source_header=header, canonical_field=field, status=status)


def test_column_mapping_unmapped_columns_returns_only_unresolved_headers():
    mapping = ColumnMapping(
        decisions=[
            _decision(["Product"], "product_name_raw", MappingStatus.exact),
            _decision(["Dump", "Qty."], None, MappingStatus.unresolved),
        ]
    )
    assert [h.path for h in mapping.unmapped_columns] == [["Dump", "Qty."]]


def test_column_mapping_resolved_fraction_counts_non_unresolved_decisions():
    mapping = ColumnMapping(
        decisions=[
            _decision(["Product"], "product_name_raw", MappingStatus.exact),
            _decision(["Rate"], "rate", MappingStatus.fuzzy_low_confidence),
            _decision(["Dump", "Qty."], None, MappingStatus.unresolved),
        ]
    )
    assert mapping.resolved_fraction == pytest.approx(2 / 3)


def test_column_mapping_resolved_fraction_is_one_for_empty_decisions():
    # An empty table has nothing unresolved — vacuously fully resolved,
    # not zero (which would misleadingly read as "nothing worked").
    assert ColumnMapping(decisions=[]).resolved_fraction == 1.0


# --- Canonical: summary-only documents (doc3.jpg) ---------------------------


def test_summary_document_type_forbids_resolved_product_id():
    with pytest.raises(ValidationError):
        CanonicalRow(
            document_type=DocumentType.summary,
            product_id="some-product",
            source_document="doc3.jpg",
            page_number=1,
        )


def test_summary_document_with_all_product_fields_null_is_valid():
    row = CanonicalRow(
        document_type=DocumentType.summary,
        source_document="doc3.jpg",
        page_number=1,
        opening_value=109599.61,   # doc3.jpg: real printed value, quantities genuinely absent
        closing_value=47912.0,
    )
    assert row.product_id is None
    assert row.opening_quantity is None  # null, not zero — CLAUDE.md is explicit about this distinction


# --- Canonical: null-not-zero for unreported fields --------------------------


def test_rate_defaults_to_none_not_zero():
    product = ProductRecord(product_name_raw="ZORVICAL TAB")
    assert product.rate is None  # doc1.jpg (New Tripura) never prints a RATE column


def test_transaction_record_allows_partial_population():
    # doc1.jpg product rows: Purchase Quantity is always 0 (real, printed zero),
    # but e.g. free_received_qty is never printed on this format at all (null).
    txn = TransactionRecord(opening_qty=20, received_qty=0, closing_qty=20)
    assert txn.free_received_qty is None
    assert txn.received_qty == 0  # printed zero is a real value, distinct from "not reported"


# --- Canonical: review status / traceability fields exist -------------------


def test_canonical_row_requires_traceability_fields():
    with pytest.raises(ValidationError):
        CanonicalRow(document_type=DocumentType.product_level, page_number=1)  # missing source_document


def test_canonical_row_default_review_status_is_needs_review_not_auto_accepted():
    row = CanonicalRow(document_type=DocumentType.product_level, source_document="doc6.jpg", page_number=1)
    # Nothing has validated this row yet, so it must not default to accepted.
    assert row.review_status == ReviewStatus.needs_review


# --- Document record ---------------------------------------------------------


def test_document_record_page_number_must_be_positive():
    with pytest.raises(ValidationError):
        DocumentRecord(document_id="x", source_file="doc1.jpg", page_number=0, page_count=1)
