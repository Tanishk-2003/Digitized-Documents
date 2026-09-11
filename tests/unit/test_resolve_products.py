"""P6 unit tests for resolve/products.py — product master resolution
(IMPLEMENTATION_PLAN.md section 4.8)."""
from __future__ import annotations

from pharma_di.resolve.masters import MasterProduct
from pharma_di.resolve.products import SCORE_FLOOR, resolve_product
from pharma_di.schemas.canonical import ProductRecord


def _product(name, pack=None, hsn_code=None):
    return ProductRecord(product_name_raw=name, pack=pack, hsn_code=hsn_code)


def _master(product_id, name, pack=None, hsn_code=None):
    return MasterProduct(product_id=product_id, product_name_raw=name, pack=pack, hsn_code=hsn_code)


def test_exact_hsn_code_match_wins_even_with_a_different_name():
    # hsn_code is the primary, structured identifier (CLAUDE.md: "hsn_code
    # ahead of fuzzy matching for product resolution whenever the source
    # provides it") — an exact code match should be trusted over name
    # noise, not overridden by a closer-sounding but wrong-code candidate.
    masters = [
        _master("real-product", "COSKLOT REG TAB", hsn_code="300490"),
        _master("similar-sounding", "COSKLOT REG TABLET", hsn_code="999999"),
    ]
    product_id, reason = resolve_product(_product("COSKLOT REG TA8", hsn_code="300490"), masters)
    assert product_id == "real-product"
    assert "hsn_code" in reason


def test_fuzzy_match_on_name_and_pack_above_score_floor():
    masters = [_master("p1", "COSKLOT REG TAB.", pack="10'S")]
    product_id, reason = resolve_product(_product("COSKLOT REG TAB", pack="10'S"), masters)
    assert product_id == "p1"
    assert "fuzzy" in reason


def test_unmatched_below_score_floor_returns_none_not_a_guess():
    masters = [_master("p1", "COSKLOT REG TAB.", pack="10'S")]
    product_id, reason = resolve_product(_product("ZINCACE SYP", pack="100ML"), masters)
    assert product_id is None
    assert "no confident match" in reason


def test_empty_masters_returns_none():
    product_id, reason = resolve_product(_product("ANYTHING"), [])
    assert product_id is None
    assert "no product master catalogue" in reason


def test_hsn_code_present_on_product_but_absent_from_every_master_falls_through_to_fuzzy():
    masters = [_master("p1", "COSKLOT REG TAB.", pack="10'S", hsn_code=None)]
    product_id, _reason = resolve_product(_product("COSKLOT REG TAB", pack="10'S", hsn_code="300490"), masters)
    assert product_id == "p1"


def test_score_floor_constant_is_stricter_than_mapping_low_confidence_threshold():
    # Product identity is higher-stakes than a column-header label — the
    # bar for auto-matching a product should not be lower than the bar
    # config/column_mappings.yaml already uses for a mere column label.
    from pharma_di.mapping.fuzzy import LOW_CONFIDENCE_THRESHOLD

    assert SCORE_FLOOR >= LOW_CONFIDENCE_THRESHOLD
