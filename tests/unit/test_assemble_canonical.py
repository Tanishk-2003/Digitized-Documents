"""P6 unit tests for assemble/canonical.py — 3-level canonical assembly
(IMPLEMENTATION_PLAN.md P6 / CLAUDE.md's "Data model: 3 levels")."""
from __future__ import annotations

import datetime as dt

from pharma_di.assemble.canonical import assemble_document
from pharma_di.schemas.canonical import DocumentRecord, DocumentType
from pharma_di.schemas.layout import BBox, Cell, ColumnBand, HeaderNode, Region, RegionType, TableGrid
from pharma_di.schemas.mapping import ColumnMapping, MappingDecision, MappingStatus
from pharma_di.schemas.ocr import OcrToken


def _header(path):
    return HeaderNode(path=path, bbox=BBox(x0=0, y0=0, x1=100, y1=20))


def _band(path):
    return ColumnBand(header=_header(path), x0=0, x1=100)


def _tok(text, conf=0.95):
    return OcrToken(text=text, bbox=BBox(x0=0, y0=0, x1=10, y1=10), confidence=conf)


def _cell(row_index, path, text, conf=0.95):
    tokens = [_tok(text, conf)] if text else []
    return Cell(row_index=row_index, column=_header(path), tokens=tokens)


def _decision(path, field, status=MappingStatus.exact, combine=None):
    return MappingDecision(source_header=_header(path), canonical_field=field, status=status, combine=combine)


def _doc_record(document_type=DocumentType.product_level, **overrides):
    kwargs = dict(
        document_id="test-doc",
        source_file="test.jpg",
        page_number=1,
        page_count=1,
        distributor_id="acme",
        distributor_name="Acme",
        company_name="Acme Co",
        document_type=document_type,
    )
    kwargs.update(overrides)
    return DocumentRecord(**kwargs)


def _region():
    return Region(region_type=RegionType.stock_table, bbox=BBox(x0=0, y0=0, x1=200, y1=200))


# --- product_level assembly --------------------------------------------------


def test_assemble_document_builds_one_row_per_product():
    columns = [_band(["Product"]), _band(["Opening", "Qty."]), _band(["Opening", "Value"])]
    mapping = ColumnMapping(
        decisions=[
            _decision(["Product"], "product_name_raw"),
            _decision(["Opening", "Qty."], "opening_quantity"),
            _decision(["Opening", "Value"], "opening_value"),
        ]
    )
    grid = TableGrid(
        region=_region(),
        columns=columns,
        row_count=2,
        cells=[
            _cell(0, ["Product"], "COSKLOT REG TAB."),
            _cell(0, ["Opening", "Qty."], "16"),
            _cell(0, ["Opening", "Value"], "6541.76"),
            _cell(1, ["Product"], "COSKLOT-500 TAS"),
            _cell(1, ["Opening", "Qty."], "72"),
            _cell(1, ["Opening", "Value"], "18034.08"),
        ],
    )
    products, transactions, rows, errors = assemble_document(grid, mapping, _doc_record())

    assert errors == []
    assert len(products) == len(transactions) == len(rows) == 2
    assert products[0].product_name_raw == "COSKLOT REG TAB."
    assert transactions[0].opening_qty == 16.0
    assert transactions[0].opening_value == 6541.76
    assert rows[0].opening_quantity == 16.0
    assert rows[0].document_type == DocumentType.product_level


def test_assemble_document_skips_section_label_rows():
    columns = [_band(["Product"]), _band(["Opening", "Qty."])]
    mapping = ColumnMapping(
        decisions=[_decision(["Product"], "product_name_raw"), _decision(["Opening", "Qty."], "opening_quantity")]
    )
    grid = TableGrid(
        region=_region(),
        columns=columns,
        row_count=2,
        cells=[
            _cell(0, ["Product"], "ZORVIA HEALTHCARE LTD"),
            _cell(0, ["Opening", "Qty."], ""),
            _cell(1, ["Product"], "COSKLOT REG TAB."),
            _cell(1, ["Opening", "Qty."], "16"),
        ],
        section_label_rows={0: "ZORVIA HEALTHCARE LTD"},
    )
    products, _transactions, rows, _errors = assemble_document(grid, mapping, _doc_record())
    assert len(products) == 1
    assert products[0].product_name_raw == "COSKLOT REG TAB."
    assert len(rows) == 1


