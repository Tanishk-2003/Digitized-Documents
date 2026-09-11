"""P4 unit tests for detect/fingerprint.py — template fingerprinting
(IMPLEMENTATION_PLAN.md section 1.3)."""
from __future__ import annotations

from pharma_di.detect.fingerprint import compute_fingerprint, lookup_fingerprint
from pharma_di.schemas.layout import BBox, ColumnBand, HeaderNode


def _band(path, x0=0, x1=100):
    return ColumnBand(header=HeaderNode(path=path, bbox=BBox(x0=x0, y0=0, x1=x1, y1=20)), x0=x0, x1=x1)


def test_compute_fingerprint_is_deterministic():
    columns = [_band(["ITEM DESCRIPTION"]), _band(["RATE"], 100, 200)]
    assert compute_fingerprint(columns) == compute_fingerprint(columns)


def test_compute_fingerprint_same_headers_same_signature_across_instances():
    a = [_band(["ITEM DESCRIPTION"]), _band(["OPENING", "QTY."], 100, 200)]
    b = [_band(["ITEM DESCRIPTION"]), _band(["OPENING", "QTY."], 100, 200)]
    assert compute_fingerprint(a) == compute_fingerprint(b)


def test_compute_fingerprint_differs_on_different_headers():
    a = [_band(["ITEM DESCRIPTION"]), _band(["RATE"], 100, 200)]
    b = [_band(["ITEM DESCRIPTION"]), _band(["PACK"], 100, 200)]
    assert compute_fingerprint(a) != compute_fingerprint(b)


def test_compute_fingerprint_is_order_sensitive():
    # A different column arrangement is a different template (plan finding
    # #11: doc4/doc5/doc6 each print a different subset/order of columns) —
    # this must NOT be a set hash that ignores order.
    a = [_band(["RATE"]), _band(["PACK"], 100, 200)]
    b = [_band(["PACK"]), _band(["RATE"], 100, 200)]
    assert compute_fingerprint(a) != compute_fingerprint(b)


def test_compute_fingerprint_is_case_and_whitespace_normalized():
    # normalized_key already lowercases/strips each path element — a purely
    # cosmetic OCR-casing difference should not produce a new fingerprint.
    a = [_band(["Item Description"])]
    b = [_band(["ITEM DESCRIPTION"])]
    assert compute_fingerprint(a) == compute_fingerprint(b)


def test_lookup_fingerprint_returns_cached_mapping():
    cfg = {"fingerprints": {"abc123": {"resolved": "mapping"}}}
    assert lookup_fingerprint("abc123", cfg) == {"resolved": "mapping"}


def test_lookup_fingerprint_returns_none_for_unknown_fingerprint():
    cfg = {"fingerprints": {"abc123": {"resolved": "mapping"}}}
    assert lookup_fingerprint("does-not-exist", cfg) is None


def test_lookup_fingerprint_handles_empty_cache():
    assert lookup_fingerprint("anything", {"fingerprints": {}}) is None
