"""P3 unit tests for layout/columns.py — column band inference
(IMPLEMENTATION_PLAN.md section 4.3)."""
from __future__ import annotations

from pharma_di.layout.columns import is_numeric, _is_pack_like, infer_column_bands
from pharma_di.schemas.layout import HeaderNode
from pharma_di.schemas.ocr import BBox, OcrToken


def _tok(text, x0, y0=400, w=60, h=20, conf=0.95):
    return OcrToken(text=text, bbox=BBox(x0=x0, y0=y0, x1=x0 + w, y1=y0 + h), confidence=conf)


def _header(path, x0, x1, y0=300):
    return HeaderNode(path=path, bbox=BBox(x0=x0, y0=y0, x1=x1, y1=y0 + 30))


# --- is_numeric: thousands-grouping, not blind comma-stripping -------------


def test_is_numeric_accepts_plain_decimals():
    assert is_numeric("408.86")
    assert is_numeric("0.00")
    assert is_numeric("19964")


def test_is_numeric_accepts_proper_thousands_grouping():
    assert is_numeric("19,561")
    assert is_numeric("120,129.53")


def test_is_numeric_rejects_garbled_pack_code():
    # Real OCR noise, doc6.jpg: "10'S" misread as "10,8" — a comma followed
    # by a single digit is not valid thousands-grouping.
    assert not is_numeric("10,8")


def test_is_numeric_rejects_non_numeric_text():
    assert not is_numeric("COSKLOT")
    assert not is_numeric("")


# --- _is_pack_like ------------------------------------------------------------


def test_is_pack_like_matches_observed_real_pack_codes():
    for code in ["10'S", "1X10", "20ML", "1X14g", "1X5GM", "1x1", "1X1.5ml", "10TABS."]:
        assert _is_pack_like(code), f"{code!r} should be recognized as pack-like"


def test_is_pack_like_matches_ocr_garbled_apostrophe_as_comma():
    assert _is_pack_like("10,8")  # "10'S" misread


def test_is_pack_like_rejects_plain_decimals():
    assert not _is_pack_like("408.86")
    assert not _is_pack_like("0.00")


def test_is_pack_like_rejects_multi_word_text():
    assert not _is_pack_like("ITEM DESCRIPTION")


# --- infer_column_bands: the PACK/RATE split regression ----------------------


def test_infer_column_bands_splits_unlabeled_pack_column_from_rate():
    """Regression test for a real bug found on doc6.jpg: the MARG format has
    an unlabeled pack-code column between the product description and RATE
    — with column bands built one-per-header-leaf, that column has no
    header to attach to and its tokens were silently absorbed into RATE,
    mixing pack codes ("1X10") and rate decimals ("408.86") in one band —
    which then corrupted every downstream row-alignment estimate that used
    that band (not just the pack/rate values themselves)."""
    headers = [
        _header(["ITEM DESCRIPTION"], 0, 300),
        _header(["RATE"], 300, 650),
    ]
    body_tokens = []
    for i in range(5):
        y = 400 + i * 30
        body_tokens.append(_tok(f"COSKLOT-{i}", 10, y, w=200))
        body_tokens.append(_tok("1X10", 340, y, w=50))  # pack, close to RATE's left edge
        body_tokens.append(_tok(f"{200 + i}.50", 560, y, w=60))  # rate, close to RATE's right edge

    bands = infer_column_bands(headers, body_tokens, page_x0=0, page_x1=650)
    paths = [b.header.path for b in bands]
    assert ["PACK"] in paths, f"expected a split-out PACK column, got bands: {paths}"

    pack_band = next(b for b in bands if b.header.path == ["PACK"])
    rate_band = next(b for b in bands if b.header.path == ["RATE"])
    assert pack_band.x1 <= rate_band.x0, "PACK must be fully to the left of the narrowed RATE band"


def test_infer_column_bands_does_not_split_when_no_pack_codes_present():
    # A column with only plain numeric values should never get an
    # unnecessary PACK split.
    headers = [_header(["ITEM DESCRIPTION"], 0, 300), _header(["RATE"], 300, 650)]
    body_tokens = [_tok(f"COSKLOT-{i}", 10, 400 + i * 30, w=200) for i in range(5)]
    body_tokens += [_tok(f"{200+i}.50", 400, 400 + i * 30, w=60) for i in range(5)]
    bands = infer_column_bands(headers, body_tokens, page_x0=0, page_x1=650)
    assert [b.header.path for b in bands] == [["ITEM DESCRIPTION"], ["RATE"]]


def test_infer_column_bands_returns_empty_for_no_headers():
    assert infer_column_bands([], [], 0, 100) == []


def test_infer_column_bands_one_band_per_header_leaf():
    headers = [_header(["A"], 0, 100), _header(["B"], 200, 300), _header(["C"], 400, 500)]
    bands = infer_column_bands(headers, [], page_x0=0, page_x1=600)
    assert len(bands) == 3
