"""Orchestrates the full P1 preprocessing sequence (CLAUDE.md pipeline stage
1 / IMPLEMENTATION_PLAN.md section 4.1):

    load -> resize to working resolution -> boundary detect
         -> perspective correct -> dewarp (curvature) -> deskew
         -> illuminate-flatten (shadow removal) -> [quality assess]
         -> denoise -> adaptive threshold

Quality is assessed on the illumination-flattened grayscale, *before*
denoising — denoise necessarily smooths high-frequency detail, and measuring
blur/contrast after our own smoothing would score our own processing instead
of the source photo's real sharpness.

Every step's output can be written to `debug_dir` so the effect of each
stage on a real document is directly inspectable (IMPLEMENTATION_PLAN.md
section 4.1: "Every step writes a debug image ... that is how this stage
gets tuned").
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError as e:  # pragma: no cover
    raise ImportError("opencv-python-headless is required for preprocess.pipeline") from e

from pharma_di.config import Settings
from pharma_di.preprocess import boundary as boundary_mod
from pharma_di.preprocess import denoise as denoise_mod
from pharma_di.preprocess import deskew as deskew_mod
from pharma_di.preprocess import dewarp as dewarp_mod
from pharma_di.preprocess import illumination as illum_mod
from pharma_di.preprocess import quality as quality_mod
from pharma_di.preprocess import perspective as perspective_mod
from pharma_di.schemas.preprocess import PreprocessResult


def _resize_to_working(image: np.ndarray, max_dimension_px: int) -> np.ndarray:
    h, w = image.shape[:2]
    longest = max(h, w)
    if longest <= max_dimension_px:
        return image
    scale = max_dimension_px / longest
    return cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


def preprocess_document(image_path: str, settings: Settings, debug_dir: str | None = None) -> PreprocessResult:
    path = Path(image_path)
    color = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if color is None:
        raise ValueError(f"preprocess: could not decode image (unsupported/corrupt file): {path}")

    debug: dict[str, str] = {}

    def save_debug(name: str, img: np.ndarray) -> None:
        if debug_dir is None:
            return
        out_dir = Path(debug_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{name}.png"
        cv2.imwrite(str(out_path), img)
        debug[name] = str(out_path)

    p = settings.preprocess
    q = settings.quality_gate

    resized = _resize_to_working(color, p.max_dimension_px)
    save_debug("01_resized", resized)

    gray0 = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)

    corners = boundary_mod.detect_boundary(gray0, min_area_frac=p.boundary_min_area_frac)
    boundary_found = corners is not None
    if corners is None:
        h, w = gray0.shape[:2]
        corners = boundary_mod.full_frame_corners(w, h)

    warped_color = perspective_mod.correct_perspective(resized, corners)
    warped_gray = cv2.cvtColor(warped_color, cv2.COLOR_BGR2GRAY)
    save_debug("02_perspective_corrected", warped_color)

    dewarp_result = dewarp_mod.flatten_curvature(
        warped_color, warped_gray, n_strips=p.dewarp_strip_count
    )
    dewarped_color = dewarp_result.image
    dewarped_gray = cv2.cvtColor(dewarped_color, cv2.COLOR_BGR2GRAY)
    save_debug("03_dewarped", dewarped_color)

    detected_skew = deskew_mod.estimate_skew_deg(dewarped_gray)
    deskewed_color = deskew_mod.rotate_image(dewarped_color, detected_skew)
    deskewed_gray = cv2.cvtColor(deskewed_color, cv2.COLOR_BGR2GRAY)
    save_debug("04_deskewed", deskewed_color)

    residual_skew = deskew_mod.estimate_skew_deg(deskewed_gray)

    illum_gray = illum_mod.flatten_illumination(deskewed_gray, kernel_frac=p.illumination_kernel_frac)
    save_debug("05_illumination_flattened", illum_gray)

    quality = quality_mod.assess_quality(
        illum_gray,
        detected_skew_deg=detected_skew,
        residual_skew_deg=residual_skew,
        boundary_found=boundary_found,
        min_blur_variance=q.min_blur_variance,
        min_contrast_std=q.min_contrast_std,
        max_residual_skew_deg=q.max_residual_skew_deg,
        edge_band_frac=p.edge_band_frac,
        content_edge_density_threshold=q.content_edge_density_threshold,
    )

    denoised_gray = denoise_mod.denoise(illum_gray, h=p.denoise_h)
    save_debug("06_denoised", denoised_gray)

    binary = denoise_mod.adaptive_threshold(
        denoised_gray, block_size=p.adaptive_threshold_block_size, c=p.adaptive_threshold_C
    )
    save_debug("07_binary", binary)

    # Grayscale (not hard-binarized) is the default OCR input: modern
    # deep-learning OCR engines (PaddleOCR) generally do better with tonal
    # information than with a hard-thresholded binary image, unlike classic
    # engines (Tesseract) that need stark binarization. The binary version is
    # still produced and saved for inspection/debugging, per CLAUDE.md's
    # explicit "adaptive thresholding" step. This is a stated assumption,
    # not a silent choice — override via settings if P2 shows otherwise.
    working_image = denoised_gray
    working_path: str
    if debug_dir is not None:
        working_path = str(Path(debug_dir) / "working.png")
    else:
        working_path = str(path.with_suffix(".preprocessed.png"))
    cv2.imwrite(working_path, working_image)

    h_final, w_final = working_image.shape[:2]

    return PreprocessResult(
        source_file=str(path),
        working_image_path=working_path,
        debug_dir=debug_dir,
        debug_artifacts=debug,
        quality=quality,
        boundary_found=boundary_found,
        working_width=w_final,
        working_height=h_final,
    )
