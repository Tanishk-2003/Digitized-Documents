"""Sloped-baseline row assembly (IMPLEMENTATION_PLAN.md section 4.4) — the
plan's central risk: "the product name in the left column visibly sits
above its own row's numbers on the right, because the paper is curved" —
horizontal y-banding would silently shift values onto the wrong product,
"the worst possible failure, because the output still looks well-formed."

A single global curve (tried first: one shared slope, then one shared
quadratic) is not sufficient. Direct measurement on doc6.jpg — comparing
each product-name seed to its own RATE value (dx~440), then to its own
OPENING VALUE (dx~700) — showed the true per-column vertical drift is
~0.064 near the seed column but ~0.099 further right: real curvature, and
not simply quadratic either. Extrapolating a low-order curve fit across the
table's full width doesn't survive contact with real data here.

Instead: walk outward column by column. Each row starts anchored at its own
seed; for every subsequent column band (left to right), estimate the LOCAL
slope from that single short hop (never a long extrapolation), assign that
column's tokens to their nearest predicted row, then advance each row's
anchor to what it was just assigned. This is the same principle that made
the RATE-column measurement trustworthy in the first place — short hops
keep row separation (~27px) large relative to the position error a slightly
wrong local slope can produce, however the true curve bends.

Every matching step — both the slope bootstrap and the final per-column
assignment — goes through one shared, properly one-to-one (conflict-
resolved) matcher (`_greedy_match`). An earlier version let the slope
bootstrap assign candidates independently per row, with no check for two
rows claiming the same token; on doc6.jpg's RATE column that let both row1
and row2 pick "408.86" as their own "nearest" candidate at slope=0, and the
resulting contaminated slope estimate (a spurious duplicate pairing pulling
the median) came out negative — sign-flipped from the true ~+0.064 — which
then cascaded into every row in that hop landing one row off, with no
uncertainty flag raised. A slope estimated from candidate pairs is only as
trustworthy as the matching that produced those pairs.
"""
from __future__ import annotations

import numpy as np

from pharma_di.schemas.layout import ColumnBand
from pharma_di.schemas.ocr import OcrToken

MatchResult = dict[int, tuple[OcrToken, float, "float | None"]]  # row_index -> (token, dist, second_best_dist)


class RowBaseline:
    def __init__(self, row_index: int, seed: OcrToken):
        self.row_index = row_index
        self.seed = seed
        self.tokens: list[OcrToken] = [seed]
        self.uncertain_tokens: set[int] = set()  # id()s of tokens flagged row_assignment_uncertain
        self.anchor_x = seed.bbox.cx
        self.anchor_y = seed.bbox.cy

    def predict(self, local_slope: float, x: float) -> float:
        return self.anchor_y + local_slope * (x - self.anchor_x)


def _greedy_match(
    rows: list[RowBaseline], band_tokens: list[OcrToken], local_slope: float, max_dist: float | None = None
) -> MatchResult:
    """One-to-one matching: each row gets at most one token and each token
    goes to at most one row, resolving the globally-closest (row, token)
    pairing first. This is the single source of truth for "what does this
    row's nearest candidate look like" — used both to bootstrap the local
    slope and to make the final assignment, so neither can silently allow
    two rows to claim the same token (see module docstring).

    `max_dist`, when given, excludes a pairing from actually being claimed
    if its distance exceeds it — but a row's OWN candidate list
    (`row_candidates`, used below for the "second best" ambiguity check)
    stays unfiltered, since a genuinely far-away second candidate already
    fails the caller's `(second_dist - dist) < ambiguity_margin` check on
    its own; there's no need to filter it here too. Only the claiming pass
    (`all_pairs`) needs the cap, and only the caller assembling the FINAL
    per-row cells should pass one at all (see assign_rows) — slope-fitting
    callers leave it unset, since one outlier pairing doesn't move a
    median fit across many real rows.
    """
    row_candidates: dict[int, list[tuple[float, OcrToken]]] = {}
    for row in rows:
        row_candidates[row.row_index] = sorted(
            ((abs(t.bbox.cy - row.predict(local_slope, t.bbox.cx)), t) for t in band_tokens),
            key=lambda p: p[0],
        )

    all_pairs = sorted(
        ((dist, row.row_index, tok) for row in rows for dist, tok in row_candidates[row.row_index]),
        key=lambda p: p[0],
    )

    claimed_tokens: set[int] = set()
    matched_rows: set[int] = set()
    result: MatchResult = {}
    for dist, row_idx, tok in all_pairs:
        if max_dist is not None and dist > max_dist:
            break  # all_pairs is sorted ascending — nothing further can qualify either
        if row_idx in matched_rows or id(tok) in claimed_tokens:
            continue
        matched_rows.add(row_idx)
        claimed_tokens.add(id(tok))
        second = next((d for d, t in row_candidates[row_idx] if id(t) != id(tok)), None)
        result[row_idx] = (tok, dist, second)
    return result