def test_assemble_document_skips_row_with_no_resolved_product_name_and_records_error():
    columns = [_band(["Unresolved"]), _band(["Opening", "Qty."])]
    mapping = ColumnMapping(
        decisions=[_decision(["Unresolved"], None, status=MappingStatus.unresolved), _decision(["Opening", "Qty."], "opening_quantity")]
    )
    grid = TableGrid(
        region=_region(),
        columns=columns,
        row_count=1,
        cells=[_cell(0, ["Unresolved"], "some text"), _cell(0, ["Opening", "Qty."], "16")],
    )
    products, transactions, rows, errors = assemble_document(grid, mapping, _doc_record())
    assert products == [] and transactions == [] and rows == []
    assert len(errors) == 1 and "row 0" in errors[0]


def test_blank_cell_is_null_not_zero():
    columns = [_band(["Product"]), _band(["Receipt", "Qty"])]
    mapping = ColumnMapping(
        decisions=[_decision(["Product"], "product_name_raw"), _decision(["Receipt", "Qty"], "received_quantity")]
    )
    grid = TableGrid(
        region=_region(),
        columns=columns,
        row_count=1,
        cells=[_cell(0, ["Product"], "COSKLOT REG TAB."), _cell(0, ["Receipt", "Qty"], "")],  # blank — no tokens
    )
    _products, transactions, rows, _errors = assemble_document(grid, mapping, _doc_record())
    assert transactions[0].received_qty is None
    assert rows[0].received_quantity is None
    assert "received_quantity" in rows[0].null_field_reasons


def test_printed_zero_is_a_real_zero_not_null():
    columns = [_band(["Product"]), _band(["Receipt", "Qty"])]
    mapping = ColumnMapping(
        decisions=[_decision(["Product"], "product_name_raw"), _decision(["Receipt", "Qty"], "received_quantity")]
    )
    grid = TableGrid(
        region=_region(),
        columns=columns,
        row_count=1,
        cells=[_cell(0, ["Product"], "COSKLOT REG TAB."), _cell(0, ["Receipt", "Qty"], "0")],
    )
    _products, transactions, rows, _errors = assemble_document(grid, mapping, _doc_record())
    assert transactions[0].received_qty == 0.0
    assert rows[0].received_quantity == 0.0
    assert "received_quantity" not in rows[0].null_field_reasons


def test_derived_check_only_keeps_multiple_printed_totals_separate_not_summed():
    # doc2.jpg's real case: "Total Revd." and "Total Sold" both resolve to
    # derived_check_only on the same row — they are two independent printed
    # totals (R3 checks each against a different pair of fields), not parts
    # of one combined quantity, so they must NOT be summed together the way
    # a real combine=sum field would be.
    columns = [_band(["Product"]), _band(["Total Revd."]), _band(["Total Sold"])]
    mapping = ColumnMapping(
        decisions=[
            _decision(["Product"], "product_name_raw"),
            _decision(["Total Revd."], "derived_check_only"),
            _decision(["Total Sold"], "derived_check_only"),
        ]
    )
    grid = TableGrid(
        region=_region(),
        columns=columns,
        row_count=1,
        cells=[
            _cell(0, ["Product"], "COSKLOT 500 10 TAB"),
            _cell(0, ["Total Revd."], "68"),
            _cell(0, ["Total Sold"], "49"),
        ],
    )
    _products, _transactions, rows, _errors = assemble_document(grid, mapping, _doc_record())
    assert rows[0].source_field_breakdown["derived_check_only"] == {"Total Revd.": 68.0, "Total Sold": 49.0}


def test_combine_sum_fields_are_summed_and_recorded_in_breakdown():
    # New Tripura's real case (section 4.6): three source columns feed one
    # canonical field.
    columns = [_band(["Product"]), _band(["Market Return"]), _band(["Return Outward"]), _band(["Short Quantity"])]
    mapping = ColumnMapping(
        decisions=[
            _decision(["Product"], "product_name_raw"),
            _decision(["Market Return"], "sales_return_quantity", combine="sum"),
            _decision(["Return Outward"], "sales_return_quantity", combine="sum"),
            _decision(["Short Quantity"], "sales_return_quantity", combine="sum"),
        ]
    )
    grid = TableGrid(
        region=_region(),
        columns=columns,
        row_count=1,
        cells=[
            _cell(0, ["Product"], "DECOKIT SYRUP"),
            _cell(0, ["Market Return"], "2"),
            _cell(0, ["Return Outward"], "1"),
            _cell(0, ["Short Quantity"], "3"),
        ],
    )
    _products, _transactions, rows, _errors = assemble_document(grid, mapping, _doc_record())
    assert rows[0].sales_return_quantity == 6.0
    assert rows[0].source_field_breakdown["sales_return_quantity"] == {
        "Market Return": 2.0,
        "Return Outward": 1.0,
        "Short Quantity": 3.0,
    }


