"""Config loader.

Every stage reads settings/mappings/rules through this module rather than
hardcoding paths or thresholds, and rather than re-reading YAML itself. There
is exactly one place a new distributor format's config lives; this module is
where it gets loaded.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

# Repo root = two levels up from this file (src/pharma_di/config.py -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[2]


class PreprocessSettings(BaseModel):
    max_dimension_px: int = 2000
    # See preprocess/boundary.py detect_boundary() docstring: must stay high
    # (all 6 real samples show the page filling 85%+ of the frame) or a
    # strong inner contour (a ruled table's own border, on doc2.jpg) gets
    # mistaken for the page boundary and silently crops out real content.
    boundary_min_area_frac: float = 0.6
    illumination_kernel_frac: float = 0.10
    denoise_h: float = 7.0
    adaptive_threshold_block_size: int = 35
    adaptive_threshold_C: int = 15
    dewarp_strip_count: int = 24
    edge_band_frac: float = 0.012


class QualityGateSettings(BaseModel):
    min_blur_variance: float = 50.0
    max_residual_skew_deg: float = 3.0
    require_all_corners_in_frame: bool = True
    min_contrast_std: float = 20.0
    content_edge_density_threshold: float = 0.35


class SemanticMappingSettings(BaseModel):
    fallback: str = "none"  # "none" | "local_llm" — see IMPLEMENTATION_PLAN.md section 0
    fuzzy_accept_threshold: int = 90
    fuzzy_review_threshold: int = 75


class ValidationSettings(BaseModel):
    rate_tolerance_pct: float = 0.5
    totals_tolerance_abs: float = 0.01
    # R6 confidence gate (IMPLEMENTATION_PLAN.md section 4.7). Grounded in
    # P2's own real-data finding (test_ocr_real_images.py /
    # IMPLEMENTATION_PLAN.md P2 build notes): garbled/wrong product names
    # scored 0.72-0.85, confirmed-correct clean numbers scored 0.98+ — a
    # lower threshold like 0.7 would pass some of the garbled cases already
    # observed, so 0.85 sits just above that band rather than being an
    # unverified guess.
    min_field_confidence: float = 0.85


class OcrSettings(BaseModel):
    engine: str = "paddleocr"
    lang: str = "en"
    min_token_confidence: float = 0.5
    # Separate from preprocess.max_dimension_px, but kept close to it: this
    # environment's PaddleOCR inference runs without oneDNN acceleration
    # (see ocr/paddle_engine.py module docstring) and measurement showed
    # cost is driven by per-detected-region recognition passes, not overall
    # pixel count — downscaling further gives at most a mild detection-step
    # saving, so this is not pushed lower to chase a speedup that doesn't
    # materialize, at the cost of legibility.
    max_dimension_px: int = 1800
    cache_dir: str = "data/interim/ocr_cache"


class LlmSettings(BaseModel):
    provider: str = "local_only"
    endpoint: str | None = None
    model: str | None = None


class Settings(BaseModel):
    """Top-level settings object, loaded once from config/settings.yaml."""

    paths: dict[str, str] = Field(default_factory=dict)
    semantic_mapping: SemanticMappingSettings = Field(default_factory=SemanticMappingSettings)
    preprocess: PreprocessSettings = Field(default_factory=PreprocessSettings)
    quality_gate: QualityGateSettings = Field(default_factory=QualityGateSettings)
    validation: ValidationSettings = Field(default_factory=ValidationSettings)
    ocr: OcrSettings = Field(default_factory=OcrSettings)
    llm: LlmSettings = Field(default_factory=LlmSettings)

    def resolve_path(self, key: str) -> Path:
        """Resolve one of the `paths.*` entries to an absolute Path under repo root."""
        rel = self.paths[key]
        return (REPO_ROOT / rel).resolve()


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Required config file missing: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


@lru_cache(maxsize=1)
def load_settings(config_path: str | None = None) -> Settings:
    path = Path(config_path) if config_path else REPO_ROOT / "config" / "settings.yaml"
    raw = _load_yaml(path)
    return Settings.model_validate(raw)


@lru_cache(maxsize=1)
def load_column_mappings() -> dict[str, Any]:
    settings = load_settings()
    return _load_yaml(settings.resolve_path("column_mappings"))


def load_abbreviations() -> dict[str, str]:
    """P12: tier 3's whole-word abbreviation table, now a `column_mappings.
    yaml` entry instead of a hardcoded Python dict (mapping/normalize.py) —
    a new distributor's own abbreviation style is a config change, not a
    code change. Not independently cached: it's a sub-view of the same
    already-cached `load_column_mappings()` read, so `clear_config_cache()`
    clearing that one cache already covers this too."""
    return load_column_mappings().get("abbreviations", {})


@lru_cache(maxsize=1)
def load_distributors() -> dict[str, Any]:
    settings = load_settings()
    return _load_yaml(settings.resolve_path("distributors"))


def distributor_address(distributor_id: str | None) -> str | None:
    """P14: the final-output table's `Address` column source — a config
    lookup, not page-text extraction (per the project owner's own answer).
    `config/distributors.yaml` already carries a hand-populated `address`
    field per known distributor. Returns None for an unresolved
    `distributor_id` or one not yet in that config — same "route to
    review rather than guess" discipline an unresolved product already
    follows, not a special case invented for this field."""
    if not distributor_id:
        return None
    for entry in load_distributors().get("distributors", []):
        if entry.get("distributor_id") == distributor_id:
            return entry.get("address")
    return None


@lru_cache(maxsize=1)
def load_validation_rules() -> dict[str, Any]:
    settings = load_settings()
    return _load_yaml(settings.resolve_path("validation_rules"))


@lru_cache(maxsize=1)
def load_templates() -> dict[str, Any]:
    settings = load_settings()
    return _load_yaml(settings.resolve_path("templates"))


def clear_config_cache() -> None:
    """Test-only: drop cached config so a test can point at a different file."""
    load_settings.cache_clear()
    load_column_mappings.cache_clear()
    load_distributors.cache_clear()
    load_validation_rules.cache_clear()
    load_templates.cache_clear()
