"""P1 integration test: run the real preprocessing pipeline against all six
real sample photographs. Assertions here are pinned to ACTUAL verified
behaviour (checked against the images by eye during development — see
IMPLEMENTATION_PLAN.md and this session's build notes), not to what the
design intended before real data was run through it. Two honest, documented
findings from that process:

  - doc4.jpg genuinely has a partial row cropped at the bottom edge of the
    photograph — content_touches_edge['bottom'] is a verified TRUE positive.
  - doc3.jpg is also genuinely truncated (its right edge cuts off mid-cell —
    "CLOSING VALUE[PT..." — see tests/fixtures/golden/doc3.json), but the
    pixel-density edge heuristic does NOT catch it: the cut column is sparse
    text with low ink density even at the true edge, unlike a solid dark
    object. This is a known false negative, not silently accepted — it is
    exactly why reliable truncation detection needs P3's table/layout
    structure (a detected table's boundary coinciding with the page
    boundary), not just P1 pixel analysis. Documented here so it isn't
    forgotten, not asserted as passing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")

from pharma_di.config import load_settings
from pharma_di.preprocess.pipeline import preprocess_document

REPO_ROOT = Path(__file__).resolve().parents[2]
INPUT_DIR = REPO_ROOT / "data" / "input"
SAMPLE_DOCS = sorted(INPUT_DIR.glob("doc*.jpg"))


@pytest.mark.parametrize("doc_path", SAMPLE_DOCS, ids=[p.name for p in SAMPLE_DOCS])
def test_preprocess_runs_end_to_end_on_real_document(doc_path: Path, tmp_path):
    settings = load_settings()
    result = preprocess_document(str(doc_path), settings, debug_dir=str(tmp_path / doc_path.stem))

    assert Path(result.working_image_path).exists()
    assert result.working_width > 0 and result.working_height > 0

    q = result.quality
    assert q.blur_variance > 0
    assert q.contrast_std > 0
    # residual skew should never be worse than what deskew started from —
    # the correction should not make things worse.
    assert abs(q.residual_skew_deg) <= abs(q.detected_skew_deg) + 0.5


def test_doc4_bottom_edge_truncation_is_detected():
    """Verified by direct visual inspection: doc4.jpg's photograph crops a
    partial row at the very bottom of the frame."""
    settings = load_settings()
    result = preprocess_document(str(INPUT_DIR / "doc4.jpg"), settings, debug_dir=None)
    assert result.quality.content_touches_edge["bottom"] is True
    assert result.quality.passed is False
    assert "page_truncated" in result.quality.reasons


@pytest.mark.parametrize("doc_name", ["doc1.jpg", "doc2.jpg", "doc5.jpg", "doc6.jpg"])
def test_no_false_positive_truncation_on_well_framed_documents(doc_name: str):
    """doc5.jpg and doc6.jpg both have significant background clutter
    (laptop edge, shadowed desk) once boundary detection falls back to the
    full frame — this is the regression test for that specific bug found
    and fixed this session (background objects near the frame edge must not
    be misread as cropped document content)."""
    settings = load_settings()
    result = preprocess_document(str(INPUT_DIR / doc_name), settings, debug_dir=None)
    assert not any(result.quality.content_touches_edge.values()), (
        f"{doc_name}: false-positive edge truncation — {result.quality.content_touches_edge}"
    )


def test_doc6_skew_correction_matches_independently_verified_angle():
    """doc6.jpg's true skew was independently cross-checked via Hough line
    detection on its printed rule lines during development (~-5.0 to -5.5deg
    across 12 long, consistent line segments). This pins that verified value
    so a future change to the deskew method is caught if it regresses."""
    settings = load_settings()
    result = preprocess_document(str(INPUT_DIR / "doc6.jpg"), settings, debug_dir=None)
    assert -6.0 <= result.quality.detected_skew_deg <= -4.5
    assert abs(result.quality.residual_skew_deg) < 1.0


def test_doc2_table_border_is_not_mistaken_for_the_page_boundary():
    """Regression test for a real bug found and fixed this session: doc2.jpg
    is a fully ruled grid, and its table's own high-contrast border produced
    a cleaner, more strongly-closed rectangular contour (45.9% of the frame)
    than the true page edge — at the old min_area_frac (0.15) that was
    accepted as "the boundary", silently cropping out the entire
    distributor/company header above the table (confirmed by direct visual
    inspection: "NABIN DRUG CENTRE" and "Company :ERIS LIFESCIENCE..." were
    absent from the cropped output, and correspondingly absent from OCR
    results — a real, no-op tolerant failure since the output still looked
    like a well-formed, if headerless, table).

    boundary_found=False here is the CORRECT outcome (falls back to the
    full frame, preserving the header), not a shortfall — see
    preprocess/boundary.py detect_boundary()'s docstring.
    """
    settings = load_settings()
    result = preprocess_document(str(INPUT_DIR / "doc2.jpg"), settings, debug_dir=None)
    assert result.boundary_found is False
    # And the header must actually be present in the output now — checked
    # indirectly via working image dimensions matching the full-frame
    # fallback (a table-only crop was a very different, much shorter aspect
    # ratio: 1955x777 before the fix, vs the standard working resolution).
    assert result.working_width == pytest.approx(1999, abs=5)
    assert result.working_height == pytest.approx(1499, abs=5)
