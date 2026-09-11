"""Document boundary detection: find the largest quadrilateral in the frame
and order its corners for a perspective transform.

Real samples (data/input/doc5.jpg, doc6.jpg) have cluttered backgrounds
(laptop edge, dark desk) where a clean 4-point contour may not be found at
all. That is treated as a normal outcome, not an error: callers fall back to
treating the full frame as the boundary, and the quality gate records
`corners_in_frame=False` as a diagnostic signal rather than a hard failure.
"""
from __future__ import annotations

import numpy as np

try:
    import cv2
except ImportError as e:  # pragma: no cover
    raise ImportError("opencv-python-headless is required for preprocess.boundary") from e


def order_corners(pts: np.ndarray) -> np.ndarray:
    """Order 4 points as [top-left, top-right, bottom-right, bottom-left]."""
    pts = pts.reshape(4, 2).astype(np.float32)
    ordered = np.zeros((4, 2), dtype=np.float32)

    s = pts.sum(axis=1)
    ordered[0] = pts[np.argmin(s)]  # top-left: smallest x+y
    ordered[2] = pts[np.argmax(s)]  # bottom-right: largest x+y

    diff = np.diff(pts, axis=1).flatten()
    ordered[1] = pts[np.argmin(diff)]  # top-right: smallest y-x
    ordered[3] = pts[np.argmax(diff)]  # bottom-left: largest y-x

    return ordered


def detect_boundary(gray: np.ndarray, min_area_frac: float = 0.6) -> np.ndarray | None:
    """Return ordered 4 corner points of the largest plausible document
    quadrilateral, or None if no such contour was found.

    `min_area_frac` guards against accepting a smaller contour that isn't
    actually the page — found and fixed this session: on doc2.jpg (a fully
    ruled grid), the table's own high-contrast border produced a cleaner,
    more strongly-closed rectangular contour than the true page edge (weak
    contrast against the background), and at the old default (0.15) that
    45.9%-of-frame table border was accepted as "the boundary" — silently
    cropping out the entire header (distributor/company name) above it.
    Every one of the six real samples shows the page filling nearly the
    whole frame (85%+), so 0.6 is still generous while correctly rejecting
    an inner content region. Getting this wrong is worse than it looks: the
    fallback (full camera frame) preserves all content and is what doc1/
    doc3/doc4/doc5/doc6 already run through successfully — a confident but
    wrong crop that discards real content is strictly worse than that.
    """
    h, w = gray.shape[:2]
    image_area = h * w

    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area_frac * image_area:
            continue
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
        if len(approx) == 4:
            return order_corners(approx)

    # No clean quadrilateral — fall back to the minimum-area rectangle of the
    # single largest contour, which at least degrades gracefully on a
    # non-rectangular / partially-occluded boundary rather than returning
    # nothing whenever the page isn't a perfect quad.
    largest = contours[0]
    if cv2.contourArea(largest) >= min_area_frac * image_area:
        rect = cv2.minAreaRect(largest)
        box = cv2.boxPoints(rect)
        return order_corners(box)

    return None


def full_frame_corners(width: int, height: int) -> np.ndarray:
    """The fallback boundary when no contour is found: the whole image."""
    return np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
