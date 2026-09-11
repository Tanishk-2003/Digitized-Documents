"""Product master resolution (IMPLEMENTATION_PLAN.md section 4.8): hsn_code
(exact) -> fuzzy match on normalized product_name_raw + pack, with a score
floor below which the row is unmatched rather than guessed.

CLAUDE.md's stated order is "hsn_code (exact) -> product code (exact) ->
fuzzy" — the middle tier is not implemented as a separate step because
`ProductRecord` (schemas/canonical.py) has no field for a "product code"
distinct from `hsn_code`, and none of the six real samples' column
vocabularies name one either: the numeric codes actually observed
(doc2.jpg's "300490" etc.) are printed under an explicit "HSN Code" header
and match real Harmonized System pharmaceutical chapter numbering (chapter
3004 = "Medicaments"), so they ARE hsn_code values, not a second identifier
space. Implementing a tier for a field that doesn't exist anywhere in the
data model or the real data would be dead code, not faithfulness to the
plan — this reflects the data actually on file.
"""
from __future__ import annotations

from pharma_di.mapping.fuzzy import best_fuzzy_match
from pharma_di.resolve.masters import MasterProduct
from pharma_di.schemas.canonical import ProductRecord

SCORE_FLOOR = 85.0


def _normalize_identity(product_name_raw: str, pack: str | None) -> str:
    return f"{product_name_raw.strip().lower()} {pack.strip().lower() if pack else ''}".strip()


def resolve_product(product: ProductRecord, masters: list[MasterProduct]) -> tuple[str | None, str]:
    """Returns (product_id, reason). product_id is None iff unmatched —
    never guessed onto a candidate below SCORE_FLOOR (section 0's "no
    column is ever guessed" principle applies to product identity too).

    Iterates `masters` directly for the fuzzy tier rather than building a
    dict keyed by normalized name+pack: two real master entries can share
    an identical normalized identity while differing in hsn_code (a
    genuine product variant), and a dict key would silently collapse them
    to whichever was inserted last.
    """
    if not masters:
        return None, "no product master catalogue loaded"

    if product.hsn_code:
        for m in masters:
            if m.hsn_code and m.hsn_code == product.hsn_code:
                return m.product_id, "exact hsn_code match"

    query = _normalize_identity(product.product_name_raw, product.pack)
    best_master: MasterProduct | None = None
    best_score = 0.0
    for m in masters:
        candidate = _normalize_identity(m.product_name_raw, m.pack)
        match = best_fuzzy_match(query, [candidate])
        if match is not None and match[1] > best_score:
            best_master, best_score = m, match[1]

    if best_master is None or best_score < SCORE_FLOOR:
        return None, f"no confident match (best score {best_score:.1f}, floor {SCORE_FLOOR:.1f})"
    return best_master.product_id, f"fuzzy match on name+pack (score {best_score:.1f})"
