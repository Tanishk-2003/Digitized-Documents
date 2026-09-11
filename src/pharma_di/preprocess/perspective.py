"""Perspective correction: warp the detected boundary quadrilateral to a
front-on rectangle. Handles camera tilt/keystone; residual page curvature
(the paper itself bowing) is handled separately by preprocess.dewarp.
"""
from __future__ import annotations

import numpy as np

try:
    import cv2
except ImportError as e:  # pragma: no cover
    raise ImportError("opencv-python-headless is required for preprocess.perspective") from e


def correct_perspective(image: np.ndarray, corners: np.ndarray) -> np.ndarray:
    """Warp `image` so the quadrilateral `corners` (ordered TL,TR,BR,BL) maps
    to a rectangle sized from the quad's own (longest) edge lengths."""
    (tl, tr, br, bl) = corners

    width_top = np.linalg.norm(tr - tl)
    width_bottom = np.linalg.norm(br - bl)
    target_width = int(max(width_top, width_bottom))

    height_left = np.linalg.norm(bl - tl)
    height_right = np.linalg.norm(br - tr)
    target_height = int(max(height_left, height_right))

    target_width = max(target_width, 1)
    target_height = max(target_height, 1)

    dst = np.array(
        [[0, 0], [target_width - 1, 0], [target_width - 1, target_height - 1], [0, target_height - 1]],
        dtype=np.float32,
    )

    matrix = cv2.getPerspectiveTransform(corners.astype(np.float32), dst)
    warped = cv2.warpPerspective(image, matrix, (target_width, target_height))
    return warped
