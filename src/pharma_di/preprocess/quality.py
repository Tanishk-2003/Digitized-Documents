"""Quality gate (IMPLEMENTATION_PLAN.md section 4.1): runs after
preprocessing and decides whether a page is fit for OCR at all. A page that
fails is NOT passed to OCR — it goes to the review queue with a
machine-readable reason (`poor_capture` / `page_truncated`), rather than
silently producing a plausible-looking wrong extraction downstream.

`content_touches_edge` is the concrete mechanism for the doc3.jpg case: that
photograph is physically cropped mid-cell at the right edge of the table
("CLOSING VALUE[PT..." truncated) — there is no white margin between the
printed content and the photo's own border on that side. A properly-framed
photo has a blank/background margin on all four sides; ink running flush to
the frame edge is the signal that content was cut off, not photographed.
"""
from __future__ import annotations

import numpy as np

try:
    import cv2
except ImportError as e:  # pragma: no cover
    raise ImportError("opencv-python-headless is required for preprocess.quality") from e

from pharma_di.schemas.preprocess import PageQualityResult


def blur_variance(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def contrast_std(gray: np.ndarray) -> float:
    return float(gray.std())


def _looks_like_cutoff_text(
    band: np.ndarray,
    min_components: int = 3,
    max_component_area_frac: float = 0.15,
    min_small_component_ink_fraction: float = 0.4,
) -> bool:
    """Distinguish genuine cut-off printed content (many small, separate ink
    marks — individual characters/digits, together making up MOST of the
    ink in the band) from a background object sitting near the frame edge
    (a laptop edge, a UI toolbar banner, a strip of desk/shadow — one or two
    large blobs, possibly with a few small noise specks on top).

    Requiring both a minimum *count* of small components AND that they carry
    a meaningful *share* of the band's ink area is what this needs: doc5.jpg
    (a MARG print-preview screenshot, not a clean photo) has a toolbar banner
    at the top and a shadow band at the bottom, each a large dominant blob
    that also happens to have a handful of small noise specks nearby — count
    alone called that "text-like"; requiring the small marks to actually
    dominate the band's ink area correctly rejects it.
    """
    band_u8 = (band * 255).astype(np.uint8)
    n_labels, _, stats, _ = cv2.connectedComponentsWithStats(band_u8, connectivity=8)
    if n_labels <= 1:  # no ink at all
        return False

    band_area = band.shape[0] * band.shape[1]
    areas = stats[1:, cv2.CC_STAT_AREA]  # exclude background label 0
    total_ink_area = float(areas.sum())
    if total_ink_area <= 0:
        return False

    small_components = areas[areas < max_component_area_frac * band_area]
    small_ink_area = float(small_components.sum())

    return len(small_components) >= min_components and (small_ink_area / total_ink_area) >= min_small_component_ink_fraction


def content_touches_edge(
    gray: np.ndarray,
    edge_band_frac: float,
    density_threshold: float,
    require_text_like_shape: bool = True,
) -> dict[str, bool]:
    """For each of the 4 sides, check whether ink density in a thin band along
    that edge exceeds `density_threshold` AND (when `require_text_like_shape`)
    that ink is shaped like cut-off text rather than a single background
    object — i.e. content runs flush to the frame border rather than fading
    into a blank margin, and it looks like real printed content doing it."""
    h, w = gray.shape[:2]
    _, ink = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    band_h = max(1, int(h * edge_band_frac))
    band_w = max(1, int(w * edge_band_frac))

    def density(region: np.ndarray) -> float:
        return float(region.mean()) if region.size else 0.0

    bands = {
        "top": ink[0:band_h, :],
        "bottom": ink[h - band_h : h, :],
        "left": ink[:, 0:band_w],
        "right": ink[:, w - band_w : w],
    }

    result: dict[str, bool] = {}
    for side, region in bands.items():
        dense = density(region) > density_threshold
        if dense and require_text_like_shape:
            dense = _looks_like_cutoff_text(region)
        result[side] = dense
    return result


def assess_quality(
    gray: np.ndarray,
    *,
    detected_skew_deg: float,
    residual_skew_deg: float,
    boundary_found: bool,
    min_blur_variance: float,
    min_contrast_std: float,
    max_residual_skew_deg: float,
    edge_band_frac: float,
    content_edge_density_threshold: float,
) -> PageQualityResult:
    blur = blur_variance(gray)
    contrast = contrast_std(gray)
    edges = content_touches_edge(gray, edge_band_frac, content_edge_density_threshold)

    reasons: list[str] = []
    if blur < min_blur_variance:
        reasons.append("blurry")
    if contrast < min_contrast_std:
        reasons.append("low_contrast")
    if abs(residual_skew_deg) > max_residual_skew_deg:
        reasons.append("residual_skew_exceeds_threshold")
    if any(edges.values()):
        reasons.append("page_truncated")

    return PageQualityResult(
        blur_variance=blur,
        contrast_std=contrast,
        detected_skew_deg=detected_skew_deg,
        residual_skew_deg=residual_skew_deg,
        corners_in_frame=boundary_found,
        content_touches_edge=edges,
        passed=len(reasons) == 0,
        reasons=reasons,
    )
