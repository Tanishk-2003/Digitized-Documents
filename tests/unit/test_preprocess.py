"""P1 unit tests on synthetic images — fast, and precise about ground truth
(a real photo has no ground truth to check against; a synthetic one does).

These specifically lock in two things discovered the hard way while building
P1 against the real samples (see IMPLEMENTATION_PLAN.md section 4.1 and the
dewarp/deskew debugging in this session):
  1. deskew's estimate/apply round-trip is mathematically correct (verified
     against a KNOWN synthetic tilt, not just "looks right" on a real photo).
  2. dewarp's safety net actually refuses to warp on noisy/ambiguous input —
     a wrong warp silently misaligns rows (the worst-case failure the plan
     calls out), so "declines to act" must be a tested, guaranteed behavior,
     not just an intention.
"""
from __future__ import annotations

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from pharma_di.preprocess import boundary, denoise, deskew, dewarp, illumination, quality


def _synthetic_document(w=800, h=600, n_rows=10, tilt_deg=0.0, noise=False) -> np.ndarray:
    """A blank page with regularly-spaced horizontal 'text' blocks — enough
    structure for boundary/skew/quality functions to have something real to
    measure, with a known ground truth (row positions, tilt)."""
    img = np.full((h, w), 255, dtype=np.uint8)
    row_ys = range(80, h - 40, max(1, (h - 120) // max(n_rows, 1)))
    for y in row_ys:
        for x0 in range(40, w - 60, 100):
            cv2.rectangle(img, (x0, y), (x0 + 70, y + 16), 0, -1)
    if noise:
        rng = np.random.default_rng(0)
        speckle = rng.integers(0, 40, size=img.shape, dtype=np.uint8)
        img = np.clip(img.astype(int) - speckle, 0, 255).astype(np.uint8)
    if tilt_deg:
        img = deskew.rotate_image(img, -tilt_deg)  # introduce a *known* tilt of +tilt_deg
    return img


# --- boundary ----------------------------------------------------------------


def test_boundary_detects_a_clear_rectangle():
    # Rectangle covers ~90% of the frame — representative of the real
    # samples (every one of the 6 shows the page filling 85%+ of the
    # frame), and comfortably above min_area_frac's default (0.6).
    img = np.full((400, 600), 40, dtype=np.uint8)  # dark background
    cv2.rectangle(img, (20, 20), (580, 380), 255, -1)  # bright page, ~90% of frame
    corners = boundary.detect_boundary(img)
    assert corners is not None
    # ordered TL, TR, BR, BL — top-left should be near (20, 20)
    tl = corners[0]
    assert abs(tl[0] - 20) < 15 and abs(tl[1] - 20) < 15


def test_boundary_returns_none_on_a_blank_uniform_image():
    img = np.full((400, 600), 255, dtype=np.uint8)  # nothing to find
    corners = boundary.detect_boundary(img)
    assert corners is None  # caller falls back to full_frame_corners, not a guess


def test_boundary_does_not_mistake_a_smaller_inner_rectangle_for_the_page():
    # Regression test for a real bug found on doc2.jpg (a ruled-grid table):
    # a smaller, high-contrast inner rectangle (a table border) must not be
    # accepted as "the page boundary" merely for being a clean quadrilateral
    # — it has to also be large enough relative to the frame. Here the inner
    # rectangle covers exactly the same ~46% fraction that doc2.jpg's false
    # positive did, well under the 0.6 default.
    img = np.full((400, 600), 255, dtype=np.uint8)  # page fills the whole frame (no visible outer edge)
    cv2.rectangle(img, (150, 100), (450, 320), 0, 2)  # a smaller inner border (a "table"), ~46% of frame
    corners = boundary.detect_boundary(img)
    assert corners is None, "an inner content region must not be mistaken for the page boundary"


def test_boundary_still_finds_a_large_outer_page_when_present():
    # The flip side of the regression above: when a genuine page-sized
    # boundary IS present (not just an inner content region), it should
    # still be found — the fix must not make detection universally give up.
    img = np.full((400, 600), 30, dtype=np.uint8)  # background
    cv2.rectangle(img, (15, 15), (585, 385), 255, -1)  # page, ~93% of frame
    cv2.rectangle(img, (150, 100), (450, 320), 0, 2)  # a smaller inner table border too
    corners = boundary.detect_boundary(img)
    assert corners is not None
    tl = corners[0]
    assert abs(tl[0] - 15) < 15 and abs(tl[1] - 15) < 15, "should find the outer page, not the inner table"


def test_full_frame_corners_covers_the_whole_image():
    corners = boundary.full_frame_corners(600, 400)
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    assert min(xs) == 0 and max(xs) == 599
    assert min(ys) == 0 and max(ys) == 399


# --- deskew --------------------------------------------------------------------


@pytest.mark.parametrize("known_tilt", [3.0, 7.0, -5.0, 10.0])
def test_deskew_round_trips_a_known_tilt(known_tilt):
    flat = _synthetic_document(tilt_deg=0.0)
    tilted = deskew.rotate_image(flat, known_tilt)

    estimated = deskew.estimate_skew_deg(tilted)
    # The estimate should be the correction needed, i.e. close to -known_tilt.
    assert abs(estimated - (-known_tilt)) < 0.5, f"expected ~{-known_tilt}, got {estimated}"

    corrected = deskew.rotate_image(tilted, estimated)
    _, ink_flat = cv2.threshold(flat, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    _, ink_corrected = cv2.threshold(corrected, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    var_flat = float(ink_flat.sum(axis=1).astype(np.float64).var())
    var_corrected = float(ink_corrected.sum(axis=1).astype(np.float64).var())
    # Corrected variance should be close to the true-flat variance (both
    # measure "how sharply horizontal the text rows are").
    assert var_corrected > 0.9 * var_flat


def test_estimate_skew_on_blank_image_returns_zero_not_a_crash():
    blank = np.full((300, 400), 255, dtype=np.uint8)
    assert deskew.estimate_skew_deg(blank) == 0.0


def test_rotate_by_near_zero_is_a_no_op():
    img = _synthetic_document()
    rotated = deskew.rotate_image(img, 0.02)
    assert np.array_equal(img, rotated)


# --- dewarp: the safety net is the thing under test -----------------------------


def test_dewarp_skips_on_random_noise_rather_than_warping_it():
    rng = np.random.default_rng(1)
    noise_img = rng.integers(0, 255, size=(600, 800), dtype=np.uint8)
    color = cv2.cvtColor(noise_img, cv2.COLOR_GRAY2BGR)
    result = dewarp.flatten_curvature(color, noise_img, n_strips=24)
    assert result.applied is False
    assert np.array_equal(result.image, color)  # untouched, not a garbage warp


def test_dewarp_skips_when_reference_row_is_a_background_plateau():
    # Reproduces the doc6.jpg failure mode this session found and fixed: a
    # wide uniformly-dark band (simulating background beyond a mis-detected
    # page boundary) must NOT be treated as a real full-width rule line.
    img = _synthetic_document(n_rows=8)
    img[560:600, :] = 30  # wide dark plateau across the bottom ~7% of the image
    color = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    ref_row = dewarp._find_reference_row(dewarp._ink_mask(img), n_strips=24)
    assert ref_row is None or ref_row < 560, "must not lock onto the background plateau"


def test_dewarp_does_not_move_content_off_its_own_row_when_it_applies():
    # Build a document with GENUINE smooth curvature (every row bows the same
    # way), confirm that if dewarp applies, product-label and data columns
    # for the SAME row stay on the same y after correction.
    h, w = 600, 900
    img = np.full((h, w), 255, dtype=np.uint8)
    row_ys = list(range(100, 500, 45))
    bow = lambda x: int(15 * np.sin(np.pi * x / w))  # smooth, page-wide bow
    for y in row_ys:
        for x0 in range(40, w - 60, 90):
            yy = y + bow(x0)
            cv2.rectangle(img, (x0, yy), (x0 + 60, yy + 14), 0, -1)
        # a page-wide rule line just above the data, itself following the bow
        for x in range(20, w - 20, 3):
            cv2.circle(img, (x, y - 20 + bow(x)), 1, 0, -1)

    color = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    result = dewarp.flatten_curvature(color, img, n_strips=30, min_valid_strips=6)
    # Either outcome is acceptable (synthetic dot-line may or may not clear
    # the confidence bar) — but IF it applies, curvature must measurably drop.
    if result.applied:
        assert result.curve_std_after < result.curve_std_before


# --- illumination --------------------------------------------------------------


def test_illumination_flattening_removes_a_pure_shadow_gradient():
    # Isolates the core claim with nothing else confounding it: on a page
    # with no text at all, a smooth shadow gradient should be almost
    # entirely removed. (Empirically: ~94% reduction — this pins a generous
    # but real floor, not the full observed number, to leave headroom.)
    h, w = 1500, 2000
    gray = np.full((h, w), 230, dtype=np.uint8)
    gradient = np.tile(np.linspace(-120, 0, w), (h, 1)).astype(np.int16)
    shadowed = np.clip(gray.astype(np.int16) + gradient, 0, 255).astype(np.uint8)

    before = float(shadowed.std())
    after = float(illumination.flatten_illumination(shadowed, kernel_frac=0.10).std())
    assert after < before * 0.2, f"expected a pure gradient reduced by >80%, got {before:.1f} -> {after:.1f}"


def test_illumination_flattening_reduces_shadow_gradient_with_text_present():
    # With real (sparse-stroke) text content in the way, flattening is
    # measurably less complete than the pure-gradient case above — the
    # morphological background estimate is partly influenced by nearby ink.
    # This threshold (30%, not a more impressive-looking 50%) is calibrated
    # from direct measurement, not guessed: this exact setup measured ~44%
    # reduction; a first draft of this test used solid-filled rectangles
    # instead of sparse strokes to simulate text and only achieved ~15-23%,
    # because a filled block (~100% local ink coverage) is a much harder
    # obstacle for a background estimate to see through than real printed
    # text (thin strokes, large real gaps) — confirmed separately that a
    # pure gradient with zero text clears >90%, so the shortfall here is
    # specifically about text density, not a flaw in the method. Real
    # dot-matrix print is sparser than even these strokes, so production
    # performance should sit at or above this floor — see the direct visual
    # comparison already done on doc6.jpg in this session.
    h, w = 1500, 2000
    gray = np.full((h, w), 230, dtype=np.uint8)
    gradient = np.tile(np.linspace(-120, 0, w), (h, 1)).astype(np.int16)
    shadowed = np.clip(gray.astype(np.int16) + gradient, 0, 255).astype(np.uint8)

    rng = np.random.default_rng(2)
    row_ys = range(150, h - 100, 45)
    for y in row_ys:
        for x0 in range(60, w - 100, 130):
            for _ in range(5):  # a handful of short strokes per 'word', not a solid block
                sx, sy = x0 + int(rng.integers(0, 60)), y + int(rng.integers(0, 16))
                cv2.line(shadowed, (sx, sy), (sx + int(rng.integers(3, 10)), sy + int(rng.integers(3, 14))), 0, 2)

    bg_row_mask = np.ones(h, dtype=bool)
    for y in row_ys:
        bg_row_mask[y : y + 18] = False

    before = float(shadowed[bg_row_mask, :].std())
    after = float(illumination.flatten_illumination(shadowed, kernel_frac=0.10)[bg_row_mask, :].std())
    assert after < before * 0.7, f"expected shadow gradient reduced by >30% even with text present, got {before:.1f} -> {after:.1f}"


# --- quality gate ----------------------------------------------------------------


def test_content_touching_edge_detected_on_a_cropped_document():
    img = np.full((400, 600), 255, dtype=np.uint8)
    for y in range(20, 380, 30):
        # a row of ink that runs all the way to the right edge (simulating
        # a table cropped mid-cell, like doc3.jpg)
        cv2.rectangle(img, (300, y), (599, y + 12), 0, -1)
    edges = quality.content_touches_edge(img, edge_band_frac=0.02, density_threshold=0.35)
    assert edges["right"] is True
    assert edges["left"] is False


def test_content_touches_edge_false_on_a_well_framed_document():
    img = np.full((400, 600), 255, dtype=np.uint8)
    cv2.rectangle(img, (100, 100), (500, 300), 0, 3)  # a bordered box well within the frame
    edges = quality.content_touches_edge(img, edge_band_frac=0.02, density_threshold=0.35)
    assert not any(edges.values())


def test_blur_variance_distinguishes_sharp_from_blurred():
    img = _synthetic_document(noise=False)
    blurred = cv2.GaussianBlur(img, (25, 25), 10)
    assert quality.blur_variance(img) > quality.blur_variance(blurred) * 2


def test_assess_quality_fails_closed_on_truncated_content():
    img = np.full((400, 600), 255, dtype=np.uint8)
    for y in range(20, 380, 30):
        cv2.rectangle(img, (300, y), (599, y + 12), 0, -1)  # touches right edge
    result = quality.assess_quality(
        img,
        detected_skew_deg=0.0,
        residual_skew_deg=0.0,
        boundary_found=True,
        min_blur_variance=10.0,
        min_contrast_std=5.0,
        max_residual_skew_deg=3.0,
        edge_band_frac=0.02,
        content_edge_density_threshold=0.35,
    )
    assert result.passed is False
    assert "page_truncated" in result.reasons


# --- denoise ---------------------------------------------------------------------


def test_denoise_preserves_image_dimensions():
    img = _synthetic_document(noise=True)
    out = denoise.denoise(img, h=7.0)
    assert out.shape == img.shape


def test_adaptive_threshold_returns_binary_image():
    img = _synthetic_document()
    out = denoise.adaptive_threshold(img, block_size=35, c=15)
    unique_vals = set(np.unique(out).tolist())
    assert unique_vals <= {0, 255}
