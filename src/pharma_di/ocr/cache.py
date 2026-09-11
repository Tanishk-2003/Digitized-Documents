"""Disk cache for OCR results, keyed on the preprocessed image's own content
hash — not on document_id, which changes on every pipeline run (it carries a
random suffix). The same preprocessed image bytes always hit the same cache
entry, which is what makes P3+ iteration fast without re-running OCR
(IMPLEMENTATION_PLAN.md P2 "done when": "re-runs hit cache").

This matters more than usual in this environment: PaddleOCR inference is
currently running without oneDNN acceleration here (see paddle_engine.py's
module docstring) and is slow — the cache is not just a nice-to-have for
iteration speed, it is what makes repeated runs on the same 6 sample
documents practical at all while that is unresolved.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from pharma_di.schemas.ocr import OcrPage


def hash_image_file(image_path: str | Path) -> str:
    """sha256 of the file's bytes — content-addressed, so re-preprocessing
    the same source image to bit-identical output hits the same cache entry,
    and any change to preprocessing correctly invalidates it."""
    h = hashlib.sha256()
    with open(image_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class OcrCache:
    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(self, key: str) -> OcrPage | None:
        path = self._path_for(key)
        if not path.exists():
            return None
        return OcrPage.model_validate_json(path.read_text(encoding="utf-8"))

    def set(self, key: str, page: OcrPage) -> None:
        self._path_for(key).write_text(page.model_dump_json(indent=2), encoding="utf-8")

    def get_or_compute(self, image_path: str | Path, compute: "callable[[], OcrPage]") -> tuple[OcrPage, bool]:
        """Returns (page, cache_hit)."""
        key = hash_image_file(image_path)
        cached = self.get(key)
        if cached is not None:
            return cached, True
        page = compute()
        self.set(key, page)
        return page, False
