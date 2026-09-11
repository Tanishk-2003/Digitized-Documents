"""PaddleOCR wrapper -> OcrPage (CLAUDE.md: "OCR (PaddleOCR) — extract text,
bounding boxes, and per-token confidence").

Known environment issue (documented, not silently worked around): on this
Windows/CPU venv, paddlepaddle 3.3.1's default oneDNN-accelerated inference
path crashes on every PP-OCRv5/v6 detection model tried
(`NotImplementedError: ConvertPirAttribute2RuntimeAttribute not support
[pir::ArrayAttribute<pir::DoubleAttribute>]`) — a PIR/oneDNN compatibility
bug, not a bug in this code. Downgrading paddlepaddle to 3.0.0 hits a
different but related PIR attribute-type error at model *load* time, so is
not a fix either. The only combination that runs correctly here disables
oneDNN (`PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=False`), which this module sets.
That path is CORRECT but SLOW without hardware acceleration. Measured on
doc6.jpg (~200 detected text regions): 2000px wide -> 609s, 1400px -> 506s,
1100px -> 556s (box count near-identical: 201 vs 202) — cost is driven by
per-region *recognition* forward-passes (~200 of them, each roughly fixed
cost on unaccelerated CPU), not by overall pixel count, so downscaling the
input is NOT an effective mitigation here and `OcrSettings.max_dimension_px`
is kept close to the P1 working resolution rather than pushed lower to chase
a speedup that doesn't materialize. The real fix needs a working
oneDNN/hardware-accelerated path — see IMPLEMENTATION_PLAN.md for the
follow-up this needs (a Linux/WSL inference host, GPU, or an upstream Paddle
fix) before any real document volume. The disk cache (ocr/cache.py) is what
makes this tolerable meanwhile: the cost is paid once per unique document.
"""
from __future__ import annotations

import os

# Must be set before paddleocr/paddlex compute their run_mode default.
os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "False")

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from pharma_di.config import Settings
from pharma_di.schemas.ocr import BBox, OcrPage, OcrToken

_ENGINE: Any = None
_ENGINE_KEY: tuple | None = None


def _get_engine(lang: str):
    """Lazy singleton: PaddleOCR model init costs several seconds and should
    happen once per process, not once per document."""
    global _ENGINE, _ENGINE_KEY
    key = (lang,)
    if _ENGINE is not None and _ENGINE_KEY == key:
        return _ENGINE

    from paddleocr import PaddleOCR

    _ENGINE = PaddleOCR(
        lang=lang,
        use_doc_orientation_classify=False,  # P1 already handles this
        use_doc_unwarping=False,             # P1 already handles this (preprocess.dewarp)
        use_textline_orientation=False,
    )
    _ENGINE_KEY = key
    return _ENGINE


def _load_for_ocr(image_path: str, max_dimension_px: int) -> np.ndarray:
    """Load the preprocessed image and, if it exceeds max_dimension_px,
    downscale further specifically for the OCR call. This gives a small
    detection-step saving, not the recognition-step fix — see this module's
    docstring for the measured evidence that downscaling barely moves total
    OCR time once enough text regions are detected."""
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"ocr: could not decode preprocessed image: {image_path}")
    h, w = img.shape[:2]
    longest = max(h, w)
    if longest > max_dimension_px:
        scale = max_dimension_px / longest
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    # PaddleOCR's internal preprocessing assumes a 3-channel array (it calls
    # img.shape expecting H,W,C) — the P1 output is single-channel grayscale,
    # so replicate it across 3 channels rather than pass a 2D array.
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def run_ocr(image_path: str, settings: Settings, source_file: str, page_number: int = 1) -> OcrPage:
    """Run PaddleOCR on a preprocessed image and return a schema-valid
    OcrPage. Every detected token is kept regardless of confidence — CLAUDE.md:
    confidence scores are first-class data for downstream stages to act on,
    never a reason to silently drop a token here.
    """
    img = _load_for_ocr(image_path, settings.ocr.max_dimension_px)
    engine = _get_engine(settings.ocr.lang)

    results = engine.predict(img)
    tokens: list[OcrToken] = []
    for result in results:
        texts = result.get("rec_texts", [])
        scores = result.get("rec_scores", [])
        boxes = result.get("rec_boxes", [])
        for text, score, box in zip(texts, scores, boxes):
            x0, y0, x1, y1 = [float(v) for v in box]
            tokens.append(
                OcrToken(
                    text=text,
                    bbox=BBox(x0=x0, y0=y0, x1=x1, y1=y1),
                    confidence=float(score),
                )
            )

    h, w = img.shape[:2]
    return OcrPage(
        source_file=source_file,
        page_number=page_number,
        image_width=w,
        image_height=h,
        tokens=tokens,
    )
