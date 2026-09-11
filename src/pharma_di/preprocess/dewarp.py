"""Content-adaptive curvature flattening ("dewarp").

Perspective correction (preprocess.perspective) removes camera-angle
keystone, assuming a flat page. Real samples are photographed pages with
fold creases and bow (IMPLEMENTATION_PLAN.md finding #2 — product names
visibly sit above their own row's numbers in doc1/doc4/doc6), which a single
planar homography cannot fix.

This is a lightweight heuristic, not a full mesh/3D reconstruction (that is
out of scope for a CPU-only, no-GPU-cluster MVP per CLAUDE.md's cost
constraint): locate a strong horizontal content band (the header rule, or
the densest text band) inside a global reference row, then let that band's
row position float locally within a small vertical search window across
N vertical strips. The resulting curve approximates the page's local
vertical displacement; a remap flattens it. If too few strips carry a
confident signal, dewarping is skipped rather than applied on noise.
"""
from __future__ import annotations

import numpy as np

try:
    import cv2
except ImportError as e:  # pragma: no cover
    raise ImportError("opencv-python-headless is required for preprocess.dewarp") from e


class DewarpResult:
    def __init__(self, image: np.ndarray, applied: bool, reason: str, curve_std_before: float, curve_std_after: float):
        self.image = image
        self.applied = applied
        self.reason = reason
        self.curve_std_before = curve_std_before
        self.curve_std_after = curve_std_after


def _ink_mask(gray: np.ndarray) -> np.ndarray:
    _, mask = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return mask.astype(np.float32)


