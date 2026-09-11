"""Residual rotation (deskew) via the projection-profile-variance method:
rotate through a small angle range and pick the angle that maximizes the
variance of the horizontal row-sum profile of the ink mask — text lines
produce sharp peaks/troughs exactly when they're horizontal.

Coarse-to-fine: a wide coarse pass finds the right neighbourhood, a narrow
fine pass refines it. No line/contour detection needed, so it degrades
gracefully on the borderless dot-matrix tables (doc1/doc4/doc5/doc6) where a
contour-based skew estimate would be unreliable.
"""
from __future__ import annotations

import numpy as np

try:
    import cv2
except ImportError as e:  # pragma: no cover
    raise ImportError("opencv-python-headless is required for preprocess.deskew") from e


def _projection_variance(ink_mask: np.ndarray, angle: float) -> float:
    h, w = ink_mask.shape
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(ink_mask, matrix, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
    row_sums = rotated.sum(axis=1).astype(np.float64)
    return float(row_sums.var())


def estimate_skew_deg(gray: np.ndarray, coarse_range: float = 10.0, coarse_step: float = 1.0) -> float:
    """Return the estimated skew angle in degrees (positive = counter-clockwise
    correction needed). 0.0 if the image has too little ink to estimate from."""
    _, ink_mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    if ink_mask.sum() < 255 * 100:  # essentially blank — nothing to estimate from
        return 0.0

    coarse_angles = np.arange(-coarse_range, coarse_range + coarse_step, coarse_step)
    scores = [(_projection_variance(ink_mask, a), a) for a in coarse_angles]
    _, best_coarse = max(scores)

    fine_angles = np.arange(best_coarse - 1.0, best_coarse + 1.0 + 0.1, 0.1)
    fine_scores = [(_projection_variance(ink_mask, a), a) for a in fine_angles]
    _, best_fine = max(fine_scores)

    return round(float(best_fine), 2)


def rotate_image(image: np.ndarray, angle_deg: float) -> np.ndarray:
    if abs(angle_deg) < 0.05:
        return image
    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    border_value = 255 if image.ndim == 2 else (255, 255, 255)
    return cv2.warpAffine(image, matrix, (w, h), flags=cv2.INTER_CUBIC, borderValue=border_value)
