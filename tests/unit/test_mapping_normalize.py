"""P5 unit tests for mapping/normalize.py — header text normalization
(IMPLEMENTATION_PLAN.md section 4.6, tiers 2-3)."""
from __future__ import annotations

from pharma_di.mapping.normalize import basic_normalize_path, expand_abbreviations, expand_abbreviations_path


# --- basic_normalize_path (tier 2) --------------------------------------------


def test_basic_normalize_path_lowercases_and_joins_with_pipe():
    assert basic_normalize_path(["OPENING", "QTY."]) == "opening|qty."


def test_basic_normalize_path_strips_surrounding_whitespace():
    assert basic_normalize_path([" RATE "]) == "rate"


def test_basic_normalize_path_single_element():
    assert basic_normalize_path(["PRODUCT NAME"]) == "product name"


def test_basic_normalize_path_does_not_expand_abbreviations():
    # Exact match (tier 2) is deliberately a raw comparison — abbreviation
    # expansion is tier 3's job, applied only when tier 2 doesn't match.
    assert basic_normalize_path(["QTY"]) == "qty"


# --- expand_abbreviations (tier 3) --------------------------------------------


def test_expand_abbreviations_expands_known_abbreviations():
    assert expand_abbreviations("QTY") == "quantity"
    assert expand_abbreviations("RCVD") == "received"


def test_expand_abbreviations_is_whole_word_only():
    # "op" must not fire inside "opening" or "shop".
    assert expand_abbreviations("OPENING") == "opening"
    assert expand_abbreviations("SHOP") == "shop"
    assert expand_abbreviations("OP") == "opening"


def test_expand_abbreviations_strips_punctuation():
    assert expand_abbreviations("QTY.") == "quantity"


def test_expand_abbreviations_collapses_whitespace():
    assert expand_abbreviations("RCVD   QTY") == "received quantity"


def test_expand_abbreviations_leaves_non_abbreviated_words_alone():
    assert expand_abbreviations("VALUE") == "value"


# --- expand_abbreviations_path ------------------------------------------------


def test_expand_abbreviations_path_expands_each_element_and_joins():
    assert expand_abbreviations_path(["RECPT", "QTY."]) == "receipt|quantity"
