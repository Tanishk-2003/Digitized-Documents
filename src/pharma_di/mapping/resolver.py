"""DictionaryResolver + ReviewQueueResolver (IMPLEMENTATION_PLAN.md sections
0 and 4.6) — the no-LLM MVP's two SemanticResolver implementations, tried in
a fixed chain by `resolve_header` below. Adding a LocalLlmResolver later
means writing one more class implementing the same Protocol and inserting it
into the chain between these two — zero changes to `resolve_header` itself
or to any call site (section 0's whole point).

Every resolver in the chain returns a real MappingDecision, never None —
DictionaryResolver's own "I can't resolve this" answer is
`status=unresolved`, exactly like ReviewQueueResolver's, so the chain is a
plain "does this one actually resolve it, or was that unresolved too" walk
rather than a special-cased None check.
"""
from __future__ import annotations

from typing import Any

from pharma_di.detect.fingerprint import leaf_fingerprint_key, lookup_fingerprint
from pharma_di.mapping.dictionary import FieldEntry
from pharma_di.mapping.fuzzy import ACCEPT_THRESHOLD, LOW_CONFIDENCE_THRESHOLD, best_matching_field
from pharma_di.mapping.normalize import basic_normalize_path, expand_abbreviations, expand_abbreviations_path
from pharma_di.schemas.layout import HeaderNode
from pharma_di.schemas.mapping import MappingDecision, MappingStatus, SemanticResolver, TableContext


class DictionaryResolver:
    """Tiers 1-4 of section 4.6's resolution order: template-fingerprint
    cache hit, exact normalized-path match, abbreviation-normalized match,
    then fuzzy match — in that order, stopping at the first that resolves.
    """

    def __init__(
        self,
        field_entries: list[FieldEntry],
        templates_cfg: dict[str, Any],
        accept_threshold: float = ACCEPT_THRESHOLD,
        low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD,
        abbreviations: dict[str, str] | None = None,
    ):
        """`accept_threshold`/`low_confidence_threshold` default to
        `mapping/fuzzy.py`'s own constants (IMPLEMENTATION_PLAN.md section
        4.6's exact numbers) — P11's generalization audit found
        `config/settings.yaml`'s `semantic_mapping.fuzzy_accept_threshold`/
        `fuzzy_review_threshold` were declared but never actually read
        anywhere, with these fuzzy.py constants silently duplicating the
        same numbers instead. `graph/nodes.py::map_columns` now passes the
        real `Settings.semantic_mapping` values in here, making that config
        live; a caller that doesn't pass them (e.g. a unit test instantiating
        this directly) still gets the same defaults as before, unchanged.

        `abbreviations` (P12) is likewise config-driven now — defaults to
        `mapping/normalize.py`'s own table when not given (same
        don't-break-direct-callers reasoning); the live pipeline passes
        `config.py::load_abbreviations()`'s `column_mappings.yaml`-sourced
        table instead, so extending tier 3's vocabulary for a new
        distributor is a config change, not a code change."""
        self._field_entries = field_entries
        self._templates_cfg = templates_cfg
        self._accept_threshold = accept_threshold
        self._low_confidence_threshold = low_confidence_threshold
        self._abbreviations = abbreviations

    def resolve(self, header: HeaderNode, ctx: TableContext) -> MappingDecision:
        cached = self._resolve_from_template_cache(header, ctx)
        if cached is not None:
            return cached

        header_key = basic_normalize_path(header.path)
        for entry in self._field_entries:
            path_keys = {basic_normalize_path(p) for p in entry.paths}
            alias_keys = {a.strip().lower() for a in entry.aliases}
            if header_key in path_keys or header_key in alias_keys:
                return MappingDecision(
                    source_header=header,
                    canonical_field=entry.canonical_field,
                    status=MappingStatus.exact,
                    combine=entry.combine,
                )

        header_expanded = expand_abbreviations_path(header.path, self._abbreviations)
        for entry in self._field_entries:
            path_keys = {expand_abbreviations_path(p, self._abbreviations) for p in entry.paths}
            alias_keys = {expand_abbreviations(a, self._abbreviations) for a in entry.aliases}
            if header_expanded in path_keys or header_expanded in alias_keys:
                return MappingDecision(
                    source_header=header,
                    canonical_field=entry.canonical_field,
                    status=MappingStatus.normalized,
                    combine=entry.combine,
                )

        fuzzy_decision = self._resolve_fuzzy(header)
        if fuzzy_decision is not None:
            return fuzzy_decision

        return MappingDecision(source_header=header, canonical_field=None, status=MappingStatus.unresolved)

    def _resolve_from_template_cache(self, header: HeaderNode, ctx: TableContext) -> MappingDecision | None:
        if not ctx.fingerprint:
            return None
        cached = lookup_fingerprint(ctx.fingerprint, self._templates_cfg)
        if cached is None:
            return None
        # P13: looked up by the same OCR-noise-tolerant leaf key the
        # fingerprint itself was built from (detect/fingerprint.py), not
        # header.normalized_key (bare lowercase+strip) — a table-level
        # fingerprint hit is only useful if the per-column keys inside it
        # can still be found for THIS document's own (possibly differently
        # garbled) header text.
        leaf_key = leaf_fingerprint_key(header, self._field_entries, self._abbreviations, self._accept_threshold)
        cached_field = cached.get(leaf_key)
        if cached_field is None:
            return None
        return MappingDecision(source_header=header, canonical_field=cached_field, status=MappingStatus.template_cache)

    def _resolve_fuzzy(self, header: HeaderNode) -> MappingDecision | None:
        header_text = " ".join(header.path)
        match = best_matching_field(header_text, self._field_entries)
        if match is None or match[1] < self._low_confidence_threshold:
            return None
        best_field, best_score = match
        status = MappingStatus.fuzzy if best_score >= self._accept_threshold else MappingStatus.fuzzy_low_confidence
        return MappingDecision(
            source_header=header,
            canonical_field=best_field.canonical_field,
            status=status,
            match_score=best_score,
            combine=best_field.combine,
        )


class ReviewQueueResolver:
    """The fallback resolver (section 0): every column DictionaryResolver
    (and, later, LocalLlmResolver) couldn't resolve becomes an explicit,
    named unresolved decision — its cells survive in unmapped_columns,
    never silently dropped or guessed onto a field."""

    def resolve(self, header: HeaderNode, ctx: TableContext) -> MappingDecision:
        return MappingDecision(source_header=header, canonical_field=None, status=MappingStatus.unresolved)


def resolve_header(header: HeaderNode, ctx: TableContext, resolvers: list[SemanticResolver]) -> MappingDecision:
    """Try each resolver in order, stopping at the first non-unresolved
    decision. `resolvers` should always end with ReviewQueueResolver (or an
    equivalent that never itself returns unresolved) so this always
    terminates with a real decision."""
    decision: MappingDecision | None = None
    for resolver in resolvers:
        decision = resolver.resolve(header, ctx)
        if decision.status != MappingStatus.unresolved:
            return decision
    assert decision is not None  # resolvers is never empty in practice
    return decision