def _local_slope_for_hop(
    rows: list[RowBaseline], band_tokens: list[OcrToken], initial_slope: float = 0.0, rounds: int = 3
) -> float:
    """Estimate the slope for one short column-to-column hop: conflict-
    resolved match at the current slope guess, refit slope from those
    (now one-to-one, trustworthy) pairs, repeat. A couple of rounds is
    enough to converge over a single, short hop (unlike a global fit across
    the whole table width) — PROVIDED `initial_slope` is already close.

    Starting from 0.0 is not safe once accumulated x-distance from the seed
    grows: found on doc6.jpg's RATE hop (2nd column out), where at slope=0
    row2's anchor was genuinely raw-y-closer to row1's true rate value than
    row1's own anchor was (the real ~0.064 slope hadn't been accounted for
    yet) — the one-to-one matcher then locked in that wrong pairing before
    any refinement could correct it, and the slope refit *from* that wrong
    pairing came out negative, entrenching it further. Carrying the
    previous hop's converged slope forward as this hop's starting guess
    (the caller's job — see assign_rows) avoids ever needing a blind
    zero-slope guess after the first hop, since real page curvature is a
    smooth, shared property, not something that resets column to column.

    Deliberately uncapped (no max_dist here, unlike assign_rows' final
    claiming pass): the coarse starting guesses this is called with
    (_COARSE_SLOPE_STARTS) are intentionally far from the true slope before
    refinement narrows in, so early rounds legitimately produce large
    residuals for every row, real or phantom — a distance cap at this stage
    would reject the correct match before refinement ever gets a foothold
    (confirmed: doing this broke a clean, zero-noise synthetic case).
    """
    slope = initial_slope
    for _ in range(rounds):
        matches = _greedy_match(rows, band_tokens, slope)
        pair_slopes: list[float] = []
        for row in rows:
            if row.row_index not in matches:
                continue
            tok, _dist, _second = matches[row.row_index]
            dx = tok.bbox.cx - row.anchor_x
            if abs(dx) > 5:
                pair_slopes.append((tok.bbox.cy - row.anchor_y) / dx)
        if not pair_slopes:
            break
        new_slope = float(np.median(pair_slopes))
        converged = abs(new_slope - slope) < 1e-4
        slope = new_slope
        if converged:
            break
    return slope


def _total_residual(rows: list[RowBaseline], band_tokens: list[OcrToken], slope: float) -> float:
    matches = _greedy_match(rows, band_tokens, slope)
    return sum(dist for _tok, dist, _second in matches.values())


# Coarse starting guesses tried on every hop (see _best_hop_slope's
# docstring) — generous enough to cover real photographed page skew/
# curvature in either direction without being a fine-grained search; the
# iterative refinement in _local_slope_for_hop does the precise work from
# whichever of these (or the carried-forward slope) lands in the right basin.
_COARSE_SLOPE_STARTS = [0.0, 0.05, -0.05, 0.12, -0.12, 0.2, -0.2]


def _best_hop_slope(rows: list[RowBaseline], band_tokens: list[OcrToken], carried_slope: float | None) -> float:
    """Try several starting guesses for this hop's slope — the coarse fixed
    grid, plus the previous hop's converged slope when available — and keep
    whichever converges to the LOWEST total matched distance, not just
    whichever a single trajectory happened to reach.

    A single blind guess is not safe, even carrying the previous hop's
    slope forward: real curvature is not linear (measured on doc6.jpg:
    ~0.064 near the seed column, ~0.099 further right — a real, non-constant
    rate of change), so the true slope keeps moving hop to hop, and testing
    this module against a synthetic table with that same non-linearity
    showed even a carried-forward starting point can still converge to a
    self-consistent but wrong slope on some hops. Picking the candidate
    with the lowest total residual — the sum of every row's distance to its
    own matched token — is a direct, cheap way to prefer whichever
    trajectory actually explains the observed token positions best, rather
    than trusting any one starting guess's basin of attraction.
    """
    starts = list(_COARSE_SLOPE_STARTS)
    if carried_slope is not None:
        starts.append(carried_slope)

    best_slope, best_residual = None, None
    for start in starts:
        candidate = _local_slope_for_hop(rows, band_tokens, initial_slope=start)
        residual = _total_residual(rows, band_tokens, candidate)
        if best_residual is None or residual < best_residual:
            best_slope, best_residual = candidate, residual
    return best_slope if best_slope is not None else 0.0