def _row_coverage(ink_mask: np.ndarray, n_strips: int) -> np.ndarray:
    """For each row, the fraction of vertical strips that have *any* ink in
    that row. A true full-width rule line scores near 1.0; an ordinary text
    row (which has gaps between words/columns) scores much lower. This is
    what keeps the reference row locked onto a page-wide feature instead of
    onto whatever a single sparse column happens to be densest at."""
    h, w = ink_mask.shape
    strip_width = max(1, w // n_strips)
    coverage = np.zeros(h, dtype=np.float32)
    strip_count = 0
    for i in range(n_strips):
        x0, x1 = i * strip_width, min((i + 1) * strip_width, w)
        if x1 <= x0:
            continue
        strip_count += 1
        coverage += (ink_mask[:, x0:x1].sum(axis=1) > 0).astype(np.float32)
    if strip_count == 0:
        return coverage
    return coverage / strip_count


def _find_reference_row(
    ink_mask: np.ndarray,
    n_strips: int,
    margin_frac: float = 0.05,
    peak_window: int = 30,
    peak_core: int = 3,
) -> int | None:
    """Find a row that is both full-width (high coverage) AND a thin, isolated
    line — not a broad dark plateau. This distinguishes a real printed rule
    line from background clutter beyond the page edge: when boundary
    detection fails and perspective-correction falls back to the full camera
    frame (as happens on doc6.jpg's cluttered background), a strip of
    background below/around the page can be uniformly dark across the full
    width for dozens of consecutive rows — high coverage, but a plateau, not
    a peak. Returns None if nothing in-frame qualifies as a real line.
    """
    h, w = ink_mask.shape
    coverage = _row_coverage(ink_mask, n_strips)

    margin = int(h * margin_frac)
    lo, hi = margin, h - margin
    if hi <= lo:
        return None

    peakiness = np.zeros(h, dtype=np.float32)
    for r in range(lo, hi):
        w0, w1 = max(0, r - peak_window), min(h, r + peak_window)
        neighborhood = np.concatenate([coverage[w0 : max(w0, r - peak_core)], coverage[min(hi, r + peak_core) : w1]])
        if neighborhood.size == 0:
            continue
        peakiness[r] = coverage[r] - float(neighborhood.mean())

    score = np.zeros(h, dtype=np.float32)
    score[lo:hi] = coverage[lo:hi] * np.clip(peakiness[lo:hi], 0.0, None)

    if float(score.max()) <= 1e-6:
        return None  # nothing in-frame looks like a real full-width line
    return int(np.argmax(score))


def _trace_curve(ink_mask: np.ndarray, n_strips: int, search_band_frac: float) -> tuple[list[float], list[float]]:
    h, w = ink_mask.shape
    reference_row = _find_reference_row(ink_mask, n_strips)
    if reference_row is None:
        return [], []
    band = max(4, int(h * search_band_frac))

    strip_width = max(1, w // n_strips)
    xs: list[float] = []
    ys: list[float] = []

    for i in range(n_strips):
        x0, x1 = i * strip_width, min((i + 1) * strip_width, w)
        if x1 <= x0:
            continue
        y0 = max(0, reference_row - band)
        y1 = min(h, reference_row + band)
        strip = ink_mask[y0:y1, x0:x1]
        if strip.sum() < 5:  # essentially empty strip (gutter / margin) — no usable signal
            continue
        row_density = strip.sum(axis=1)
        local_peak = int(np.argmax(row_density)) + y0
        xs.append((x0 + x1) / 2)
        ys.append(float(local_peak))

    return xs, ys


def _reject_outliers(xs: np.ndarray, ys: np.ndarray, mad_multiplier: float = 4.0) -> tuple[np.ndarray, np.ndarray]:
    """Fit once, drop strips whose traced point is a large outlier from that
    fit (a sparse column locking onto the wrong local peak, as opposed to
    real smooth page curvature), refit on the rest. This is the direct fix
    for the failure seen on doc6.jpg: the product-name column's sparse text
    rows pulled the naive fit off the real (numeric-grid-confirmed) curve."""
    coeffs = np.polyfit(xs, ys, deg=2)
    residuals = ys - np.polyval(coeffs, xs)
    mad = float(np.median(np.abs(residuals - np.median(residuals)))) + 1e-6
    threshold = max(3.0, mad_multiplier * mad)
    inliers = np.abs(residuals) <= threshold
    return xs[inliers], ys[inliers]


def flatten_curvature(
    image: np.ndarray,
    gray: np.ndarray,
    n_strips: int = 24,
    search_band_frac: float = 0.08,
    min_valid_strips: int = 8,
    max_shift_frac: float = 0.06,
) -> DewarpResult:
    """Flatten local page curvature. Returns the (possibly unchanged) image
    plus a DewarpResult recording whether a correction was actually applied
    and why, so a failed/skipped attempt is visible, not silent."""
    h, w = gray.shape[:2]
    mask = _ink_mask(gray)
    xs, ys = _trace_curve(mask, n_strips, search_band_frac)

    if len(xs) < min_valid_strips:
        return DewarpResult(image, applied=False, reason="insufficient_strip_signal", curve_std_before=0.0, curve_std_after=0.0)

    xs_arr = np.array(xs)
    ys_arr = np.array(ys)
    curve_std_before = float(ys_arr.std())

    # Drop strips whose traced point doesn't fit a smooth curve through the
    # rest (sparse-column noise, not real curvature) before fitting for real.
    xs_in, ys_in = _reject_outliers(xs_arr, ys_arr)
    if len(xs_in) < min_valid_strips:
        return DewarpResult(image, applied=False, reason="too_few_inlier_strips_after_outlier_rejection", curve_std_before=curve_std_before, curve_std_after=curve_std_before)

    # Degree-2 fit: enough to capture a single fold/bow, not so flexible it
    # chases noise in a handful of sparse strips.
    coeffs = np.polyfit(xs_in, ys_in, deg=2)
    fitted = np.polyval(coeffs, xs_in)
    residual_std = float((ys_in - fitted).std())
    inlier_std = float(ys_in.std())

    # If the fit doesn't actually explain the (now outlier-cleaned) strip
    # signal, or there's barely any curve to correct, skip rather than warp
    # on noise — a wrong warp is strictly worse than no warp here.
    if inlier_std < 2.0 or residual_std > 0.5 * inlier_std:
        return DewarpResult(image, applied=False, reason="fit_not_confident", curve_std_before=curve_std_before, curve_std_after=curve_std_before)

    full_x = np.arange(w)
    full_curve = np.polyval(coeffs, full_x)
    baseline = float(np.median(full_curve))
    shift = full_curve - baseline

    max_shift_px = max_shift_frac * h
    shift = np.clip(shift, -max_shift_px, max_shift_px)

    map_x, map_y = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    map_y = map_y + shift.astype(np.float32)[np.newaxis, :]

    border_value = 255 if image.ndim == 2 else (255, 255, 255)
    warped = cv2.remap(image, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderValue=border_value)

    # Re-measure the curve on the warped result to report a real before/after number.
    warped_gray = warped if warped.ndim == 2 else cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    mask_after = _ink_mask(warped_gray)
    _, ys_after = _trace_curve(mask_after, n_strips, search_band_frac)
    curve_std_after = float(np.std(ys_after)) if len(ys_after) >= min_valid_strips else curve_std_before

    return DewarpResult(warped, applied=True, reason="ok", curve_std_before=curve_std_before, curve_std_after=curve_std_after)
