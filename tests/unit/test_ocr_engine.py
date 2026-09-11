"""P2: tests for the pure/fast parts of paddle_engine.py — the resize helper
and env-var setup. Does NOT invoke a real PaddleOCR prediction (that's slow
in this environment — see the module docstring — and is covered instead by
tests/integration/test_ocr_real_images.py against the pre-warmed cache).
"""
from __future__ import annotations

import os

import cv2
import numpy as np
import pytest

from pharma_di.ocr.paddle_engine import _load_for_ocr


def test_mkldnn_disabled_by_default_env_var():
    # Importing pharma_di.ocr.paddle_engine must have set this — see the
    # module's documented PIR/oneDNN compatibility bug.
    assert os.environ.get("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT") == "False"


def test_load_for_ocr_downscales_when_too_large(tmp_path):
    img = np.full((2000, 3000), 255, dtype=np.uint8)
    path = tmp_path / "big.png"
    cv2.imwrite(str(path), img)

    result = _load_for_ocr(str(path), max_dimension_px=1500)
    h, w = result.shape[:2]
    assert max(h, w) <= 1500
    assert w / h == pytest.approx(3000 / 2000, rel=0.02)  # aspect ratio preserved


def test_load_for_ocr_leaves_small_image_unchanged(tmp_path):
    img = np.full((400, 600), 255, dtype=np.uint8)
    path = tmp_path / "small.png"
    cv2.imwrite(str(path), img)

    result = _load_for_ocr(str(path), max_dimension_px=1800)
    h, w = result.shape[:2]
    assert (h, w) == (400, 600)


def test_load_for_ocr_returns_three_channel_array(tmp_path):
    # Regression test: PaddleOCR's internal preprocessing does `h, w, c =
    # img.shape`, which crashes on a 2D grayscale array (found and fixed
    # this session — see ValueError: not enough values to unpack).
    img = np.full((300, 400), 128, dtype=np.uint8)
    path = tmp_path / "gray.png"
    cv2.imwrite(str(path), img)

    result = _load_for_ocr(str(path), max_dimension_px=1800)
    assert result.ndim == 3
    assert result.shape[2] == 3


def test_load_for_ocr_missing_file_raises_clear_error(tmp_path):
    with pytest.raises(ValueError, match="could not decode"):
        _load_for_ocr(str(tmp_path / "does_not_exist.png"), max_dimension_px=1800)