def assign_rows(
    body_tokens: list[OcrToken],
    seed_tokens: list[OcrToken],
    columns: list[ColumnBand],
    ambiguity_margin_frac: float = 0.35,
    max_claim_dist_frac: float = 0.6,
    label_seed_ids: frozenset[int] = frozenset(),
) -> list[RowBaseline]:
    """One RowBaseline per seed (sorted top-to-bottom), with every body
    token assigned to a row by walking outward column-by-column from the
    seed column (see module docstring). A token whose distance to its
    second-nearest row differs from its nearest by less than
    `ambiguity_margin_frac` of the row spacing is flagged uncertain rather
    than silently assigned to whichever was marginally closer (section 4.4:
    "reject ambiguity") — likewise for any token a column-hop's matching
    couldn't cleanly claim (more candidates than rows, or lost every
    contest to a closer row).

    `max_claim_dist_frac` (of row_spacing) caps how far a row may reach to
    claim a token in the FINAL per-hop assignment (not in slope-fitting,
    where every row's pull still helps find the hop's true local slope —
    see below for why that split matters). Found on doc6.jpg: a row with no
    real data anywhere (a section-label row like "ZORVIA HEALTHCARE LTD"
    inserted into the table body) has no legitimate candidate early on, so
    its anchor never advances — but left unconstrained, a stale anchor's
    prediction, extrapolated over an ever-growing dx from later hops, can
    coincidentally land close enough to a REAL row's true value to win the
    one-to-one greedy match outright. Capping the claim distance at little
    more than half a row's own spacing — comfortably past the noise any
    genuine match should have, since half the spacing is already the
    natural boundary where a point becomes equidistant between two real
    adjacent rows — means a row this disconnected from its predicted
    position simply doesn't get a token in that column at all (a
    legitimately empty cell), rather than an implausible one. This alone
    is enough for `is_section_label_row` to correctly recognize such a row
    afterward (it now has no non-seed tokens).

    `label_seed_ids` (id()s of seed tokens already confirmed — typically by
    a first, uncapped-slope-fitting pass through this same function,
    checking which rows came back with no non-seed tokens — to head a
    section-label row) go further: they're excluded from EVERY hop's
    slope-fitting entirely, not just the final capped claim. Found on
    doc6.jpg: even though the cap above already stops a phantom row from
    winning a token, its stale anchor still PARTICIPATES in the uncapped
    slope search every hop, and can pull the "lowest total residual" choice
    toward a self-consistent-but-wrong "shift by one row" alias — row
    spacing (~27px) divided by one hop's dx (~127px) is ~0.21, dangerously
    close to one of _best_hop_slope's own coarse starting guesses (0.2) —
    corrupting a REAL row's own token assignment even though the phantom
    row's final claim was correctly capped away. A distance cap on
    slope-fitting itself can't fix this (confirmed: doing that broke a
    clean synthetic case, since coarse starts are deliberately far from
    the true slope before refinement narrows in — see _local_slope_for_hop).
    Removing the row from competition entirely, once it's already known to
    have nothing legitimate to contribute, has no such downside.
    """
    if not seed_tokens or not columns:
        return []

    seeds_sorted = sorted(seed_tokens, key=lambda t: t.bbox.cy)
    rows = [RowBaseline(i, seed) for i, seed in enumerate(seeds_sorted)]
    row_by_index = {r.row_index: r for r in rows}
    competing_rows = [r for r in rows if id(r.seed) not in label_seed_ids]

    seed_ys = [t.bbox.cy for t in seeds_sorted]
    if len(seed_ys) >= 2:
        gaps = [seed_ys[i + 1] - seed_ys[i] for i in range(len(seed_ys) - 1)]
        row_spacing = sorted(gaps)[len(gaps) // 2]
    else:
        row_spacing = 30.0
    ambiguity_margin = ambiguity_margin_frac * row_spacing
    max_claim_dist = max_claim_dist_frac * row_spacing

    columns_sorted = sorted(columns, key=lambda c: c.x0)
    seed_column = columns_sorted[0]
    running_slope: float | None = None  # carried forward once the first hop has run — see _best_hop_slope

    for column in columns_sorted[1:]:
        band_tokens = [t for t in body_tokens if column.x0 <= t.bbox.cx < column.x1]
        if not band_tokens:
            continue

        # Slope-fitting itself stays distance-uncapped — its coarse starting
        # guesses (_COARSE_SLOPE_STARTS) are deliberately far from the true
        # slope before iterative refinement narrows in, so early rounds
        # legitimately produce large residuals for every row, phantom or
        # real; capping BY DISTANCE here rejects the correct match before
        # refinement gets a foothold (confirmed: doing this broke a clean
        # synthetic case with zero noise). Known label rows are still
        # excluded from it by REMOVING them from the row list (competing_rows)
        # rather than by distance — see the label_seed_ids docstring above.
        local_slope = _best_hop_slope(competing_rows, band_tokens, carried_slope=running_slope)
        running_slope = local_slope
        matches = _greedy_match(competing_rows, band_tokens, local_slope, max_dist=max_claim_dist)

        claimed_tokens: set[int] = set()
        for row_idx, (tok, dist, second_dist) in matches.items():
            row = row_by_index[row_idx]
            row.tokens.append(tok)
            claimed_tokens.add(id(tok))
            # Two ambiguity checks, not one: does *this row* have a close
            # runner-up token (checked via second_dist, from the row's own
            # candidate list) — and, separately, does *this token* have a
            # close runner-up row that could just as plausibly have claimed
            # it? A band with only one token per contested slot has no
            # "second token" for the first check to ever compare against,
            # even when two rows were genuinely both close to it — found
            # writing a test for exactly that (two rows, one token
            # equidistant between them).
            closest_other_row_dist = min(
                (
                    abs(tok.bbox.cy - r.predict(local_slope, tok.bbox.cx))
                    for r in competing_rows
                    if r.row_index != row_idx
                ),
                default=None,
            )
            row_has_close_runner_up = second_dist is not None and (second_dist - dist) < ambiguity_margin
            token_has_close_runner_up_row = closest_other_row_dist is not None and (
                closest_other_row_dist - dist
            ) < ambiguity_margin
            if row_has_close_runner_up or token_has_close_runner_up_row:
                row.uncertain_tokens.add(id(tok))
            row.anchor_x, row.anchor_y = tok.bbox.cx, tok.bbox.cy

        # Tokens no row claimed (more candidates than rows in this band, they
        # lost every contest to a closer row, or every remaining pairing
        # exceeded max_claim_dist) still get placed — never silently
        # dropped — on the nearest row by the hop's local slope, explicitly
        # flagged uncertain since a clean claim didn't place them.
        leftover = [t for t in band_tokens if id(t) not in claimed_tokens]
        for tok in leftover:
            nearest_row = min(competing_rows, key=lambda r: abs(tok.bbox.cy - r.predict(local_slope, tok.bbox.cx)))
            nearest_row.tokens.append(tok)
            nearest_row.uncertain_tokens.add(id(tok))

    # The seed column's own extra tokens (besides each row's own seed) go
    # through the same nearest-anchor logic, using each row's un-advanced
    # seed position (slope irrelevant this close to the anchor itself). A
    # confirmed label row is excluded here too — it's already known to have
    # no real data, and the leftover/extra fallbacks exist so nothing is
    # silently dropped, not to hand stray tokens to a row already ruled out.
    seed_band_extra = [t for t in body_tokens if seed_column.x0 <= t.bbox.cx < seed_column.x1 and t not in seed_tokens]
    for tok in seed_band_extra:
        nearest_row = min(competing_rows, key=lambda r: abs(tok.bbox.cy - r.seed.bbox.cy))
        nearest_row.tokens.append(tok)
        nearest_row.uncertain_tokens.add(id(tok))

    return rows


def is_section_label_row(row: RowBaseline, seed_column_x1: float) -> bool:
    """A row whose only tokens fall in the seed (leftmost) column — no
    numeric/value cells anywhere else — is a section label (e.g. "ZORVIA
    HEALTHCARE LTD." appearing as its own row inside the MARG table body,
    finding #10), not a product. It updates company_name rather than
    becoming a line item."""
    non_seed_tokens = [t for t in row.tokens if t.bbox.cx >= seed_column_x1]
    return len(non_seed_tokens) == 0
