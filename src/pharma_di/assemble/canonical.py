"""3-level canonical assembly (IMPLEMENTATION_PLAN.md P6 / CLAUDE.md's "Data
model: 3 levels, not one flat table"): turn a resolved TableGrid +
ColumnMapping into real ProductRecord / TransactionRecord / CanonicalRow
instances.

Naming translation — schemas/canonical.py's own docstring explains why one
exists at all: CLAUDE.md itself uses "_qty" for Level 3 (TransactionRecord:
opening_qty, received_qty, ...) but "_quantity" for the canonical join-view
table (CanonicalRow, matching config/column_mappings.yaml's own canonical
field names exactly) — "producing one from the other is the assemble
stage's job (P6), not a naming decision made ahead of time." That
translation is LEVEL3_TO_TRANSACTION_FIELD below, the one place it's built
(public since P8: persist/repository.py reuses it verbatim to go the same
direction — CanonicalRow's "_quantity" names to TransactionRecord's "_qty"
names — for the summary-document storage case, rather than redeclaring the
same field-name pairs a second time).

Column-to-cell correspondence is positional, not header-text-keyed:
`row_cells` and `column_mapping.decisions` are assumed to align with the
same TableGrid.columns order both were built from (map_columns builds
exactly one decision per grid.columns entry, in that order). A text-keyed
lookup would silently collide two columns that share the same garbled
header — found this session, doc1.jpg has two separate "Return" columns
with identical text but different data.
"""
from __future__ import annotations

from typing import Any

from pharma_di.layout.columns import is_numeric
from pharma_di.schemas.canonical import CanonicalRow, DocumentRecord, DocumentType, ProductRecord, TransactionRecord
from pharma_di.schemas.layout import Cell, TableGrid
from pharma_di.schemas.mapping import ColumnMapping, MappingDecision

LEVEL3_TO_TRANSACTION_FIELD = {
    "opening_quantity": "opening_qty",
    "opening_value": "opening_value",
    "received_quantity": "received_qty",
    "received_value": "received_value",
    "free_received_quantity": "free_received_qty",
    "sales_quantity": "sales_qty",
    "sales_value": "sales_value",
    "free_sales_quantity": "free_sales_qty",
    "sales_return_quantity": "sales_return_qty",
    "purchase_return_quantity": "purchase_return_qty",
    "expired_quantity": "expired_qty",
    "closing_quantity": "closing_qty",
    "closing_value": "closing_value",
    "dump_quantity": "dump_qty",
    "months_to_expiry": "months_to_expiry",
    "stock_status": "stock_status",
}
# Public since P14: validate/rules.py and validate/engine.py both used to
# hand-maintain their own separate copy of this exact list (flagged by
# P12's own generalization audit — "adding a new Level-3 canonical field
# requires editing both lists by hand or R5/R6 silently skip it"). Fixed
# here rather than perpetuated, since adding dump_quantity is exactly that
# scenario. Both now derive their own filtered view from this one list
# instead of re-declaring it.
LEVEL3_CANONICAL_FIELDS = list(LEVEL3_TO_TRANSACTION_FIELD)
# Public since UI-UX-Implementation.md Phase A.4, same reasoning as
# LEVEL3_CANONICAL_FIELDS above: api/routes_review.py::correct_document
# needs the same field taxonomy this module already has, to actually apply
# a correction's value (previously it only ever wrote to the Correction
# audit table — see that function's own docstring for the real gap this
# closes).
PRODUCT_CANONICAL_FIELDS = ["product_name_raw", "hsn_code", "pack", "rate"]
STRING_CANONICAL_FIELDS = {"stock_status", "product_name_raw", "hsn_code", "pack"}


def _parse_cell_value(text: str, canonical_field: str) -> float | str | None:
    """None for a genuinely blank cell (no tokens) or non-numeric text in a
    numeric field — CLAUDE.md: "rate... null otherwise, not zero" applies
    to every quantity/value field, not just rate, and a value that was
    never printed must never be guessed at as zero."""
    stripped = text.strip()
    if not stripped:
        return None
    if canonical_field in STRING_CANONICAL_FIELDS:
        return stripped
    if not is_numeric(stripped):
        return None
    return float(stripped.replace(",", ""))


_DERIVED_CHECK_ONLY = "derived_check_only"


