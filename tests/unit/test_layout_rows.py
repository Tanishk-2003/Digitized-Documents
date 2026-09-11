"""P3 unit tests for layout/rows.py — sloped-baseline row assembly
(IMPLEMENTATION_PLAN.md section 4.4).

The synthetic table below deliberately reproduces the real failure mode
found on doc6.jpg: curvature that is NOT well-approximated by a single
global slope (steeper further from the seed column than near it), which is
exactly what defeated a linear model and then a quadratic one before the
column-by-column local-hop approach (this module) got it right.
"""
from __future__ import annotations

from pharma_di.layout.columns import infer_column_bands
from pharma_di.layout.headers import reconstruct_headers
from pharma_di.layout.rows import assign_rows, is_section_label_row
from pharma_di.schemas.ocr import BBox, OcrToken


def _tok(text, x0, y0, w=60, h=20, conf=0.95):
    return OcrToken(text=text, bbox=BBox(x0=x0, y0=y0, x1=x0 + w, y1=y0 + h), confidence=conf)


def _build_curved_table(n_rows=6, row_spacing=27.0):
    """Product name at x~150, RATE at x~590 (local slope ~0.064), VALUE at
    x~850 (local slope ~0.099 relative to the seed) — matching the real
    measured, non-linear geometry from doc6.jpg."""
    product_tokens, rate_tokens, value_tokens = [], [], []
    base_y = 450.0
    for i in range(n_rows):
        seed_y = base_y + i * row_spacing
        product_tokens.append(_tok(f"PRODUCT-{i}", 150, seed_y, w=100))
        rate_tokens.append(_tok(f"{100+i}.50", 590, seed_y + 0.064 * (590 - 150), w=60))
        value_tokens.append(_tok(f"{1000+i*7}.00", 850, seed_y + 0.099 * (850 - 150), w=70))
    return product_tokens, rate_tokens, value_tokens


def test_assign_rows_correctly_separates_curved_far_column_values():
    products, rates, values = _build_curved_table()
    body_tokens = products + rates + values

    header_leaves = reconstruct_headers(
        [_tok("ITEM", 150, 300, w=100), _tok("RATE", 590, 300, w=60), _tok("VALUE", 850, 300, w=70)]
    )
    columns = infer_column_bands(header_leaves, body_tokens, page_x0=0, page_x1=1000)

    seed_col = columns[0]
    seed_tokens = [t for t in body_tokens if seed_col.x0 <= t.bbox.cx < seed_col.x1]
    rows = assign_rows(body_tokens, seed_tokens, columns)

    assert len(rows) == len(products)
    for i, row in enumerate(sorted(rows, key=lambda r: r.row_index)):
        row_texts = {t.text for t in row.tokens}
        assert f"PRODUCT-{i}" in row_texts
        assert f"{100+i}.50" in row_texts, f"row {i}: expected its own RATE value, got {row_texts}"
        assert f"{1000+i*7}.00" in row_texts, f"row {i}: expected its own VALUE, got {row_texts}"


def test_assign_rows_flags_genuinely_ambiguous_tokens_uncertain():
    # Three rows establish a clear, consistent flat baseline (constraining
    # the fitted slope so it can't simply bend to fit one point exactly —
    # a degenerate single-token band would let the multi-start slope search
    # "cheat" a tie by finding a slope that fits one candidate perfectly),
    # then a 4th row's value sits exactly halfway between where two
    # baselines predict it should be: genuinely ambiguous, must be flagged.
    seeds = [_tok(f"PRODUCT-{i}", 0, 400 + i * 40, w=100) for i in range(4)]
    clear_values = [_tok(f"{100+i}.00", 200, 400 + i * 40, w=60) for i in range(3)]
    ambiguous = _tok("VALUE", 200, 400 + 3 * 40 - 20)  # row 3's value, shifted to sit halfway to row 2's slot

    header_leaves = reconstruct_headers([_tok("ITEM", 0, 300, w=100), _tok("VALUE", 200, 300, w=60)])
    body_tokens = seeds + clear_values + [ambiguous]
    columns = infer_column_bands(header_leaves, body_tokens, page_x0=0, page_x1=300)
    seed_col = columns[0]
    seed_tokens = [t for t in body_tokens if seed_col.x0 <= t.bbox.cx < seed_col.x1]
    rows = assign_rows(body_tokens, seed_tokens, columns, ambiguity_margin_frac=0.5)

    flagged = [r for r in rows if id(ambiguous) in r.uncertain_tokens]
    assert len(flagged) == 1, "the ambiguous token should be flagged uncertain on whichever row claimed it"


def test_assign_rows_empty_inputs_return_no_rows():
    assert assign_rows([], [], []) == []


def test_is_section_label_row_true_when_only_seed_column_populated():
    from pharma_di.layout.rows import RowBaseline

    seed = _tok("ZORVIA HEALTHCARE LTD", 0, 400, w=200)
    row = RowBaseline(0, seed)
    assert is_section_label_row(row, seed_column_x1=250)


def test_is_section_label_row_false_when_data_cells_present():
    from pharma_di.layout.rows import RowBaseline

    seed = _tok("COSKLOT REG TAB.", 0, 400, w=200)
    row = RowBaseline(0, seed)
    row.tokens.append(_tok("16", 700, 400))  # a real data cell, well right of the seed column
    assert not is_section_label_row(row, seed_column_x1=250)
