"""Template fingerprinting (IMPLEMENTATION_PLAN.md section 1.3): hash a
table's normalized leaf-header signature so a document from an
already-resolved layout (e.g. the shared MARG ERP template confirmed across
doc4/doc5/doc6 — same header vocabulary, three different distributors —
plan section 1.3) can skip fuzzy column matching entirely on its next
appearance, while a genuinely new layout still falls through to the mapping
dictionary normally.

This is a cache keyed on the header row's own shape, not a per-distributor
parser: the same distributor changing its report layout produces a new
fingerprint and is handled like any other new template, and three different
distributors sharing one ERP output produce the same fingerprint without
either of them being named in this module.

P13: `leaf_fingerprint_key`/`compute_fingerprint` now take the resolved
field dictionary and abbreviation table as OPTIONAL context. Without them
(the original P4-era behavior — detect_document could call this before P5's
dictionary is even loaded) the fingerprint is still lowercase+strip only.
With them, each leaf that confidently fuzzy-matches a canonical field
hashes to that field's name instead of its raw text — this is what makes
doc5.jpg's "CLOSTNG" and doc6.jpg's "CLOSINO" (two different OCR garblings
of the same real "CLOSING" header, on the same shared MARG template)
finally converge to one fingerprint: neither is a recognized abbreviation
(expand_abbreviations alone can't fix genuine character-level OCR
corruption, only known whole-word abbreviations like "qty"->"quantity"),
but both were ALREADY confirmed to independently fuzzy-match
closing_quantity during real column resolution (P5 build notes) — so
reusing that exact same matching logic here, rather than inventing a
separate/weaker approximation, is what makes a fingerprint match actually
mean "real resolution would agree too."
"""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from pharma_di.mapping.fuzzy import ACCEPT_THRESHOLD, best_matching_field
from pharma_di.mapping.normalize import expand_abbreviations_path
from pharma_di.schemas.layout import ColumnBand, HeaderNode

if TYPE_CHECKING:
    from pharma_di.mapping.dictionary import FieldEntry


def leaf_fingerprint_key(
    header: HeaderNode,
    field_entries: "list[FieldEntry] | None" = None,
    abbreviations: dict[str, str] | None = None,
    accept_threshold: float = ACCEPT_THRESHOLD,
) -> str:
    """One leaf header's contribution to a fingerprint (and the per-column
    key inside a cached fingerprint's mapping — mapping/resolver.py::
    DictionaryResolver._resolve_from_template_cache uses this same
    function, so a table-level fingerprint hit and a per-column cache
    lookup are always consistent with each other).

    Only ACCEPT_THRESHOLD-or-above fuzzy matches count (not the lower
    "review" threshold) — this key feeds a cache a future document trusts
    without re-verification, so bucketing two genuinely different headers
    together needs the same high bar real high-confidence resolution uses,
    not merely "close enough to flag for review." Falls back to
    abbreviation-expanded text (tier 3's own transform) when no
    `field_entries` is given or nothing matches confidently — still a
    normalization improvement over bare lowercase+strip on its own, just
    not tolerant of genuine OCR character corruption without the
    dictionary to check against.
    """
    if field_entries:
        header_text = " ".join(header.path)
        match = best_matching_field(header_text, field_entries)
        if match is not None and match[1] >= accept_threshold:
            return f"field:{match[0].canonical_field}"
    return expand_abbreviations_path(header.path, abbreviations)


def compute_fingerprint(
    columns: list[ColumnBand],
    field_entries: "list[FieldEntry] | None" = None,
    abbreviations: dict[str, str] | None = None,
) -> str:
    """Deterministic hash of the table's ordered leaf-header signature.

    Order-sensitive and NOT a set hash: two tables sharing the same header
    words in a different arrangement are a different template, not the same
    one with columns shuffled — real distributor formats rearrange columns
    (plan finding #11: doc4/doc5/doc6 each print a different subset/order of
    RATE, DUMP QTY, DUMP M.EXP), and collapsing that distinction would let a
    stale cached mapping apply to the wrong column order.
    """
    signature = "||".join(leaf_fingerprint_key(c.header, field_entries, abbreviations) for c in columns)
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]


def lookup_fingerprint(fingerprint: str, templates_cfg: dict[str, Any]) -> dict[str, Any] | None:
    """The cached column mapping for this exact fingerprint, or None if this
    table layout hasn't been resolved before.

    Read-only by design: writing a NEW fingerprint into the cache is
    mapping/template_cache.py::save_fingerprint's job (P13), called once a
    mapping has actually been fully, confidently resolved — not here,
    before mapping has even run. Caching an unresolved or guessed mapping
    would let one bad early read poison every later document that happens
    to share its header shape.
    """
    return templates_cfg.get("fingerprints", {}).get(fingerprint)
