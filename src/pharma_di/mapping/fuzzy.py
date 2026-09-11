"""Fuzzy header matching (IMPLEMENTATION_PLAN.md section 4.6, tier 4):
rapidfuzz `token_set_ratio` combined with `token_sort_ratio` (the minimum of
the two), not `token_set_ratio` alone, and not `partial_ratio` (used in
detect/document.py for free-text distributor/company matching).

`token_set_ratio` alone has a real, verified failure mode on short headers:
found on doc1.jpg's real column "Stock" (its own header, not "Opening
Stock") — `token_set_ratio("stock", "opening stock")` scores 100.0, because
a query whose words are a pure SUBSET of a longer candidate's words scores
as if it were a perfect match, regardless of what's missing. That's real
subset-inflation, not synthetic: it silently mapped doc1's real "Stock"
column to `opening_quantity` before this fix, and its neighboring "Stock
Value" column the same way. `token_sort_ratio` doesn't share that blind
spot (same case: 55.6, correctly low) because it compares the FULL sorted
token sequence rather than crediting a partial subset as if it were
complete — but token_sort_ratio alone would lose the word-order tolerance
token_set_ratio was chosen for in the first place (a header and its alias
listing the same words in a different order should still score highly).
Taking the minimum of both keeps a match only when NEITHER metric's blind
spot lets it through — verified this preserves every real OCR-noise case
already covered by tests (e.g. "OPENING VALDE" vs "opening value": 92.3
either way) while correctly rejecting the "stock" subset case (55.6, both
metrics agree here since token_sort_ratio never inflates it).

Thresholds are IMPLEMENTATION_PLAN.md section 4.6's exact numbers:
">=90 accept; 75-90 accept but mark the column low-confidence so its rows
require review; <75 never auto-accepts a value column."
"""
from __future__ import annotations

from rapidfuzz import fuzz

ACCEPT_THRESHOLD = 90.0
LOW_CONFIDENCE_THRESHOLD = 75.0


def _score(text: str, candidate: str) -> float:
    return min(fuzz.token_set_ratio(text, candidate), fuzz.token_sort_ratio(text, candidate))


def best_fuzzy_match(text: str, candidates: list[str]) -> tuple[str, float] | None:
    """The candidate with the highest combined score against `text`, or
    None if `candidates` is empty. Ties keep whichever candidate was seen
    first (stable, since callers pass candidates in a fixed config order).

    Both sides are lowercased before comparison — rapidfuzz's ratio
    functions are case-sensitive (verified directly: "OPENING VL" vs
    "opening value" scores far lower than "opening vl" vs "opening value"),
    and real OCR text arrives uppercase while config/column_mappings.yaml's
    aliases are written lowercase. Without this, tier 4 would silently
    never match anything real.
    """
    text_lower = text.lower()
    best: tuple[str, float] | None = None
    for candidate in candidates:
        score = _score(text_lower, candidate.lower())
        if best is None or score > best[1]:
            best = (candidate, score)
    return best
