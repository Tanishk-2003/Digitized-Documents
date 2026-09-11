"""R2 (totals cross-foot) — IMPLEMENTATION_PLAN.md section 4.7: "sum(line
items per column) == printed TOTAL row" (CLAUDE.md finding #3: doc6.jpg's
printed OPENING QTY total is 19,964, exactly matching the sum of its own
14 product rows — "a free, page-level integrity check that catches dropped
rows, duplicated rows and digit misreads... stronger than per-row checks
alone").

The totals row itself is excluded from TableGrid.cells by layout/regions.py's
own region-typing (a `totals`-typed line is a different RegionType from
`stock_table`, so stock_table_header_and_body never includes it in
body_tokens) — `extract_totals_row` re-reads it directly from the page's raw
OCR tokens plus the `totals` Region's bbox layout/regions.py already
computed, reusing layout/columns.py's own column bands (the same ones the
real table used) rather than re-inferring columns independently.

The totals Region's bbox is not always exactly one printed line — found on
doc6.jpg: it's tall enough to also catch the tail end of the last real body
row above the actual totals line, so a naive "every numeric token in this
bbox" read finds TWO values in several columns (one real total, one
contamination) with no way to tell which is which from position alone.
Fixed by re-clustering the region's own tokens into lines with
layout/baseline.py's slope-aware cluster_into_lines (the same tool P3 uses
for the header window and body rows) and keeping only the line
layout/regions.py's own `matches_totals_row` anchor check recognizes as the
real totals row — verified directly on doc6.jpg: the contaminating line
has no anchor match at all, and the real totals line's own curvature-fitted
baseline (slope ~0.047, consistent with this page's already-measured
curvature) cleanly separates it even though the two lines' tokens interleave
in raw y-position.

This is inherently a WHOLE-TABLE check, not a per-row one — R2 alone can
only say "something in this column's totals is off," not which specific row
caused it (R4's per-row rate coherence is what localizes that, per the
plan's own account: "R2 and R4 together are strong enough to localise a
single-digit OCR error"). The `validate` node attaches R2's result to every
row in the document accordingly, rather than inventing a document-level
slot in RowValidationResult's schema for a single check.
"""
from __future__ import annotations

from pharma_di.layout.baseline import cluster_into_lines
from pharma_di.layout.columns import is_numeric
from pharma_di.layout.regions import matches_totals_row
from pharma_di.schemas.layout import ColumnBand, Region
from pharma_di.schemas.mapping import ColumnMapping
from pharma_di.schemas.ocr import OcrToken
from pharma_di.schemas.validation import RuleId, RuleResult


def extract_totals_row(
    tokens: list[OcrToken], totals_region: Region, columns: list[ColumnBand], column_mapping: ColumnMapping
) -> dict[str, float]:
    """canonical_field -> printed total, for every column whose totals-row
    cell contains EXACTLY ONE real numeric value. A column with no token in
    the totals row (blank cell), an unresolved column, or a non-numeric
    cell contributes nothing — never guessed.

A column with MORE than one numeric token on the identified totals line
    also contributes nothing, rather than picking one — a defense-in-depth
    fallback for whatever the line isolation above doesn't cleanly resolve,
    never a guess.
    """
    region_tokens = [
        t
        for t in tokens
        if totals_region.bbox.x0 <= t.bbox.cx <= totals_region.bbox.x1
        and totals_region.bbox.y0 <= t.bbox.cy <= totals_region.bbox.y1
    ]
    if not region_tokens:
        return {}

    lines, _slope = cluster_into_lines(region_tokens)
    totals_lines = [line for line in lines if matches_totals_row(line)]
    if len(totals_lines) != 1:
        # Zero matches: the anchor didn't recognize any line (unexpected
        # totals-row wording) — nothing safe to extract. More than one:
        # genuinely ambiguous which line is the real total — same "don't
        # guess" reasoning as the per-column check below.
        return {}
    totals_line = totals_lines[0]

    numeric_by_column: dict[int, list[str]] = {}
    for token in totals_line:
        stripped = token.text.strip()
        if not is_numeric(stripped):
            continue
        for col_idx, column in enumerate(columns):
            if column.x0 <= token.bbox.cx < column.x1:
                numeric_by_column.setdefault(col_idx, []).append(stripped)
                break

    printed: dict[str, float] = {}
    for col_idx, values in numeric_by_column.items():
        if len(values) != 1:
            continue
        decision = column_mapping.decisions[col_idx]
        if decision.canonical_field is not None:
            printed[decision.canonical_field] = float(values[0].replace(",", ""))
    return printed


def sum_canonical_field(rows_values: list[dict[str, float | None]], field: str) -> float | None:
    """Sum of `field` across every row that has a real (non-None) value for
    it — None if NO row has one, so a missing column is never silently
    treated as summing to zero."""
    present = [v[field] for v in rows_values if v.get(field) is not None]
    if not present:
        return None
    return sum(present)


def check_totals_crossfoot(printed_totals: dict[str, float], column_sums: dict[str, float], tolerance_abs: float) -> list[RuleResult]:
    """One RuleResult per canonical field that both has a printed total AND
    has real per-row data to sum against — never fabricates a check for a
    field the totals row didn't print, or one this document has no rows for.

    A small fixed epsilon is added on top of `tolerance_abs` — found on
    doc6.jpg's real opening_value: summing 14 real two-decimal currency
    figures as binary floats gives 120129.54000000001 against a printed
    120129.53, a genuine (and unsurprising) one-paisa rounding difference
    whose float representation lands JUST outside a bare 0.01 comparison.
    The epsilon is 10,000x smaller than the default tolerance, so it
    absorbs float noise without masking a real cent-level discrepancy.
    """
    results: list[RuleResult] = []
    epsilon = 1e-6
    for field, printed in printed_totals.items():
        if field not in column_sums:
            continue
        actual_sum = column_sums[field]
        delta = actual_sum - printed
        passed = abs(delta) <= tolerance_abs + epsilon
        results.append(
            RuleResult(
                rule_id=RuleId.r2_totals_crossfoot,
                passed=passed,
                expected=printed,
                actual=actual_sum,
                delta=delta,
                detail=f"{field}: sum of line items = {actual_sum:g} vs printed total {printed:g}",
            )
        )
    return results
