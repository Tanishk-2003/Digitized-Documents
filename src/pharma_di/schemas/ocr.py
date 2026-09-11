"""Stage boundary: OCR output.

Populated by the P2 OCR stage (PaddleOCR). Every downstream stage that touches
text works through OcrToken/OcrPage, not raw PaddleOCR output — so PaddleOCR
can be swapped without touching layout/mapping code, and every token carries
the per-token confidence the CLAUDE.md checklist requires ("per-field
extraction_confidence, not just per-row").
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class BBox(BaseModel):
    """Axis-aligned pixel bounding box in the *preprocessed* image's coordinate
    frame (i.e. after dewarp/deskew — see preprocess stage)."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


class OcrToken(BaseModel):
    """One recognized text token with its box and confidence."""

    text: str
    bbox: BBox
    confidence: float = Field(ge=0.0, le=1.0)


class OcrPage(BaseModel):
    """All tokens recognized on one page, plus the image metadata needed to
    trace every downstream row back to its source (checklist: every row
    carries source_document/page_number)."""

    source_file: str
    page_number: int = Field(ge=1)
    image_width: int
    image_height: int
    tokens: list[OcrToken] = Field(default_factory=list)
