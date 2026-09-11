"""Ties sections 4.2-4.5 together into a TableGrid: find the stock_table
region's header/body split, reconstruct hierarchical headers, infer column
bands, assign rows by sloped baseline, and place every body token into a
(row, column) cell.
"""
from __future__ import annotations

from pharma_di.layout.columns import assign_token_to_column, infer_column_bands
from pharma_di.layout.headers import reconstruct_headers
from pharma_di.layout.regions import stock_table_header_and_body
from pharma_di.layout.rows import assign_rows, is_section_label_row
from pharma_di.schemas.layout import BBox, Cell, Region, RegionType, TableGrid
from pharma_di.schemas.ocr import OcrToken


def assemble_stock_table(page_tokens: list[OcrToken]) -> TableGrid | None:
    """Returns None if no stock_table region was found on the page at all —
    a legitimate outcome (e.g. a page that's entirely a purchase-detail
    block, or nothing recognizable), not an error. Callers must not force
    an empty TableGrid through downstream stages in that case."""
    header_tokens, body_tokens = stock_table_header_and_body(page_tokens)
    if not header_tokens:
        return None

    header_leaves = reconstruct_headers(header_tokens)
    if not header_leaves:
        return None

    all_relevant = header_tokens + body_tokens
    page_x0 = min(t.bbox.x0 for t in all_relevant) - 20
    page_x1 = max(t.bbox.x1 for t in all_relevant) + 20

    columns = infer_column_bands(header_leaves, body_tokens, page_x0, page_x1)
    if not columns:
        return None

    seed_column = columns[0]
    seed_tokens = [t for t in body_tokens if seed_column.x0 <= t.bbox.cx < seed_column.x1]

    if not seed_tokens:
        # No usable leftmost-column seeds to build rows from at all — flag
        # rather than silently emit a header-only, row-less table.
        region_bbox = _union_bbox([t.bbox for t in all_relevant])
        return TableGrid(
            region=Region(region_type=RegionType.stock_table, bbox=region_bbox),
            columns=columns,
            row_count=0,
            cells=[],
            header_column_count_mismatch=True,
        )

    rows = assign_rows(body_tokens, seed_tokens, columns)

    # A confirmed section-label row (no non-seed tokens even after the
    # distance cap above) still SAT IN on every hop's slope-fitting during
    # that first pass — and a phantom row's stale, never-advancing anchor
    # can pull the "lowest total residual" search toward a self-consistent
    # but wrong "shift by one row" slope alias (found on doc6.jpg: row
    # spacing / one hop's dx landed suspiciously close to one of
    # _best_hop_slope's own coarse starting guesses), corrupting a REAL
    # row's own assignment even though the phantom row's final claim was
    # correctly capped away. There's no reliable way to know ahead of time
    # which seed heads a label row (tried geometric line-span heuristics;
    # they misfire on formats with genuinely sparse real rows — see
    # layout/rows.py's assign_rows docstring), but the first pass's own
    # is_section_label_row result IS reliable, so a confirmed label from
    # pass one is excluded from slope-fitting outright in a second,
    # corrected pass — cheap (only runs when a label was actually found)
    # and doesn't touch the many documents with no section-label rows at all.
    label_seed_ids = frozenset(
        id(row.seed) for row in rows if is_section_label_row(row, seed_column.x1)
    )
    if label_seed_ids:
        rows = assign_rows(body_tokens, seed_tokens, columns, label_seed_ids=label_seed_ids)

    cells: list[Cell] = []
    section_label_rows: dict[int, str] = {}

    for row in rows:
        if is_section_label_row(row, seed_column.x1):
            label_text = " ".join(t.text for t in sorted(row.tokens, key=lambda t: t.bbox.cx)).strip()
            section_label_rows[row.row_index] = label_text
            continue

        by_column: dict[int, list[OcrToken]] = {}
        uncertain_columns: set[int] = set()
        for token in row.tokens:
            column = assign_token_to_column(token, columns)
            if column is None:
                continue
            col_idx = columns.index(column)
            by_column.setdefault(col_idx, []).append(token)
            if id(token) in row.uncertain_tokens:
                uncertain_columns.add(col_idx)

        for col_idx, column in enumerate(columns):
            cell_tokens = by_column.get(col_idx, [])
            cells.append(
                Cell(
                    row_index=row.row_index,
                    column=column.header,
                    tokens=sorted(cell_tokens, key=lambda t: t.bbox.cx),
                    row_assignment_uncertain=col_idx in uncertain_columns,
                )
            )

    region_bbox = _union_bbox([t.bbox for t in all_relevant])
    return TableGrid(
        region=Region(region_type=RegionType.stock_table, bbox=region_bbox),
        columns=columns,
        row_count=len(rows),
        cells=cells,
        header_column_count_mismatch=False,
        section_label_rows=section_label_rows,
    )


def _union_bbox(bboxes: list[BBox]) -> BBox:
    return BBox(
        x0=min(b.x0 for b in bboxes),
        y0=min(b.y0 for b in bboxes),
        x1=max(b.x1 for b in bboxes),
        y1=max(b.y1 for b in bboxes),
    )
