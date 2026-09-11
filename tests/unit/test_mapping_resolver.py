"""P5 unit tests for mapping/resolver.py — the DictionaryResolver ->
ReviewQueueResolver chain (IMPLEMENTATION_PLAN.md sections 0 and 4.6)."""
from __future__ import annotations

from pharma_di.mapping.dictionary import FieldEntry
from pharma_di.mapping.resolver import DictionaryResolver, ReviewQueueResolver, resolve_header
from pharma_di.schemas.layout import BBox, HeaderNode
from pharma_di.schemas.mapping import MappingStatus, TableContext


def _header(path):
    return HeaderNode(path=path, bbox=BBox(x0=0, y0=0, x1=100, y1=20))


_FIELD_ENTRIES = [
    FieldEntry(
        canonical_field="opening_quantity",
        paths=[["opening", "qty."], ["opening", "qty"]],
        aliases=["opening stock", "open qty"],
    ),
    FieldEntry(canonical_field="opening_value", paths=[["opening", "value"]], aliases=["opening value"]),
    FieldEntry(
        canonical_field="sales_return_quantity",
        combine="sum",
        aliases=["sale rtn", "market return", "return outward"],
    ),
    FieldEntry(canonical_field="rate", aliases=["rate"]),
]


def _resolver(templates_cfg=None) -> DictionaryResolver:
    return DictionaryResolver(_FIELD_ENTRIES, templates_cfg or {"fingerprints": {}})


def _ctx(**kwargs) -> TableContext:
    return TableContext(**kwargs)


# --- tier 2: exact match -------------------------------------------------------


def test_exact_match_on_configured_path():
    decision = _resolver().resolve(_header(["OPENING", "QTY."]), _ctx())
    assert decision.status == MappingStatus.exact
    assert decision.canonical_field == "opening_quantity"


def test_exact_match_on_alias_for_single_level_header():
    decision = _resolver().resolve(_header(["RATE"]), _ctx())
    assert decision.status == MappingStatus.exact
    assert decision.canonical_field == "rate"


def test_exact_match_carries_combine_mode():
    decision = _resolver().resolve(_header(["Sale Rtn"]), _ctx())
    assert decision.canonical_field == "sales_return_quantity"
    assert decision.combine == "sum"


# --- tier 3: normalized (abbreviation-expanded) match ---------------------------


def test_normalized_match_after_abbreviation_expansion():
    # "OP" -> "opening", "QTY" -> "quantity" — neither variant is in the
    # configured paths/aliases verbatim, so tier 2 must NOT catch this;
    # tier 3's abbreviation expansion is what resolves it.
    decision = _resolver().resolve(_header(["OP", "QTY"]), _ctx())
    assert decision.status == MappingStatus.normalized
    assert decision.canonical_field == "opening_quantity"


# --- tier 4: fuzzy match ---------------------------------------------------------


def test_fuzzy_match_accepts_mild_ocr_noise():
    # "VALDE" for "VALUE" — real doc5.jpg noise, scores 92.3 (verified),
    # above ACCEPT_THRESHOLD.
    decision = _resolver().resolve(_header(["OPENING", "VALDE"]), _ctx())
    assert decision.status == MappingStatus.fuzzy
    assert decision.canonical_field == "opening_value"
    assert decision.match_score is not None and decision.match_score >= 90.0


def test_fuzzy_match_flags_heavier_ocr_noise_low_confidence():
    # "RATEX" vs "rate" (verified score: 88.9, clean ~40-point separation
    # from every other field in this fixture) sits in the 75-90 band —
    # accepted, but flagged low-confidence rather than treated as a clean
    # match like "VALDE"/"VALOE" above (both 92.3, auto-accepted).
    decision = _resolver().resolve(_header(["RATEX"]), _ctx())
    assert decision.canonical_field == "rate"
    assert decision.status == MappingStatus.fuzzy_low_confidence
    assert decision.match_score is not None and 75.0 <= decision.match_score < 90.0


# --- tier 5 (DictionaryResolver's own answer): unresolved -----------------------


def test_unrelated_header_is_unresolved_by_dictionary_resolver():
    # CLAUDE.md's own example: DUMP QTY is deliberately not in the
    # dictionary (open decision D2) — must never be guessed onto a field.
    decision = _resolver().resolve(_header(["DUMP", "QTY"]), _ctx())
    assert decision.status == MappingStatus.unresolved
    assert decision.canonical_field is None


# --- tier 1: template fingerprint cache -----------------------------------------


def test_template_cache_hit_short_circuits_to_template_cache_status():
    templates_cfg = {"fingerprints": {"abc123": {"weird header|text": "opening_quantity"}}}
    decision = _resolver(templates_cfg).resolve(_header(["WEIRD HEADER", "TEXT"]), _ctx(fingerprint="abc123"))
    assert decision.status == MappingStatus.template_cache
    assert decision.canonical_field == "opening_quantity"


def test_template_cache_miss_falls_through_to_normal_tiers():
    templates_cfg = {"fingerprints": {"abc123": {"some other key": "rate"}}}
    decision = _resolver(templates_cfg).resolve(_header(["OPENING", "QTY."]), _ctx(fingerprint="abc123"))
    assert decision.status == MappingStatus.exact  # not template_cache — this header wasn't in the cached entry
    assert decision.canonical_field == "opening_quantity"


def test_no_fingerprint_in_context_skips_template_cache_tier_entirely():
    templates_cfg = {"fingerprints": {"abc123": {"opening|qty.": "rate"}}}  # would mis-map if consulted
    decision = _resolver(templates_cfg).resolve(_header(["OPENING", "QTY."]), _ctx())  # no fingerprint
    assert decision.status == MappingStatus.exact
    assert decision.canonical_field == "opening_quantity"  # correct tier-2 result, not the unrelated cache entry


# --- ReviewQueueResolver + resolve_header chain ---------------------------------


def test_review_queue_resolver_always_returns_unresolved():
    decision = ReviewQueueResolver().resolve(_header(["ANYTHING AT ALL"]), _ctx())
    assert decision.status == MappingStatus.unresolved
    assert decision.canonical_field is None


def test_resolve_header_chain_falls_through_to_review_queue():
    resolvers = [_resolver(), ReviewQueueResolver()]
    decision = resolve_header(_header(["DUMP", "QTY"]), _ctx(), resolvers)
    assert decision.status == MappingStatus.unresolved


def test_resolve_header_chain_stops_at_first_resolving_resolver():
    resolvers = [_resolver(), ReviewQueueResolver()]
    decision = resolve_header(_header(["RATE"]), _ctx(), resolvers)
    assert decision.status == MappingStatus.exact
    assert decision.canonical_field == "rate"