def _row_field_values(
    row_cells: list[Cell], decisions: list[MappingDecision]
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, float]]:
    """One row's resolved canonical-field values, `source_field_breakdown`
    contributions for combine=sum fields, and per-field
    extraction_confidence (the minimum confidence across every contributing
    cell — a combined field is only as trustworthy as its weakest
    contributor).

    `derived_check_only` is always routed into the breakdown dict, keyed by
    header text, like a combine=sum field — but never summed into `values`:
    it can legitimately hold MULTIPLE, INDEPENDENT printed totals on one row
    (doc2.jpg has both "Total Revd." and "Total Sold" resolve to this same
    canonical field), and summing them together would produce a meaningless
    number for a field that isn't written to any CanonicalRow column at all
    (config/column_mappings.yaml's own comment: "Printed but not written to
    a canonical field directly — consumed by validation rule R3 instead").
    R3 reads each contributor back out of the breakdown by its own header
    text.
    """
    values: dict[str, Any] = {}
    breakdown: dict[str, dict[str, Any]] = {}
    confidence: dict[str, float] = {}

    for cell, decision in zip(row_cells, decisions):
        field = decision.canonical_field
        if field is None:
            continue
        parsed = _parse_cell_value(cell.text, field)
        if parsed is None:
            continue
        cell_confidence = cell.min_confidence

        if decision.combine == "sum" or field == _DERIVED_CHECK_ONLY:
            header_text = " ".join(decision.source_header.path)
            breakdown.setdefault(field, {})[header_text] = parsed
            if decision.combine == "sum":
                values[field] = values.get(field, 0.0) + parsed
        else:
            values[field] = parsed

        if cell_confidence is not None:
            confidence[field] = min(confidence.get(field, 1.0), cell_confidence)

    return values, breakdown, confidence


def _null_reasons(values: dict[str, Any], fields: list[str], reason: str) -> dict[str, str]:
    return {f: reason for f in fields if f not in values}


