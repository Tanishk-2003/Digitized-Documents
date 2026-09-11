"""Denoise + final binarization.

fastNlMeansDenoising gives the best quality but is too slow to run
comfortably on every document at full camera resolution; at the pipeline's
working resolution (settings.preprocess.max_dimension_px, default 2000px
longest side) it runs in about a second and is worth the quality.
"""
from __future__ import annotations

import numpy as np

try:
    import cv2
except ImportError as e:  # pragma: no cover
    raise ImportError("opencv-python-headless is required for preprocess.denoise") from e


def denoise(gray: np.ndarray, h: float = 7.0) -> np.ndarray:
    return cv2.fastNlMeansDenoising(gray, None, h=h, templateWindowSize=7, searchWindowSize=21)


def adaptive_threshold(gray: np.ndarray, block_size: int = 35, c: int = 15) -> np.ndarray:
    block_size = block_size | 1  # must be odd
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block_size, c
    )
