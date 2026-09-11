"""P7 unit tests for validate/totals.py — R2 totals cross-foot
(IMPLEMENTATION_PLAN.md section 4.7)."""
from __future__ import annotations

from pharma_di.schemas.layout import BBox, ColumnBand, HeaderNode, Region, RegionType
from pharma_di.schemas.mapping import ColumnMapping, MappingDecision, MappingStatus
from pharma_di.schemas.ocr import OcrToken
from pharma_di.validate.totals import check_totals_crossfoot, extract_totals_row, sum_canonical_field


def _tok(text, x0, y0=900, w=60, h=20, conf=0.95):
    return OcrToken(text=text, bbox=BBox(x0=x0, y0=y0, x1=x0 + w, y1=y0 + h), confidence=conf)


def _band(path, x0, x1):
    return ColumnBand(header=HeaderNode(path=path, bbox=BBox(x0=x0, y0=0, x1=x1, y1=20)), x0=x0, x1=x1)


def _decision(field, combine=None):
    return MappingDecision(
        source_header=HeaderNode(path=[field], bbox=BBox(x0=0, y0=0, x1=1, y1=1)),
        canonical_field=field,
        status=MappingStatus.exact,
        combine=combine,
    )


def _totals_region():
    return Region(region_type=RegionType.totals, bbox=BBox(x0=0, y0=880, x1=1000, y1=920))


# --- extract_totals_row --------------------------------------------------------


def test_extract_totals_row_reads_printed_value_per_column():
    columns = [_band(["Product"], 0, 200), _band(["Opening", "Qty."], 200, 400)]
    mapping = ColumnMapping(decisions=[_decision("product_name_raw"), _decision("opening_quantity")])
    tokens = [_tok("TOTAL", 0), _tok("19964", 250)]
    printed = extract_totals_row(tokens, _totals_region(), columns, mapping)
    assert printed == {"opening_quantity": 19964.0}


def test_extract_totals_row_skips_a_column_with_more_than_one_numeric_token_on_the_totals_line():
    # Real doc6.jpg case: RECEIPT QTY's totals-cell has two numeric tokens
    # ("50" and "370") on the SAME identified totals line — genuinely
    # ambiguous which one (if either) is the real total, so the field must
    # be skipped entirely rather than guessing via token order. Both
    # tokens are placed on the "TOTAL" anchor's own line (same y) so this
    # actually exercises the per-column ambiguity check, not just "no
    # totals line was found at all."
    columns = [_band(["Receipt", "Qty"], 0, 400)]
    mapping = ColumnMapping(decisions=[_decision("received_quantity")])
    tokens = [_tok("TOTAL", 0, y0=900), _tok("50", 100, y0=900), _tok("370", 110, y0=900)]
    assert extract_totals_row(tokens, _totals_region(), columns, mapping) == {}


def test_extract_totals_row_returns_empty_when_no_line_matches_the_totals_anchor():
    columns = [_band(["Opening", "Qty."], 0, 400)]
    mapping = ColumnMapping(decisions=[_decision("opening_quantity")])
    tokens = [_tok("19964", 100)]  # no "TOTAL"-style anchor anywhere
    assert extract_totals_row(tokens, _totals_region(), columns, mapping) == {}


# A synthetic test for "a contaminating line above the real totals line
# gets excluded" was tried and dropped here: with only a handful of tokens
# spread across a narrow x-range, cluster_into_lines' slope auto-fit has too
# little signal to reliably separate two close y-bands the way it does on
# doc6.jpg's real ~1000px-wide, 10-token totals region (confirmed directly
# — see IMPLEMENTATION_PLAN.md's P7 build notes) — a synthetic case would
# only be testing whatever slope the fitter happens to find for that
# specific handful of points, not the behavior this function actually
# relies on. That real behavior is covered by
# tests/integration/test_validate_real_images.py instead, against real
# geometry, rather than by an unrealistic, fragile synthetic reproduction.


def test_extract_totals_row_ignores_tokens_outside_the_region_bbox():
    columns = [_band(["Opening", "Qty."], 0, 400)]
    mapping = ColumnMapping(decisions=[_decision("opening_quantity")])
    tokens = [_tok("19964", 100, y0=100)]  # far above the totals region's y-range
    assert extract_totals_row(tokens, _totals_region(), columns, mapping) == {}


def test_extract_totals_row_ignores_non_numeric_tokens():
    columns = [_band(["Product"], 0, 200), _band(["Opening", "Qty."], 200, 400)]
    mapping = ColumnMapping(decisions=[_decision("product_name_raw"), _decision("opening_quantity")])
    tokens = [_tok("TOTAL", 0)]  # sits in the product_name_raw column, not numeric
    assert extract_totals_row(tokens, _totals_region(), columns, mapping) == {}


def test_extract_totals_row_skips_unresolved_columns():
    columns = [_band(["Dump", "Qty"], 0, 400)]
    mapping = ColumnMapping(decisions=[MappingDecision(source_header=columns[0].header, canonical_field=None, status=MappingStatus.unresolved)])
    tokens = [_tok("500", 100)]
    assert extract_totals_row(tokens, _totals_region(), columns, mapping) == {}


# --- sum_canonical_field ---------------------------------------------------------


def test_sum_canonical_field_sums_present_values():
    rows = [{"opening_quantity": 16}, {"opening_quantity": 72}, {"opening_quantity": 45}]
    assert sum_canonical_field(rows, "opening_quantity") == 133


def test_sum_canonical_field_returns_none_when_no_row_has_it():
    rows = [{"opening_quantity": None}, {"opening_quantity": None}]
    assert sum_canonical_field(rows, "opening_quantity") is None


def test_sum_canonical_field_skips_none_rows_but_sums_the_rest():
    rows = [{"opening_quantity": 16}, {"opening_quantity": None}]
    assert sum_canonical_field(rows, "opening_quantity") == 16


# --- check_totals_crossfoot -----------------------------------------------------


def test_totals_crossfoot_passes_on_the_real_doc6_figure():
    # Real, hand-verified doc6.jpg value (CLAUDE.md finding #3): the sum of
    # 14 real OPENING QTY cells is exactly 19,964, matching the printed total.
    results = check_totals_crossfoot({"opening_quantity": 19964.0}, {"opening_quantity": 19964.0}, tolerance_abs=0.01)
    assert len(results) == 1
    assert results[0].passed is True


def test_totals_crossfoot_fails_outside_tolerance():
    results = check_totals_crossfoot({"opening_quantity": 19964.0}, {"opening_quantity": 19960.0}, tolerance_abs=0.01)
    assert results[0].passed is False


def test_totals_crossfoot_skips_field_with_no_real_row_data():
    results = check_totals_crossfoot({"opening_quantity": 19964.0}, {}, tolerance_abs=0.01)
    assert results == []
