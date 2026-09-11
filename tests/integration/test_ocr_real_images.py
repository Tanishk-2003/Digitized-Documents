"""P2 integration test: run the real OCR stage against all six real sample
photographs, through the actual disk cache.

This is deliberately gated on the cache already being warm (see
_cache_prewarmed below) rather than computing on demand: in this
environment PaddleOCR runs without oneDNN acceleration (a documented
PIR/oneDNN compatibility bug — see ocr/paddle_engine.py), and a cold run
across 5 documents (doc4.jpg is correctly skipped by the P1 quality gate —
see test_preprocess_real_images.py) takes on the order of 45-60 minutes.
A routine `pytest` run must not silently eat that; pre-warm explicitly with:

    python scripts/run_pipeline.py --input data/input/doc1.jpg
    ... (repeat for doc2, doc3, doc5, doc6)

or the equivalent batch loop. Once warm, these tests run in seconds (cache
hits — see ocr/cache.py).

Assertions below check for real, verifiable content — exact numbers where
OCR is normally reliable, and tolerant substring matches on product/company
names where realistic dot-matrix OCR noise is expected (e.g. "COSKLOT-500
TAS" instead of "TAB" was observed during development; that is a normal,
expected error type on this input quality, not a bug to chase).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pytest

from pharma_di.config import load_settings
from pharma_di.ocr.cache import OcrCache, hash_image_file
from pharma_di.preprocess.pipeline import preprocess_document

REPO_ROOT = Path(__file__).resolve().parents[2]
INPUT_DIR = REPO_ROOT / "data" / "input"

# doc4.jpg is intentionally excluded: it fails the P1 quality gate
# (page_truncated, verified true positive) and the graph short-circuits it
# to review before OCR ever runs — see test_preprocess_real_images.py.
DOCS_REACHING_OCR = ["doc1.jpg", "doc2.jpg", "doc3.jpg", "doc5.jpg", "doc6.jpg"]


@lru_cache(maxsize=None)
def _preprocessed_hash(doc_name: str) -> str:
    """Real P1 preprocessing is deterministic (verified this session) but
    not free — a few seconds per document. Memoized so it runs at most once
    per document per test session: the module-level skip check and every
    test function that needs a document's cache key would otherwise each
    redo the same work (this was measured costing minutes across a run that
    should be all cache hits, before this fix)."""
    settings = load_settings()
    result = preprocess_document(str(INPUT_DIR / doc_name), settings, debug_dir=None)
    return hash_image_file(result.working_image_path)


def _cache_prewarmed() -> bool:
    settings = load_settings()
    cache = OcrCache(settings.ocr.cache_dir)
    return all(cache.get(_preprocessed_hash(name)) is not None for name in DOCS_REACHING_OCR)


pytestmark = pytest.mark.skipif(
    not _cache_prewarmed(),
    reason=(
        "OCR cache not pre-warmed for all 5 documents that reach OCR. "
        "Cold PaddleOCR inference in this environment runs without oneDNN "
        "acceleration and takes ~45-60 min across these documents — see "
        "ocr/paddle_engine.py. Pre-warm explicitly before running this file."
    ),
)


def _ocr_page_for(doc_name: str):
    settings = load_settings()
    cache = OcrCache(settings.ocr.cache_dir)
    page = cache.get(_preprocessed_hash(doc_name))
    assert page is not None, f"{doc_name}: expected a pre-warmed cache entry"
    return page


def _all_text_upper(page) -> str:
    return " ".join(t.text for t in page.tokens).upper()


@pytest.mark.parametrize("doc_name", DOCS_REACHING_OCR)
def test_ocr_produces_real_tokens_with_confidence(doc_name: str):
    page = _ocr_page_for(doc_name)
    assert len(page.tokens) > 5, f"{doc_name}: suspiciously few tokens recognized"
    empty_text_count = 0
    for token in page.tokens:
        assert 0.0 <= token.confidence <= 1.0
        assert token.bbox.x1 > token.bbox.x0
        assert token.bbox.y1 > token.bbox.y0
        if token.text.strip() == "":
            # A legitimate PaddleOCR outcome, found on doc1.jpg: detection
            # finds a text-shaped region but recognition can't read anything
            # in it (confidence 0.0) — e.g. a print smudge or genuinely
            # illegible fragment. This is real, useful signal (something is
            # there, unreadable), not a token to silently drop — CLAUDE.md's
            # "never drop data" applies here too. Confidence must reflect
            # that honestly: near-zero, not a confident empty guess.
            empty_text_count += 1
            assert token.confidence < 0.1, f"{doc_name}: empty-text token has suspiciously high confidence {token.confidence}"
    assert empty_text_count < len(page.tokens) * 0.1, f"{doc_name}: too many empty-text tokens ({empty_text_count}/{len(page.tokens)})"


def test_doc6_recognizes_exact_known_numbers():
    # Hand-verified against the source photograph (IMPLEMENTATION_PLAN.md
    # section 1.2, finding 4): RATE x OPENING QTY = OPENING VALUE.
    page = _ocr_page_for("doc6.jpg")
    texts = {t.text for t in page.tokens}
    for expected in ["408.86", "6541.76", "18034.08", "245.37"]:
        assert expected in texts, f"doc6.jpg: expected exact number {expected!r} not recognized"


def test_doc6_recognizes_product_names_with_tolerance_for_ocr_noise():
    page = _ocr_page_for("doc6.jpg")
    all_text = _all_text_upper(page)
    for fragment in ["COSKLOT", "MEDICO"]:
        assert fragment in all_text, f"doc6.jpg: expected fragment {fragment!r} somewhere in recognized text"


def test_doc2_recognizes_hsn_and_product_table_content():
    page = _ocr_page_for("doc2.jpg")
    texts = {t.text for t in page.tokens}
    assert "300490" in texts, "doc2.jpg: expected the HSN code 300490 to be recognized"
    all_text = _all_text_upper(page)
    assert "COSKLOT" in all_text


def test_doc2_header_is_a_known_undetected_region_not_silently_wrong():
    """Real, diagnosed limitation, not a bug: "NABIN DRUG CENTRE" /
    "Company :ERIS LIFESCIENCE..." sit exactly at a sharp paper fold crease
    (a local V-bend in the photograph, not smooth page bowing) — confirmed
    by direct visual inspection of the OCR input crop. PP-OCR's text
    DETECTION step (not recognition) finds nothing at all above y=284 in
    the working image; this is a complete miss, not garbled recognition.

    dewarp.flatten_curvature() correctly declines to touch this
    (`reason="fit_not_confident"`) rather than force a wrong correction — a
    sharp local V-fold isn't the smooth whole-page curve the heuristic
    models, and IMPLEMENTATION_PLAN.md section 4.1 already scopes dewarp as
    "a lightweight heuristic, not a full mesh/3D reconstruction". This test
    exists so the gap stays visible (a document-detection stage that can't
    find distributor/company text should itself route to review — see
    IMPLEMENTATION_PLAN.md open items) rather than silently regressing to
    "expected, ignore" the next time someone touches this file.
    """
    page = _ocr_page_for("doc2.jpg")
    header_region_tokens = [t for t in page.tokens if t.bbox.y0 < 280]
    assert header_region_tokens == [], (
        "doc2.jpg: header region now producing tokens — if this starts passing, "
        "the fold-crease detection gap may be fixed; update this test's assumption "
        "and test_doc2_recognizes_hsn_and_product_table_content instead of leaving "
        "this xfail-shaped assertion in place"
    )


def test_doc3_recognizes_summary_values():
    # doc3.jpg is the company-summary-only document (no line items) —
    # OPENING VALUE[PTS] = 109599.61.
    page = _ocr_page_for("doc3.jpg")
    texts = {t.text for t in page.tokens}
    assert "109599.61" in texts, "doc3.jpg: expected the opening value 109599.61 to be recognized"


def test_doc5_recognizes_purchase_detail_amount():
    # doc5.jpg's embedded Purchase Detail block: Amount = 9374.00.
    page = _ocr_page_for("doc5.jpg")
    texts = {t.text for t in page.tokens}
    assert "9374.00" in texts, "doc5.jpg: expected the purchase detail amount 9374.00 to be recognized"


def test_confidence_correlates_with_recognizability():
    # Not a strict causal claim — but on average, tokens that are pure
    # digits/decimals (recognized very reliably in this input, per manual
    # spot-checks during development) should score at least as high as the
    # page's overall average confidence.
    page = _ocr_page_for("doc6.jpg")
    numeric_scores = [t.confidence for t in page.tokens if t.text.replace(".", "").replace(",", "").isdigit()]
    all_scores = [t.confidence for t in page.tokens]
    assert numeric_scores, "expected at least some purely-numeric tokens on doc6.jpg"
    assert sum(numeric_scores) / len(numeric_scores) >= sum(all_scores) / len(all_scores) - 0.05
