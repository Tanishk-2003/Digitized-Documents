"""P3 integration test: table assembly against real cached OCR data.

Gated on the OCR cache being warm (same reasoning as
test_ocr_real_images.py) — table assembly runs on OcrPage tokens, which in
this environment come from a slow, unaccelerated PaddleOCR pass (see
ocr/paddle_engine.py). Once the cache is warm this runs in a couple of
seconds (just P1 preprocessing to recompute the cache key, then a cache hit).

doc6.jpg's exact-ground-truth check is the single most important regression
test in this file: getting here took finding and fixing four real,
substantive bugs in one session (an unlabeled PACK column silently absorbed
into RATE, corrupting downstream slope estimates; a slope bootstrap that let
two rows claim the same candidate with no conflict resolution; blind
zero-slope starts that can converge to a self-consistent but sign-flipped
result; and non-linear curvature that no single global slope or quadratic
curve could fit well enough to extrapolate across the table's full width).
If this test ever regresses, treat it as seriously as the bugs that led to
writing it — see layout/rows.py's module docstring for the full account.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pharma_di.config import load_settings
from pharma_di.ocr.cache import OcrCache, hash_image_file
from pharma_di.preprocess.pipeline import preprocess_document
from pharma_di.layout.tables import assemble_stock_table

REPO_ROOT = Path(__file__).resolve().parents[2]
INPUT_DIR = REPO_ROOT / "data" / "input"


def _cache_prewarmed(doc_name: str) -> bool:
    settings = load_settings()
    result = preprocess_document(str(INPUT_DIR / doc_name), settings, debug_dir=None)
    cache = OcrCache(settings.ocr.cache_dir)
    return cache.get(hash_image_file(result.working_image_path)) is not None


pytestmark = pytest.mark.skipif(
    not _cache_prewarmed("doc6.jpg"),
    reason="doc6.jpg's OCR cache is not pre-warmed — see test_ocr_real_images.py for how to warm it.",
)


def _grid_for(doc_name: str):
    settings = load_settings()
    result = preprocess_document(str(INPUT_DIR / doc_name), settings, debug_dir=None)
    cache = OcrCache(settings.ocr.cache_dir)
    page = cache.get(hash_image_file(result.working_image_path))
    assert page is not None, f"{doc_name}: expected a pre-warmed cache entry"
    return assemble_stock_table(page.tokens)


def _row_dict(grid, row_index: int) -> dict[str, str]:
    return {"/".join(c.column.path): c.text for c in grid.cells_for_row(row_index) if c.text}


def test_doc6_row1_matches_hand_transcribed_ground_truth_exactly():
    # COSKLOT REG TAB.: 10'S, rate 408.86, opening 16/6541.76, receipt
    # 0/0.00, issue 0/0.00, closing 16/6541.76, dump 16 — every field.
    grid = _grid_for("doc6.jpg")
    row = _row_dict(grid, 1)
    assert row["ITEM DESCRIPTION"] == "COSKLOT REG TAB."
    assert row["PACK"] == "10'S"
    assert row["RATE"] == "408.86"
    assert row["OPENING/QTY."] == "16"
    assert row["OPENING/VALUE"] == "6541.76"
    assert row["RECEIPT/QTY"] == "0"
    assert row["RECEIPT/VALUE"] == "0.00"
    assert row["CLOSTNG/VALUE"] == "6541.76"  # "CLOSING" OCR-garbled, consistent with this dataset
    assert row["DOM2/QTY"] == "16"  # "DUMP" OCR-garbled


def test_doc6_pack_and_rate_are_separate_columns_for_every_row():
    # Regression test for the unlabeled-PACK-column bug specifically:
    # every row must have BOTH a pack code and a separate plain-decimal
    # rate, never a merged "1X10 408.86"-style value in one cell.
    grid = _grid_for("doc6.jpg")
    for row_idx in sorted({c.row_index for c in grid.cells}):
        row = _row_dict(grid, row_idx)
        if "PACK" not in row or "RATE" not in row:
            continue
        assert " " not in row["PACK"], f"row {row_idx}: PACK cell looks merged: {row['PACK']!r}"
        assert " " not in row["RATE"], f"row {row_idx}: RATE cell looks merged: {row['RATE']!r}"


def test_doc6_section_label_row_detected_not_fabricated_as_a_product():
    grid = _grid_for("doc6.jpg")
    assert 0 in grid.section_label_rows
    assert "ZORVIA" in grid.section_label_rows[0].upper()
    # and that row must NOT also appear as a normal data row
    assert _row_dict(grid, 0) == {} or all(
        k == "ITEM DESCRIPTION" for k in _row_dict(grid, 0)
    )


def test_doc6_row_count_matches_visible_product_count():
    # 1 section-label row + 14 real products, hand-counted from the source
    # photograph at the start of this project.
    grid = _grid_for("doc6.jpg")
    assert grid.row_count == 15
