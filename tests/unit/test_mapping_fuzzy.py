"""P5 unit tests for mapping/fuzzy.py — fuzzy header matching
(IMPLEMENTATION_PLAN.md section 4.6, tier 4)."""
from __future__ import annotations

from pharma_di.mapping.fuzzy import ACCEPT_THRESHOLD, LOW_CONFIDENCE_THRESHOLD, best_fuzzy_match


def test_best_fuzzy_match_finds_exact_candidate_at_top_score():
    candidate, score = best_fuzzy_match("opening qty", ["opening qty", "closing qty"])
    assert candidate == "opening qty"
    assert score == 100.0


def test_best_fuzzy_match_scores_word_order_differences_highly():
    # token_set_ratio is order-insensitive by design (section 4.6 chose it
    # specifically for this) — unlike a plain character-level ratio.
    candidate, score = best_fuzzy_match("qty opening", ["opening qty"])
    assert candidate == "opening qty"
    assert score == 100.0


def test_best_fuzzy_match_returns_none_for_empty_candidates():
    assert best_fuzzy_match("opening qty", []) is None


def test_best_fuzzy_match_picks_the_closer_of_two_candidates():
    candidate, score = best_fuzzy_match("opening value", ["opening qty", "opening value"])
    assert candidate == "opening value"
    assert score == 100.0


def test_mild_ocr_noise_still_auto_accepts():
    # Real doc5.jpg OCR noise: "VALUE" read as "VALDE" — one garbled
    # character in a 5-letter word out of a 2-word phrase still scores
    # above ACCEPT_THRESHOLD (verified: 92.3), not merely low-confidence.
    _candidate, score = best_fuzzy_match("opening valde", ["opening value"])
    assert score >= ACCEPT_THRESHOLD


def test_heavier_ocr_noise_lands_in_the_low_confidence_band():
    # Real doc6.jpg OCR noise: "ISSUE" read as "ISSOZ" — verified score
    # (77.8) sits in the 75-90 band: accepted, but the column must still be
    # flagged low-confidence so its rows require review (section 4.6),
    # not treated as cleanly as a near-exact match.
    _candidate, score = best_fuzzy_match("issoz qty", ["issue qty"])
    assert LOW_CONFIDENCE_THRESHOLD <= score < ACCEPT_THRESHOLD


def test_unrelated_text_scores_below_low_confidence_threshold():
    _candidate, score = best_fuzzy_match("item description", ["expired quantity"])
    assert score < LOW_CONFIDENCE_THRESHOLD
