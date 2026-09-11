"""Stage boundary: preprocessing output (P1).

CLAUDE.md: "Because the real inputs are camera photographs of folded/creased
paper (not clean scans), this stage is not optional and can affect output
quality more than the choice of OCR engine." PageQualityResult is the
"quality gate... emits a PageQuality record" object named in
IMPLEMENTATION_PLAN.md section 4.1 — a page failing it is never handed to
OCR; it goes straight to review with a machine-readable reason.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class PageQualityResult(BaseModel):
    # --- measured signals --------------------------------------------------
    blur_variance: float                      # variance of Laplacian; higher = sharper
    contrast_std: float                       # std-dev of pixel intensity
    detected_skew_deg: float                  # skew estimated before correction
    residual_skew_deg: float                  # skew estimated after deskew correction
    corners_in_frame: bool                    # a full 4-corner document boundary was found
    content_touches_edge: dict[str, bool] = Field(default_factory=dict)  # per side: top/bottom/left/right

    # --- verdict -------------------------------------------------------------
    passed: bool
    reasons: list[str] = Field(default_factory=list)   # machine-readable failure reasons, e.g. "page_truncated"


class PreprocessResult(BaseModel):
    source_file: str
    working_image_path: str          # final corrected image handed to OCR (P2)
    debug_dir: str | None = None     # where per-step debug images were written, if requested
    debug_artifacts: dict[str, str] = Field(default_factory=dict)  # step name -> file path
    quality: PageQualityResult
    boundary_found: bool
    working_width: int
    working_height: int