def test_extraction_confidence_for_combined_field_is_the_minimum_contributor():
    columns = [_band(["Product"]), _band(["Market Return"]), _band(["Return Outward"])]
    mapping = ColumnMapping(
        decisions=[
            _decision(["Product"], "product_name_raw"),
            _decision(["Market Return"], "sales_return_quantity", combine="sum"),
            _decision(["Return Outward"], "sales_return_quantity", combine="sum"),
        ]
    )
    grid = TableGrid(
        region=_region(),
        columns=columns,
        row_count=1,
        cells=[
            _cell(0, ["Product"], "DECOKIT SYRUP"),
            _cell(0, ["Market Return"], "2", conf=0.95),
            _cell(0, ["Return Outward"], "1", conf=0.40),
        ],
    )
    _products, _transactions, rows, _errors = assemble_document(grid, mapping, _doc_record())
    assert rows[0].extraction_confidence["sales_return_quantity"] == 0.40


def test_unresolved_column_contributes_nothing():
    columns = [_band(["Product"]), _band(["Dump", "Qty"])]
    mapping = ColumnMapping(
        decisions=[_decision(["Product"], "product_name_raw"), _decision(["Dump", "Qty"], None, status=MappingStatus.unresolved)]
    )
    grid = TableGrid(
        region=_region(),
        columns=columns,
        row_count=1,
        cells=[_cell(0, ["Product"], "COSKLOT REG TAB."), _cell(0, ["Dump", "Qty"], "16")],
    )
    _products, _transactions, rows, _errors = assemble_document(grid, mapping, _doc_record())
    assert rows[0].source_field_breakdown == {}
    # Not written to ANY canonical field — 16 exists only in the raw OCR
    # data, never guessed onto expired_quantity/closing_quantity/anything else.
    assert 16.0 not in [
        rows[0].opening_quantity, rows[0].closing_quantity, rows[0].expired_quantity, rows[0].received_quantity,
    ]


# --- summary assembly ---------------------------------------------------------


def test_summary_document_emits_exactly_one_row_with_no_product_levels():
    columns = [_band(["Opening"]), _band(["Closing", "Value"])]
    mapping = ColumnMapping(
        decisions=[_decision(["Opening"], "opening_value"), _decision(["Closing", "Value"], "closing_value")]
    )
    grid = TableGrid(
        region=_region(),
        columns=columns,
        row_count=1,
        cells=[_cell(0, ["Opening"], "109599.61"), _cell(0, ["Closing", "Value"], "47912.00")],
    )
    products, transactions, rows, errors = assemble_document(grid, mapping, _doc_record(document_type=DocumentType.summary))

    assert errors == []
    assert products == [] and transactions == []
    assert len(rows) == 1
    assert rows[0].document_type == DocumentType.summary
    assert rows[0].product_id is None
    assert rows[0].product_name_raw is None
    assert rows[0].hsn_code is None
    assert rows[0].opening_value == 109599.61
    assert rows[0].closing_value == 47912.00


def test_summary_document_merges_values_scattered_across_multiple_rows():
    # doc3.jpg's real shape (see this module's own docstring): the summary's
    # one true set of values gets scattered across several bogus "rows"
    # because there's no product-name seed column to anchor them to one.
    columns = [_band(["Opening"]), _band(["Closing", "Value"])]
    mapping = ColumnMapping(
        decisions=[_decision(["Opening"], "opening_value"), _decision(["Closing", "Value"], "closing_value")]
    )
    grid = TableGrid(
        region=_region(),
        columns=columns,
        row_count=2,
        cells=[
            _cell(0, ["Opening"], "109599.61"),
            _cell(0, ["Closing", "Value"], ""),  # blank on this bogus row
            _cell(1, ["Opening"], ""),  # blank on this one instead
            _cell(1, ["Closing", "Value"], "47912.00"),
        ],
    )
    _products, _transactions, rows, _errors = assemble_document(grid, mapping, _doc_record(document_type=DocumentType.summary))
    assert len(rows) == 1
    assert rows[0].opening_value == 109599.61
    assert rows[0].closing_value == 47912.00


def test_grid_is_none_returns_empty_with_no_error():
    products, transactions, rows, errors = assemble_document(None, ColumnMapping(decisions=[]), _doc_record())
    assert (products, transactions, rows, errors) == ([], [], [], [])


def test_document_type_none_returns_empty_with_no_error():
    # A document P4 couldn't even classify (rare, but must not crash or guess).
    columns = [_band(["Product"])]
    mapping = ColumnMapping(decisions=[_decision(["Product"], "product_name_raw")])
    grid = TableGrid(region=_region(), columns=columns, row_count=1, cells=[_cell(0, ["Product"], "X")])
    products, transactions, rows, errors = assemble_document(grid, mapping, _doc_record(document_type=None))
    assert (products, transactions, rows, errors) == ([], [], [], [])
