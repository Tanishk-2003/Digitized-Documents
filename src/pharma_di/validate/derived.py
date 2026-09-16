"""R3 (derived columns cross-check) — IMPLEMENTATION_PLAN.md section 4.7:
Nabin's printed derived totals ("Total Rcvd.", "Total Sold") should equal
the sum of their own printed components (received + free_received,
sold + free_sold — CLAUDE.md finding #12). Only relevant when a document
actually prints such a column — captured into
CanonicalRow.source_field_breakdown["derived_check_only"] by
assemble/canonical.py, keyed by the printed header text (config/
column_mappings.yaml's own comment: "Printed but not written to a
canonical field directly — consumed by validation rule R3 instead").

Which breakdown entry means "total received" vs "total sold" is decided by
fuzzy-matching each key against alias groups config/column_mappings.yaml
defines for derived_check_only (`received_sold_groups`, P12 — split out
from that field's own flat `aliases` list, which separately decides whether
a header maps to derived_check_only at all; see the YAML's own comment) —
reusing that vocabulary rather than hardcoding doc2.jpg's exact printed
strings — verified directly against real doc2.jpg text ("Total Revd."
scores 90.9 against the received-total aliases vs 66.7 against sold-total
aliases; "Total Sold" scores 100 vs 70 the other way).
"""
from __future__ import annotations

from pharma_di.mapping.fuzzy import LOW_CONFIDENCE_THRESHOLD, best_fuzzy_match
from pharma_di.schemas.validation import RuleId, RuleResult

# Defaults for direct callers (e.g. unit tests) that don't pass their own
# groups — identical to config/column_mappings.yaml's derived_check_only.
# received_sold_groups as of P12, kept here so this module still works
# standalone. The live pipeline (graph/nodes.py::validate) passes the real
# config-sourced groups instead, so a new distributor's differently-worded
# derived total is a config change, not a code change.
_RECEIVED_TOTAL_ALIASES = ["total rcvd.", "total rcvd", "total received"]
_SOLD_TOTAL_ALIASES = ["total sold"]


def _classify_derived_key(
    header_text: str, received_aliases: list[str], sold_aliases: list[str], low_confidence_threshold: float
) -> str | None:
    received = best_fuzzy_match(header_text, received_aliases) if received_aliases else None
    sold = best_fuzzy_match(header_text, sold_aliases) if sold_aliases else None
    received_score = received[1] if received else 0.0
    sold_score = sold[1] if sold else 0.0
    if max(received_score, sold_score) < low_confidence_threshold:
        return None
    return "received" if received_score >= sold_score else "sold"


def check_derived_columns(
    derived_breakdown: dict[str, float],
    values: dict[str, float | None],
    received_aliases: list[str] | None = None,
    sold_aliases: list[str] | None = None,
    low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD,
) -> list[RuleResult]:
    """One RuleResult per recognized printed derived total found in
    `derived_breakdown` (a row's own source_field_breakdown["derived_check_only"],
    or {} for a document that doesn't print one). Never fabricates a check
    for a total this specific document doesn't actually print, and never
    checks against a missing component (CLAUDE.md's null-vs-zero discipline
    — a genuinely unresolved received_quantity/free_received_quantity must
    not be silently treated as 0 just to force this check through).

    `received_aliases`/`sold_aliases` default to this module's own table
    when not given (same pattern as mapping/resolver.py's config-driven
    thresholds/abbreviations, P12)."""
    received_aliases = received_aliases if received_aliases is not None else _RECEIVED_TOTAL_ALIASES
    sold_aliases = sold_aliases if sold_aliases is not None else _SOLD_TOTAL_ALIASES
    results: list[RuleResult] = []
    for header_text, printed_total in derived_breakdown.items():
        kind = _classify_derived_key(header_text, received_aliases, sold_aliases, low_confidence_threshold)
        if kind == "received":
            component_fields = ["received_quantity", "free_received_quantity"]
        elif kind == "sold":
            component_fields = ["sales_quantity", "free_sales_quantity"]
        else:
            continue

        components = [values.get(f) for f in component_fields]
        if any(c is None for c in components):
            continue

        expected = sum(components)
        delta = expected - printed_total
        passed = abs(delta) < 1e-6
        results.append(
            RuleResult(
                rule_id=RuleId.r3_derived_columns,
                passed=passed,
                expected=expected,
                actual=printed_total,
                delta=delta,
                detail=f"{header_text}: {' + '.join(component_fields)} = {expected:g} vs printed {printed_total:g}",
            )
        )
    return results
