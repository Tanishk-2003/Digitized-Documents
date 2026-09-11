"""Illumination flattening / shadow removal via large-kernel morphological
background estimation + division. This is the step the plan calls out as
mattering more than OCR engine choice for photos like doc5.jpg/doc6.jpg,
which have visible fold-shadow gradients across the page.

Standard technique: a morphological close with a kernel much larger than any
character erases the text/fine detail and leaves an estimate of the
slowly-varying background illumination; dividing the original by that
estimate cancels the gradient while preserving local (text) contrast.
"""
from __future__ import annotations

import numpy as np

try:
    import cv2
except ImportError as e:  # pragma: no cover
    raise ImportError("opencv-python-headless is required for preprocess.illumination") from e


def flatten_illumination(gray: np.ndarray, kernel_frac: float = 0.10) -> np.ndarray:
    h, w = gray.shape[:2]
    k = int(max(h, w) * kernel_frac)
    k = max(k | 1, 3)  # odd, >= 3

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)

    background_f = np.clip(background.astype(np.float32), 1.0, 255.0)
    normalized = (gray.astype(np.float32) / background_f) * 255.0
    normalized = np.clip(normalized, 0, 255).astype(np.uint8)
    return normalized


def local_uniformity_std(gray: np.ndarray, block: int = 32) -> float:
    """Diagnostic metric: std-dev of block-mean intensities. Large-scale
    shadow gradients raise this; a well-flattened page has a low value. Used
    to report a real before/after shadow-removal number, not just claim it
    worked."""
    h, w = gray.shape[:2]
    means = []
    for y in range(0, h - block, block):
        for x in range(0, w - block, block):
            means.append(float(gray[y : y + block, x : x + block].mean()))
    if not means:
        return 0.0
    return float(np.std(means))
