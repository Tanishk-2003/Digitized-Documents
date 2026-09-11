"""Column band inference (IMPLEMENTATION_PLAN.md section 4.3): borderless
tables (doc1/doc4/doc5/doc6) have no ruled grid lines, so column
boundaries have to be inferred from token geometry.

Design note on the hard invariant ("leaf header count must equal inferred
column count", section 4.3): rather than running an independent
whitespace-only column detector and cross-checking its count against the
header's leaf count, this uses the header leaves (already reconstructed —
actual identified labels, generally more reliable than blind whitespace
peak-finding on noisy dot-matrix body text) as the authoritative column
*count* by construction, and uses the whitespace-projection and
right-edge-clustering signals only to refine *where the boundary sits*
between each adjacent pair of header-derived columns. The invariant is
satisfied by construction rather than needing a separate reconciliation
step — but `geometry_uncertain` is still set per-column whenever the
signals disagree enough that a boundary can't be placed with confidence
(section 4.3: "Disagreement beyond a threshold sets column_geometry_uncertain
... and routes to review rather than picking a winner").
"""
from __future__ import annotations

import re

import numpy as np

from pharma_di.schemas.layout import BBox, ColumnBand, HeaderNode
from pharma_di.schemas.ocr import OcrToken

# Pack-size codes ("10'S", "1X10", "20ML", "1X1.5ml") sit in their own
# visual column in the MARG family (doc4/doc5/doc6) between the product
# description and RATE — but, unlike every other column, that column has no
# header text of its own at all. Found this session: with column bands built
# one-per-header-leaf (by design — see this module's docstring), a genuinely
# unlabeled column has nowhere to go, and its tokens got silently absorbed
# into the adjacent RATE band, mixing pack-code text ("1X10") and rate
# decimals ("408.86") in one column — which then corrupted every downstream
# row-alignment estimate that used that band's tokens (rows.py's local-slope
# fitting), not just the pack/rate values themselves.
#
# This is intentionally recognized by *shape*, not guessed by position or
# fuzzy-matched against a label that doesn't exist: pack codes are digits
# combined with a unit/multiplier letter or an apostrophe/comma (an OCR
# misread of the apostrophe — "10,S" was observed for "10'S"), while rate/
# value cells are plain decimals. `pack` is also a real, expected Level-2
# field (CLAUDE.md's canonical schema) — labeling the split-out column
# "PACK" is a structural read of the source layout, not a semantic guess.
_PACK_PATTERN = re.compile(r"^\d+(\.\d+)?([xX]\d+(\.\d+)?)?[a-zA-Z']*\.?$|^\d+[,']")


def _is_pack_like(text: str) -> bool:
    stripped = text.strip()
    if not stripped or " " in stripped:
        return False
    if is_numeric(stripped):
        return False  # a plain decimal ("408.86") is a value, not a pack code
    return bool(_PACK_PATTERN.match(stripped))


def _split_pack_column(band: ColumnBand, body_tokens: list[OcrToken]) -> list[ColumnBand]:
    """If `band` contains both pack-shaped and plainly-numeric tokens
    occupying two separated x-ranges, split it into a synthetic PACK column
    plus the original (narrowed to just its real content). Returns [band]
    unchanged if no such split is warranted."""
    column_tokens = [t for t in body_tokens if band.x0 <= t.bbox.cx < band.x1]
    pack_tokens = [t for t in column_tokens if _is_pack_like(t.text)]
    other_tokens = [t for t in column_tokens if is_numeric(t.text)]

    if len(pack_tokens) < 3 or len(other_tokens) < 3:
        return [band]

    pack_max_x = max(t.bbox.x1 for t in pack_tokens)
    other_min_x = min(t.bbox.x0 for t in other_tokens)
    if other_min_x <= pack_max_x:
        return [band]  # the two groups aren't actually separated in x — not a real split

    split_at = (pack_max_x + other_min_x) / 2
    pack_header = HeaderNode(
        path=["PACK"],
        bbox=BBox(
            x0=min(t.bbox.x0 for t in pack_tokens),
            y0=min(t.bbox.y0 for t in pack_tokens),
            x1=max(t.bbox.x1 for t in pack_tokens),
            y1=max(t.bbox.y1 for t in pack_tokens),
        ),
        confidence=min(t.confidence for t in pack_tokens),
    )
    return [
        ColumnBand(header=pack_header, x0=band.x0, x1=split_at, geometry_uncertain=False),
        ColumnBand(header=band.header, x0=split_at, x1=band.x1, geometry_uncertain=band.geometry_uncertain),
    ]