def _canonical_row_kwargs(
    document_record: DocumentRecord,
    values: dict[str, Any],
    breakdown: dict[str, dict[str, Any]],
    confidence: dict[str, float],
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {f: values.get(f) for f in LEVEL3_CANONICAL_FIELDS}
    kwargs.update(
        distributor_id=document_record.distributor_id,
        distributor_name=document_record.distributor_name,
        company_name=document_record.company_name,
        statement_from=document_record.statement_from,
        statement_to=document_record.statement_to,
        source_field_breakdown=breakdown,
        source_document=document_record.source_file,
        page_number=document_record.page_number,
        extraction_confidence=confidence,
    )
    return kwargs


def _build_transaction_record(values: dict[str, Any]) -> TransactionRecord:
    kwargs = {
        txn_field: values[canon_field]
        for canon_field, txn_field in LEVEL3_TO_TRANSACTION_FIELD.items()
        if canon_field in values
    }
    return TransactionRecord(**kwargs)


def assemble_document(
    grid: TableGrid | None, column_mapping: ColumnMapping, document_record: DocumentRecord
) -> tuple[list[ProductRecord], list[TransactionRecord], list[CanonicalRow], list[str]]:
    """Returns (product_records, transaction_records, canonical_rows,
    errors). Branches on `document_record.document_type` (P4's job to set,
    via a more reliable signal — a product-name-shaped column — than
    counting this table's own possibly-messy row count; see
    detect/document.py::detect_document_type), not on the table's own
    shape.

    `grid is None` (no stock_table region found at all) is a legitimate,
    non-error outcome — an entirely non-tabular or unrecognizable page —
    and returns empty lists with no errors, the same as an already-null
    document_type would.
    """
    if grid is None or document_record.document_type is None:
        return [], [], [], []
    if document_record.document_type == DocumentType.summary:
        return _assemble_summary(grid, column_mapping, document_record)
    return _assemble_product_level(grid, column_mapping, document_record)


def _assemble_product_level(
    grid: TableGrid, column_mapping: ColumnMapping, document_record: DocumentRecord
) -> tuple[list[ProductRecord], list[TransactionRecord], list[CanonicalRow], list[str]]:
    decisions = column_mapping.decisions
    products: list[ProductRecord] = []
    transactions: list[TransactionRecord] = []
    rows: list[CanonicalRow] = []
    errors: list[str] = []

    for row_index in sorted({c.row_index for c in grid.cells}):
        if row_index in grid.section_label_rows:
            continue  # a company/section-name row (schemas/layout.py's own
            # comment: "P6 uses this to update company_name instead of
            # emitting an empty product row for it") — not a product.

        row_cells = grid.cells_for_row(row_index)
        if len(row_cells) != len(decisions):
            errors.append(
                f"assemble_canonical: row {row_index} has {len(row_cells)} cells but "
                f"{len(decisions)} columns are mapped — skipped rather than misaligned"
            )
            continue

        values, breakdown, confidence = _row_field_values(row_cells, decisions)
        product_name_raw = values.get("product_name_raw")
        if not product_name_raw:
            errors.append(f"assemble_canonical: row {row_index} has no resolved product name — skipped")
            continue

        product = ProductRecord(
            product_name_raw=product_name_raw,
            hsn_code=values.get("hsn_code"),
            pack=values.get("pack"),
            rate=values.get("rate"),
        )
        transaction = _build_transaction_record(values)

        null_reasons = _null_reasons(
            values, LEVEL3_CANONICAL_FIELDS, "no source column on this document resolved to this field, or this row's cell was blank"
        )
        null_reasons.update(
            _null_reasons(values, ["hsn_code", "pack", "rate"], "no source column on this document resolved to this field")
        )

        canonical = CanonicalRow(
            **_canonical_row_kwargs(document_record, values, breakdown, confidence),
            document_type=DocumentType.product_level,
            product_id=None,  # resolve_products (the next node) fills this in
            product_name_raw=product.product_name_raw,
            hsn_code=product.hsn_code,
            pack=product.pack,
            rate=product.rate,
            null_field_reasons=null_reasons,
        )

        products.append(product)
        transactions.append(transaction)
        rows.append(canonical)

    return products, transactions, rows, errors


def _assemble_summary(
    grid: TableGrid, column_mapping: ColumnMapping, document_record: DocumentRecord
) -> tuple[list[ProductRecord], list[TransactionRecord], list[CanonicalRow], list[str]]:
    """CLAUDE.md: "A document can be company-level-only with no line
    items... The pipeline must detect this and emit a document-level
    summary rather than forcing an empty product table through row
    extraction. This is a first-class case, not an error state." Level 2/3
    records are absent by design here (CLAUDE.md: "absent for summary-only
    documents") — only ONE CanonicalRow is emitted, with product_id/
    hsn_code left None (CanonicalRow's own validator forbids anything else
    for a summary row).

    Values are merged across every "row" the table assembly produced,
    taking the first non-null value found per field scanning top to
    bottom, rather than trusting a single row index: doc3.jpg (CLAUDE.md's
    own summary example) has no product-name seed column at all, so
    assemble_stock_table's leftmost-column-is-the-seed assumption doesn't
    cleanly apply to it, and its one true set of values gets scattered
    across several bogus "rows" instead of landing in one — a known,
    already-documented P3 limitation (see this file's own P6 build notes
    in IMPLEMENTATION_PLAN.md), not something invented here. Merging is the
    most defensible reading of that scattered data available without
    fabricating a value that was never printed.
    """
    decisions = column_mapping.decisions
    merged_values: dict[str, Any] = {}
    merged_breakdown: dict[str, dict[str, Any]] = {}
    merged_confidence: dict[str, float] = {}

    for row_index in sorted({c.row_index for c in grid.cells}):
        row_cells = grid.cells_for_row(row_index)
        if len(row_cells) != len(decisions):
            continue
        values, breakdown, confidence = _row_field_values(row_cells, decisions)
        for field, value in values.items():
            merged_values.setdefault(field, value)
        for field, entries in breakdown.items():
            merged_breakdown.setdefault(field, {}).update(entries)
        for field, conf in confidence.items():
            merged_confidence.setdefault(field, conf)

    null_reasons = _null_reasons(
        merged_values,
        LEVEL3_CANONICAL_FIELDS,
        "no source column on this document resolved to this field, or every row's cell was blank",
    )

    canonical = CanonicalRow(
        **_canonical_row_kwargs(document_record, merged_values, merged_breakdown, merged_confidence),
        document_type=DocumentType.summary,
        product_id=None,
        product_name_raw=None,
        hsn_code=None,
        pack=None,
        rate=None,
        null_field_reasons=null_reasons,
    )
    return [], [], [canonical], []
