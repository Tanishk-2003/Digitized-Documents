"""P2: the disk cache is what makes repeated runs fast (and, in this
environment, practical at all — see ocr/paddle_engine.py's documented
performance issue). Tested independently of any real OCR call: `compute`
here is just a counter, so these tests are fast and don't need paddle.
"""
from __future__ import annotations

from pharma_di.ocr.cache import OcrCache, hash_image_file
from pharma_di.schemas.ocr import BBox, OcrPage, OcrToken


def _sample_page(source_file: str = "doc1.jpg") -> OcrPage:
    return OcrPage(
        source_file=source_file,
        page_number=1,
        image_width=100,
        image_height=50,
        tokens=[OcrToken(text="ZORVICAL", bbox=BBox(x0=0, y0=0, x1=50, y1=20), confidence=0.95)],
    )


def test_hash_is_stable_for_identical_content(tmp_path):
    f1 = tmp_path / "a.png"
    f2 = tmp_path / "b.png"
    f1.write_bytes(b"identical content")
    f2.write_bytes(b"identical content")
    assert hash_image_file(f1) == hash_image_file(f2)


def test_hash_differs_for_different_content(tmp_path):
    f1 = tmp_path / "a.png"
    f2 = tmp_path / "b.png"
    f1.write_bytes(b"content A")
    f2.write_bytes(b"content B")
    assert hash_image_file(f1) != hash_image_file(f2)


def test_cache_miss_then_hit(tmp_path):
    img = tmp_path / "img.png"
    img.write_bytes(b"some preprocessed image bytes")
    cache = OcrCache(tmp_path / "cache")

    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return _sample_page()

    page1, hit1 = cache.get_or_compute(img, compute)
    assert hit1 is False
    assert calls["n"] == 1

    page2, hit2 = cache.get_or_compute(img, compute)
    assert hit2 is True
    assert calls["n"] == 1  # compute() must NOT be called again on a hit
    assert page2 == page1


def test_cache_is_keyed_on_content_not_document_id(tmp_path):
    # Two different "documents" (different paths) with IDENTICAL preprocessed
    # bytes must hit the same cache entry — this is the whole point of
    # content-addressing rather than keying on a run's document_id.
    img_a = tmp_path / "run1" / "working.png"
    img_b = tmp_path / "run2" / "working.png"
    img_a.parent.mkdir()
    img_b.parent.mkdir()
    img_a.write_bytes(b"same bytes")
    img_b.write_bytes(b"same bytes")

    cache = OcrCache(tmp_path / "cache")
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return _sample_page()

    cache.get_or_compute(img_a, compute)
    cache.get_or_compute(img_b, compute)
    assert calls["n"] == 1


def test_different_content_produces_different_cache_entries(tmp_path):
    img_a = tmp_path / "a.png"
    img_b = tmp_path / "b.png"
    img_a.write_bytes(b"content one")
    img_b.write_bytes(b"content two, different")

    cache = OcrCache(tmp_path / "cache")
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return _sample_page(source_file=f"doc-{calls['n']}.jpg")

    cache.get_or_compute(img_a, compute)
    cache.get_or_compute(img_b, compute)
    assert calls["n"] == 2


def test_cached_page_round_trips_through_json_exactly(tmp_path):
    img = tmp_path / "img.png"
    img.write_bytes(b"bytes")
    cache = OcrCache(tmp_path / "cache")
    original = _sample_page()

    page, _ = cache.get_or_compute(img, lambda: original)
    reloaded, hit = cache.get_or_compute(img, lambda: (_ for _ in ()).throw(AssertionError("should not recompute")))

    assert hit is True
    assert reloaded.tokens[0].text == "ZORVICAL"
    assert reloaded.tokens[0].confidence == 0.95
    assert reloaded.tokens[0].bbox.x1 == 50
