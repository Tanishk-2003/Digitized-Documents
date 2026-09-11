"""Shared line-clustering machinery for sections 4.4 (row assembly) and 4.5
(header reconstruction) — both need the same thing: group tokens into
"lines" that may not be horizontal.

Grounded in real data, not just anticipated risk: inspecting doc6.jpg's
cached OCR tokens during development showed the header row's own
sub-columns (QTY/VALUE under OPENING/RECEIPT/ISSUE/CLOSING) drift in y by
~85px as x increases across the row — a real, measurable local slope,
distinct from the page's already-corrected global skew (P1's deskew fixes
one global angle; dewarp declined to touch doc6's residual local curvature,
`fit_not_confident` — see preprocess/dewarp.py). Naive "cluster by absolute
y-range" would silently merge or split the wrong tokens here. Fitting the
slope locally (Theil-Sen, resistant to the outliers curvature produces) and
clustering by perpendicular distance to that fitted family of lines is what
both 4.4 and 4.5 specify, and this module is where it lives once, not
duplicated.
"""
from __future__ import annotations

import numpy as np

from pharma_di.schemas.ocr import OcrToken


def theil_sen_slope(points: list[tuple[float, float]], max_abs_slope: float | None = None) -> float:
    """Robust slope (dy/dx) via Theil-Sen: the median of all pairwise
    slopes. Resistant to the handful of tokens curvature/misdetection push
    off the true line — a simple least-squares fit is not.

    `max_abs_slope`, when given, discards pairs whose *implied slope*
    exceeds this bound. Filtering on raw dy doesn't work here: within a row,
    a large x-distance genuinely produces a large dy when there's real
    curvature — that's what a slope IS — so a same-row pair spanning most of
    a wide table can have dy well over one row's own spacing. Found on
    doc6.jpg: filtering by a small absolute dy threshold (an earlier version
    of this function) excluded exactly the long-distance same-row pairs
    needed to estimate the slope precisely enough to separate rows only
    ~27px apart, and the resulting near-zero slope put a value 4 rows away
    from its real product. Filtering by implied-slope magnitude instead
    keeps large-dx same-row pairs (a real, gentle slope) while rejecting
    small-dx cross-row pairs (whose implied "slope" would be implausibly
    steep) — most surviving pairs are genuinely same-row, so the median is
    dominated by them even though a few coincidental cross-row pairs can
    still pass the filter.
    """
    n = len(points)
    if n < 2:
        return 0.0
    slopes: list[float] = []
    for i in range(n):
        x1, y1 = points[i]
        for j in range(i + 1, n):
            x2, y2 = points[j]
            dx = x2 - x1
            if abs(dx) > 1e-6:
                slope = (y2 - y1) / dx
                if max_abs_slope is None or abs(slope) <= max_abs_slope:
                    slopes.append(slope)
    if not slopes:
        return 0.0
    return float(np.median(slopes))


def rotated_y(cx: float, cy: float, slope: float) -> float:
    """Project (cx, cy) onto the axis perpendicular to a line of the given
    slope. Used both to order/cluster tokens into lines and, un-normalized,
    as a fast proxy during clustering (exact perpendicular distance is used
    separately where the design calls for a real distance — see
    perpendicular_distance)."""
    return cy - slope * cx


def perpendicular_distance(cx: float, cy: float, slope: float, intercept: float) -> float:
    """True perpendicular distance from (cx, cy) to the line y = slope*x + intercept."""
    return abs(cy - slope * cx - intercept) / float(np.sqrt(1 + slope**2))


def cluster_into_lines(
    tokens: list[OcrToken],
    slope: float | None = None,
    gap_frac: float = 0.55,
) -> tuple[list[list[OcrToken]], float]:
    """Group tokens into lines (top-to-bottom, tokens within a line ordered
    left-to-right), using a shared slope fit once across all the tokens
    given. Returns (lines, slope_used).

    `gap_frac` is the minimum gap between consecutive tokens' rotated-y,
    relative to the median token height, before a new line starts — tuned
    so normal row-to-row spacing splits cleanly while sub-column headers on
    a genuinely single (if sloped) line stay together.
    """
    if not tokens:
        return [], 0.0

    centroids = [(t.bbox.cx, t.bbox.cy) for t in tokens]
    if slope is None:
        slope = theil_sen_slope(centroids)

    heights = [t.bbox.height for t in tokens]
    median_height = float(np.median(heights)) if heights else 20.0
    gap_threshold = max(gap_frac * median_height, 4.0)

    order = sorted(range(len(tokens)), key=lambda i: rotated_y(*centroids[i], slope))

    lines_idx: list[list[int]] = [[order[0]]]
    for idx in order[1:]:
        prev_idx = lines_idx[-1][-1]
        gap = rotated_y(*centroids[idx], slope) - rotated_y(*centroids[prev_idx], slope)
        if gap > gap_threshold:
            lines_idx.append([])
        lines_idx[-1].append(idx)

    lines = [sorted((tokens[i] for i in line), key=lambda t: t.bbox.cx) for line in lines_idx]
    return lines, slope
