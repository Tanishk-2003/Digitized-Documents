"""P3 unit tests for layout/headers.py — hierarchical header reconstruction
(IMPLEMENTATION_PLAN.md section 4.5)."""
from __future__ import annotations

from pharma_di.layout.headers import is_leaf_label, reconstruct_headers
from pharma_di.schemas.ocr import BBox, OcrToken


def _tok(text, x0, y0, x1=None, y1=None, conf=0.95):
    return OcrToken(text=text, bbox=BBox(x0=x0, y0=y0, x1=x1 or x0 + 40, y1=y1 or y0 + 20), confidence=conf)


def test_is_leaf_label_matches_known_variants():
    assert is_leaf_label("QTY")
    assert is_leaf_label("qty.")
    assert is_leaf_label("VALUE")
    assert is_leaf_label("M.Exp")


def test_is_leaf_label_rejects_severely_garbled_text():
    # Real OCR noise, found on doc6.jpg: "QTY" read as "CEY" — too corrupted
    # to safely fuzzy-match (the "never guess" principle applies to header
    # structure too, not just semantic mapping).
    assert not is_leaf_label("CEY")


def test_is_leaf_label_rejects_unrelated_words():
    assert not is_leaf_label("ITEM DESCRIPTION")
    assert not is_leaf_label("RATE")
    assert not is_leaf_label("COSKLOT")


def test_reconstruct_headers_pairs_parent_and_child_by_proximity_not_overlap():
    # Reproduces the real doc6.jpg geometry: RECEIPT's own QTY sub-column
    # barely overlaps RECEIPT in x (touching by ~1px) — an overlap-based
    # match would miss this pairing; proximity-based matching finds it.
    opening = _tok("OPENING", 760, 339, 861, 383)
    opening_qty = _tok("QTY.", 704, 355, 764, 392)
    receipt = _tok("RECEIPT", 1015, 382, 1114, 412)
    receipt_qty = _tok("QTY", 966, 408, 1014, 435)  # x1=1014, receipt.x0=1015 -- touching, not overlapping

    nodes = reconstruct_headers([opening, opening_qty, receipt, receipt_qty])
    paths = {tuple(n.path) for n in nodes}
    assert ("OPENING", "QTY.") in paths
    assert ("RECEIPT", "QTY") in paths


def test_reconstruct_headers_single_line_degenerate_case():
    # doc1.jpg / doc2.jpg: no leaf labels (QTY/VALUE) at all -> every token
    # is its own single-level column.
    tokens = [_tok("Product", 0, 0), _tok("Pack", 100, 0), _tok("Opening Stock", 200, 0)]
    nodes = reconstruct_headers(tokens)
    assert len(nodes) == 3
    assert all(len(n.path) == 1 for n in nodes)


def test_reconstruct_headers_unclaimed_parent_becomes_its_own_single_level_column():
    # RATE has no QTY/VALUE children -- it's a single-level header even in
    # a table that otherwise has hierarchical columns.
    rate = _tok("RATE", 583, 306)
    opening = _tok("OPENING", 760, 339, 861, 383)
    opening_qty = _tok("QTY.", 704, 355, 764, 392)
    nodes = reconstruct_headers([rate, opening, opening_qty])
    paths = {tuple(n.path) for n in nodes}
    assert ("RATE",) in paths
    assert ("OPENING", "QTY.") in paths


def test_reconstruct_headers_empty_input():
    assert reconstruct_headers([]) == []


def test_reconstruct_headers_never_merges_two_leaves_into_one_node():
    # Two leaves (QTY appears under both OPENING and RECEIPT) must produce
    # two separate HeaderNodes, not be collapsed.
    opening = _tok("OPENING", 760, 339, 861, 383)
    opening_qty = _tok("QTY", 704, 355, 764, 392)
    receipt = _tok("RECEIPT", 1015, 382, 1114, 412)
    receipt_qty = _tok("QTY", 966, 408, 1014, 435)
    nodes = reconstruct_headers([opening, opening_qty, receipt, receipt_qty])
    assert len(nodes) == 2
    assert len(set(id(n) for n in nodes)) == 2
