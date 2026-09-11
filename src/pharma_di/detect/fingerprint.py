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
"""
from __future__ import annotations

import hashlib
from typing import Any

from pharma_di.schemas.layout import ColumnBand


def compute_fingerprint(columns: list[ColumnBand]) -> str:
    """Deterministic hash of the table's ordered leaf-header signature.

    Order-sensitive and NOT a set hash: two tables sharing the same header
    words in a different arrangement are a different template, not the same
    one with columns shuffled — real distributor formats rearrange columns
    (plan finding #11: doc4/doc5/doc6 each print a different subset/order of
    RATE, DUMP QTY, DUMP M.EXP), and collapsing that distinction would let a
    stale cached mapping apply to the wrong column order.
    """
    signature = "||".join(c.header.normalized_key for c in columns)
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]


def lookup_fingerprint(fingerprint: str, templates_cfg: dict[str, Any]) -> dict[str, Any] | None:
    """The cached column mapping for this exact fingerprint, or None if this
    table layout hasn't been resolved before.

    Read-only by design: writing a NEW fingerprint into the cache is P5's
    job, done once a mapping has actually been resolved (deterministically
    or via human review) — not here, before mapping has even run. Caching
    an unresolved or guessed mapping would let one bad early read poison
    every later document that happens to share its header shape.
    """
    return templates_cfg.get("fingerprints", {}).get(fingerprint)
