"""Hierarchical header reconstruction (IMPLEMENTATION_PLAN.md section 4.5):
OPENING -> {QTY., VALUE}, and the same pattern for RECEIPT/ISSUE/CLOSING/DUMP.

Real data changed the design here. The plan's original sketch ("cluster
header tokens into 2 lines by baseline, match by x-span overlap") doesn't
survive contact with doc6.jpg's actual token geometry: parent and child
labels sit at staggered, cascading y-positions rather than two clean bands
(RATE and ITEM DESCRIPTION start well above OPENING/RECEIPT, which start
above their own QTY/VALUE), and some true parent/child pairs barely
overlap in x at all (RECEIPT's own QTY token sits almost entirely to its
left, touching by ~1px). A strict two-line-then-overlap match would miss
real pairs.

CLAUDE.md is explicit that this domain's headers are never more than one
level deep ("OPENING spans two sub-columns QTY and VALUE") — every sample
across all 6 documents confirms this. So instead of a general recursive
tree parser, this uses that actual constraint: a small closed set of
sub-column leaf words (qty, value, m.exp — the only ones CLAUDE.md and the
6 real samples show) are matched to their nearest parent candidate above
them by x-center proximity (not overlap), within a generous bound. A parent
candidate not claimed by any leaf is itself a single-level header (RATE,
ITEM DESCRIPTION). This is a domain-shaped simplification, not a shortcut
around the hard part — the hard part (staggered, non-overlapping real
geometry) is exactly what it's built to handle.
"""
from __future__ import annotations

from rapidfuzz import fuzz

from pharma_di.schemas.layout import HeaderNode
from pharma_di.schemas.ocr import OcrToken

# The only sub-column leaf words observed across CLAUDE.md's description and
# all 6 real samples (doc4/doc5/doc6's OPENING/RECEIPT/ISSUE/CLOSING/DUMP
# sub-columns). Matched fuzzily (not exact) after normalization — real OCR
# noise garbles these too (e.g. doc6.jpg's CLOSING QTY was read as "CEY").
# A moderate threshold catches near-misses ("QTV", "VALU") without forcing a
# match on severe corruption: "CEY" vs "QTY" scores well under this
# threshold and correctly stays unmatched — a leaf-reconstruction failure
# that severe is exactly what should surface as a genuinely unresolved
# column downstream (P5's mapping dictionary won't fuzzy-match "CEY" to
# anything either), not something to force-fix here with a special case for
# one observed typo. "Never guess" applies to header structure, not just
# semantic mapping.
#
# "quantity" is listed as its own literal entry, not left to fuzzy-match
# "qty" — found on doc1.jpg (New Tripura's full-word-spelled header, not the
# MARG family's abbreviation): fuzz.ratio("quantity", "qty") scores ~55,
# well under LEAF_FUZZY_THRESHOLD, so the abbreviation alone never recognizes
# the spelled-out form. This is a real dictionary/vocabulary gap (CLAUDE.md's
# preferred fix: extend the maintained mapping, not add code), not a
# threshold tweak — lowering the threshold to catch "quantity" would also
# start catching things that shouldn't match.
LEAF_LABELS = ["qty", "value", "m.exp", "quantity"]
LEAF_FUZZY_THRESHOLD = 70


def _normalize(text: str) -> str:
    return text.strip().lower().rstrip(".")


def is_leaf_label(text: str) -> bool:
    normalized = _normalize(text)
    return any(fuzz.ratio(normalized, label) >= LEAF_FUZZY_THRESHOLD for label in LEAF_LABELS)


def reconstruct_headers(
    header_tokens: list[OcrToken],
    max_parent_distance_frac: float = 3.0,
) -> list[HeaderNode]:
    """Return one HeaderNode per leaf column, path=[...] reflecting any
    parent found. Never merges tokens across genuinely different columns —
    an ambiguous or unmatched leaf simply gets its own bare path rather than
    being guessed onto a nearby parent (section 0: no column is ever
    guessed onto a field; the same discipline applies to header structure
    itself).
    """
    if not header_tokens:
        return []

    leaves: list[OcrToken] = []
    parent_candidates: list[OcrToken] = []
    for t in header_tokens:
        if is_leaf_label(t.text):
            leaves.append(t)
        else:
            parent_candidates.append(t)

    if not leaves:
        # Single-line header (doc1.jpg, doc2.jpg) — the degenerate case the
        # plan names explicitly: every token is its own single-level column.
        return [HeaderNode(path=[t.text.strip()], bbox=t.bbox, confidence=t.confidence) for t in header_tokens]

    median_width = _median_width(header_tokens)
    max_distance = max_parent_distance_frac * median_width

    claimed_parents: set[int] = set()
    nodes: list[HeaderNode] = []

    for leaf in leaves:
        best_idx, best_dist = None, None
        for i, parent in enumerate(parent_candidates):
            if parent.bbox.y0 >= leaf.bbox.y0:
                continue  # a parent must sit above its child
            dist = abs(parent.bbox.cx - leaf.bbox.cx)
            if dist > max_distance:
                continue
            if best_dist is None or dist < best_dist:
                best_idx, best_dist = i, dist

        if best_idx is not None:
            claimed_parents.add(best_idx)
            parent = parent_candidates[best_idx]
            path = [parent.text.strip(), leaf.text.strip()]
            bbox = _union_bbox(parent.bbox, leaf.bbox)
            confidence = min(parent.confidence, leaf.confidence)
        else:
            path = [leaf.text.strip()]
            bbox = leaf.bbox
            confidence = leaf.confidence

        nodes.append(HeaderNode(path=path, bbox=bbox, confidence=confidence))

    for i, parent in enumerate(parent_candidates):
        if i not in claimed_parents:
            nodes.append(HeaderNode(path=[parent.text.strip()], bbox=parent.bbox, confidence=parent.confidence))

    return sorted(nodes, key=lambda n: n.bbox.cx)


def _median_width(tokens: list[OcrToken]) -> float:
    widths = sorted(t.bbox.width for t in tokens)
    return widths[len(widths) // 2] if widths else 60.0


def _union_bbox(a, b):
    from pharma_di.schemas.ocr import BBox

    return BBox(x0=min(a.x0, b.x0), y0=min(a.y0, b.y0), x1=max(a.x1, b.x1), y1=max(a.y1, b.y1))