# A valid number, with or without proper thousands-grouping (comma
# followed by exactly 3 digits each time) — NOT a blind "strip all commas"
# check. That distinction matters: "10,8" is OCR's misread of the pack
# code "10'S" (apostrophe -> comma), not the number 108, and blindly
# stripping the comma would wrongly call it numeric.
#
# Public (not `_`-prefixed) because layout/regions.py also needs it: a bare
# numeric token (a product code, a quantity, a currency amount) is never
# legitimate column-header text, so it's reused there as a signal that a
# token caught inside an otherwise-real header line is actually stray body
# data that leaked in via line-clustering, not a header word.
_NUMERIC_PATTERN = re.compile(r"^-?\d{1,3}(,\d{3})*(\.\d+)?$|^-?\d+(\.\d+)?$")


def is_numeric(text: str) -> bool:
    return bool(_NUMERIC_PATTERN.match(text.strip()))


def _whitespace_gutter(body_tokens: list[OcrToken], x_lo: float, x_hi: float) -> float | None:
    """Find the x-position of minimum body-token coverage strictly between
    x_lo and x_hi (signal 2: whitespace projection). Returns None if the
    range has no tokens to project at all (an entirely empty gap — e.g. an
    all-zero column like doc1.jpg's Market Return — in which case the
    midpoint is used instead, by the caller)."""
    tokens_in_range = [t for t in body_tokens if x_lo < t.bbox.cx < x_hi]
    if not tokens_in_range:
        return None

    resolution = 2.0
    n_bins = max(1, int((x_hi - x_lo) / resolution))
    coverage = np.zeros(n_bins)
    for t in body_tokens:
        lo_bin = max(0, int((t.bbox.x0 - x_lo) / resolution))
        hi_bin = min(n_bins, int((t.bbox.x1 - x_lo) / resolution) + 1)
        if hi_bin > lo_bin:
            coverage[lo_bin:hi_bin] += 1

    # search only the interior (avoid picking either extreme edge as "the gutter")
    margin = max(1, n_bins // 10)
    search = coverage[margin : n_bins - margin]
    if search.size == 0:
        return (x_lo + x_hi) / 2
    min_bin = int(np.argmin(search)) + margin
    return x_lo + min_bin * resolution


def infer_column_bands(
    header_leaves: list[HeaderNode],
    body_tokens: list[OcrToken],
    page_x0: float,
    page_x1: float,
    right_edge_cluster_tolerance: float = 25.0,
) -> list[ColumnBand]:
    """One ColumnBand per header leaf, boundaries refined by whitespace
    gutters (signal 2) between adjacent leaves, with a right-edge-clustering
    coherence check (signal 3) for numeric columns."""
    if not header_leaves:
        return []

    leaves_sorted = sorted(header_leaves, key=lambda h: h.bbox.cx)
    centers = [h.bbox.cx for h in leaves_sorted]

    boundaries: list[float] = [page_x0]
    for i in range(len(leaves_sorted) - 1):
        gutter = _whitespace_gutter(body_tokens, centers[i], centers[i + 1])
        boundary = gutter if gutter is not None else (centers[i] + centers[i + 1]) / 2
        boundaries.append(boundary)
    boundaries.append(page_x1)

    bands: list[ColumnBand] = []
    for i, header in enumerate(leaves_sorted):
        x0, x1 = boundaries[i], boundaries[i + 1]
        uncertain = x1 <= x0 or (x1 - x0) < 10.0  # boundaries crossed or collapsed to nothing

        if not uncertain:
            column_tokens = [t for t in body_tokens if x0 <= t.bbox.cx < x1]
            numeric_tokens = [t for t in column_tokens if is_numeric(t.text)]
            if len(numeric_tokens) >= 3:
                right_edges = sorted(t.bbox.x1 for t in numeric_tokens)
                spread = right_edges[-1] - right_edges[0]
                # signal 3 coherence check: a genuine right-aligned numeric
                # column's own values shouldn't spread wider than the
                # column band itself by much — if they do, the boundary
                # likely bisected two different columns' numbers.
                if spread > (x1 - x0) * 1.5 + right_edge_cluster_tolerance:
                    uncertain = True

        band = ColumnBand(header=header, x0=x0, x1=x1, geometry_uncertain=uncertain)
        bands.extend(_split_pack_column(band, body_tokens) if not uncertain else [band])

    return bands


def assign_token_to_column(token: OcrToken, columns: list[ColumnBand]) -> ColumnBand | None:
    for col in columns:
        if col.x0 <= token.bbox.cx < col.x1:
            return col
    return None
