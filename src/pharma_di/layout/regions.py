"""Region segmentation (IMPLEMENTATION_PLAN.md section 4.2): a page is not
guaranteed to be a single table (CLAUDE.md) — classify lines of OCR tokens
into typed regions by anchor text and geometry before anything is treated
as the Stock & Sale grid.

Built on OCR token geometry rather than PP-StructureV3's vision-based
region detection: PP-StructureV3 was tested this session and is technically
functional but took ~8 minutes on a single small crop (measured, not
assumed) in this environment's unaccelerated inference path (see
ocr/paddle_engine.py's documented PIR/oneDNN issue) — impractical for a
"lightweight infra" MVP. The plan's own hardest sub-problems (columns, rows,
headers — sections 4.3-4.5) were already specified as deterministic
algorithms over anchor text and geometry, which is exactly what OCR tokens
provide; this module extends the same approach to region typing.

Classification runs in a specific priority order — most-certain anchors
first — because a page's regions genuinely are ordered top-to-bottom, and
picking off the certain ones (a PURCHASE DETAIL block, a TOTAL row, a footer
signature line) before guessing at the rest avoids misclassifying, e.g., a
footer's "For New Tripura Pharmaco" line as another company-name row.
"""
from __future__ import annotations

from rapidfuzz import fuzz

from pharma_di.config import load_column_mappings
from pharma_di.layout.baseline import cluster_into_lines
from pharma_di.layout.columns import is_numeric
from pharma_di.layout.headers import is_leaf_label
from pharma_di.schemas.layout import BBox, Region, RegionType
from pharma_di.schemas.ocr import OcrToken

FOOTER_ANCHORS = ["thanking you", "authorised signatory", "authorized signatory", "page no", "generated on"]
PURCHASE_DETAIL_ANCHORS = ["purchase detail"]
TOTALS_ANCHORS = ["total", "value (cost price)", "grand total"]
STATEMENT_META_ANCHORS = ["period", "stock & sale", "stock and sale", "sales analysis", " from ", " to "]


class TypedLine:
    def __init__(self, tokens: list[OcrToken], region_type: RegionType):
        self.tokens = tokens
        self.region_type = region_type

    @property
    def text(self) -> str:
        return " ".join(t.text for t in self.tokens)

    @property
    def bbox(self) -> BBox:
        return BBox(
            x0=min(t.bbox.x0 for t in self.tokens),
            y0=min(t.bbox.y0 for t in self.tokens),
            x1=max(t.bbox.x1 for t in self.tokens),
            y1=max(t.bbox.y1 for t in self.tokens),
        )


ANCHOR_FUZZY_THRESHOLD = 80


def _contains_any(text_upper: str, anchors: list[str]) -> bool:
    """Fuzzy substring match, not exact containment — OCR noise reaches
    anchor phrases too (found on doc5.jpg: "PURCHASE DETAIL" was recognized
    as "PORCHASE  DETATL", which no exact-substring check would ever match).
    `fuzz.partial_ratio` is built for exactly this: how well a short anchor
    matches *somewhere* inside a longer, noisy line.

    Each anchor is skipped unless the candidate line has at least half as
    many characters as the anchor itself. `partial_ratio` scores the BEST
    alignment of the shorter string against the longer one, which degenerates
    on very short candidates: found on doc9.jpg, a text-detection gap split a
    lone "S" off "SALES ANALYSIS" into its own one-token line, and
    `partial_ratio("PURCHASE DETAIL", "S")` trivially scored 100 (any single
    character that appears in the anchor "matches" it). That one false
    trigger reclassified the rest of the page — the real stock table and the
    footer identity block — as a purchase-detail region, since classification
    treats everything after a trigger as the same region until the next
    anchor. A real noisy OCR reading of a multi-word anchor still keeps
    roughly half its characters (as "PORCHASE  DETATL" did); a stray
    fragment doesn't.
    """
    stripped_len = len(text_upper.strip())
    return any(
        stripped_len >= len(a) / 2 and fuzz.partial_ratio(a.upper(), text_upper) >= ANCHOR_FUZZY_THRESHOLD
        for a in anchors
    )


def matches_totals_row(tokens: list[OcrToken]) -> bool:
    """Public (not `_`-prefixed) because validate/totals.py also needs it:
    R2's totals cross-foot has to re-identify the same totals line among a
    totals region's tokens that this module already knows how to spot, once
    they're re-clustered by their own baseline (a totals region's bbox can
    span more than this one line — see validate/totals.py's own docstring
    for why)."""
    if not tokens:
        return False
    first_text = tokens[0].text.strip().lower().rstrip(".:")
    return any(fuzz.ratio(first_text, a) >= 75 for a in TOTALS_ANCHORS) or "cost price" in " ".join(
        t.text for t in tokens
    ).lower()


def _all_column_aliases() -> set[str]:
    mappings = load_column_mappings()
    return {a.lower() for entry in mappings.values() for a in entry.get("aliases", [])}


_HEADER_ALIAS_MATCH_THRESHOLD = 80

# Only tokens at least this long are eligible for the partial_ratio fallback
# below. Picked to separate two real, verified cases: doc1.jpg's own "Stock"
# column (5 chars) must NOT partial-match "opening stock" (mapping/fuzzy.py's
# module docstring documents this exact subset-inflation failure mode and
# deliberately avoids partial_ratio for column-to-field resolution for that
# reason), while doc9.jpg's "ESCRIPTION" (10 chars, OCR dropped "ITEM D"
# entirely from "ITEM DESCRIPTION") legitimately needs it. 8 sits strictly
# between the two.
_PARTIAL_MATCH_MIN_TOKEN_LEN = 8


def _matches_any_alias(normalized: str, aliases: set[str]) -> bool:
    """Whole-string `ratio` first (unchanged, original behavior — every
    header match doc1-doc6's tests already rely on goes through this path
    exactly as before). A `partial_ratio` fallback only fires for longer
    tokens (see _PARTIAL_MATCH_MIN_TOKEN_LEN) that ratio scores too low on
    purely because of a length mismatch with a longer alias — found on
    doc9.jpg: "ESCRIPTION" is a clean 10-of-17-character substring match of
    "item description" that partial_ratio finds immediately (100) but ratio
    scores at 76.9 (just under threshold) solely because of the missing
    "item d" prefix. Deliberately NOT applied to short tokens: partial_ratio
    degenerates there (see _contains_any's docstring for the "S" case), and
    a real short header word being a legitimate subset of a longer alias's
    words (doc1.jpg's "Stock" vs "opening stock") is a different, weaker
    signal that this project already special-cased once before
    (mapping/fuzzy.py's token_set_ratio/token_sort_ratio combination) — reuse
    that lesson here rather than reintroduce the same failure mode via a
    different function.
    """
    for alias in aliases:
        if fuzz.ratio(normalized, alias) >= _HEADER_ALIAS_MATCH_THRESHOLD:
            return True
    if len(normalized) < _PARTIAL_MATCH_MIN_TOKEN_LEN:
        return False
    for alias in aliases:
        if len(normalized) < len(alias) / 2:
            continue
        if fuzz.partial_ratio(normalized, alias) >= _HEADER_ALIAS_MATCH_THRESHOLD:
            return True
    return False


def _count_header_matches(tokens: list[OcrToken], aliases: set[str]) -> int:
    matches = 0
    for t in tokens:
        normalized = t.text.strip().lower()
        if is_leaf_label(t.text) or _matches_any_alias(normalized, aliases):
            matches += 1
    return matches


def _find_header_window(lines: list[list[OcrToken]], start_from: int) -> tuple[int, int] | None:
    """Find the (start, end-exclusive) index range of consecutive lines that
    together form the stock-table header row.

    Real MARG-format headers cascade across several of cluster_into_lines'
    natural line breaks — found on doc6.jpg: "ITEM DESCRIPTION" (y0=280) and
    "RATE" (y0=306) sit as their own separate one-token lines, well above the
    OPENING/RECEIPT/ISSUE/CLOSING/DUMP+QTY+VALUE cluster (y0=339-466) that
    actually crosses the 3-match threshold on its own. Testing single lines
    in isolation never recognizes ITEM DESCRIPTION/RATE as part of the
    header at all — they'd be left behind in page_header, and a table built
    later without them would be missing two real columns. A growing window,
    capped by vertical span rather than line count (the real cascade here is
    ~186px), fixes this at the source rather than patching header/body
    membership after the fact.

    Once 3 matches have accumulated (header confirmed), the window stops
    growing at the FIRST candidate line that contributes zero new matches —
    no grace period. An earlier version tolerated a fixed number of
    zero-match lines before stopping (to bridge doc6.jpg's own cascade,
    where interior lines like "OPENING DOM2" legitimately score 0 on their
    own). That was empirically wrong on real data: since the loop's own
    break-check runs *before* consuming a candidate line, any grace period
    >0 always consumes at least one line past the last real match before it
    can register as "no new match" and stop — verified by hand-tracing
    against the actual OCR geometry for doc6/doc1/doc2/doc5, which is
    exactly the bug that let a trailing section-label or product-name line
    (e.g. "ZORVIA HEALTHCARE LTD", "ZCRVIA HEALTHCARE LIDMITE(20)") get
    pulled into the header as a spurious column no matter which small
    integer grace period was tried (0, 1, 2 all tested; each failed a
    different document). The fix is to not need a grace period at all: as
    long as the window hasn't hit 3 matches yet, ANY line is still
    accepted (this is what correctly bridges doc6's own 0-match interior
    lines, since they occur before confirmation) — grace is only removed
    for what comes *after* confirmation, where a 0-match line reliably means
    "real header content has ended," not "header still cascading."
    """
    aliases = _all_column_aliases()
    n = len(lines)
    max_span_px = 250.0

    for start in range(start_from, n):
        if _count_header_matches(lines[start], aliases) == 0:
            continue
        window_top = min(t.bbox.y0 for t in lines[start])
        accumulated = list(lines[start])
        end = start + 1
        matches = _count_header_matches(accumulated, aliases)

        while end < n:
            candidate_bottom = max(t.bbox.y1 for t in lines[end])
            if candidate_bottom - window_top > max_span_px:
                break
            new_matches = _count_header_matches(lines[end], aliases)
            if matches >= 3 and new_matches == 0:
                break
            accumulated.extend(lines[end])
            matches = _count_header_matches(accumulated, aliases)
            end += 1

        if matches >= 3:
            return start, end
    return None


def segment_regions(tokens: list[OcrToken]) -> list[Region]:
    """Classify every token on a page into typed regions. Returns Region
    objects (type + bbox); callers needing the token-level detail for a
    specific region should re-filter `tokens` by that Region's bbox, or use
    `stock_table_header_and_body` below during table assembly."""
    typed_lines, _header_window = _segment_lines(tokens)
    return _lines_to_regions(typed_lines)


def stock_table_header_and_body(tokens: list[OcrToken]) -> tuple[list[OcrToken], list[OcrToken]]:
    """Split a page's tokens into (header_tokens, body_tokens) for its
    stock_table region specifically — header_tokens is exactly the window
    `_find_header_window` identified (feeds layout/headers.py); body_tokens
    is every other line typed stock_table (feeds layout/columns.py and
    layout/rows.py). Empty lists if no stock_table region was found at all.

    KNOWN LIMITATION, not silently papered over: this depends on
    `cluster_into_lines`'s single whole-page slope correctly grouping the
    header's own lines. That is verified working for the MARG family
    (doc4.jpg/doc5.jpg/doc6.jpg's shared template — doc6.jpg's extraction
    matches hand-transcribed ground truth across every field with zero
    uncertain cells) and, since the zero-grace-period stopping rule and
    numeric-token rerouting below, for doc2.jpg's ruled grid too. doc1.jpg
    (single-line, ~20-row whitespace table, tight row spacing) remains a
    known, real limitation: its last true header line and its first body
    row's overflow can land in the *same* cluster_into_lines line (e.g.
    "Stock Quantity Return Outward Quantity 1440.00 UNSOLD" — trailing
    header words immediately followed by that row's own value and stock
    status, confirmed by direct inspection, not assumed), and numeric-token
    rerouting alone can't separate a non-numeric stray value ("UNSOLD")
    from real header text sharing that same line. A token-level rewrite of
    the header search (bypassing line-clustering entirely) was tried in an
    earlier session and made every document's result worse, including
    doc6.jpg's previously-exact match — reverted rather than shipped.
    Fixing doc1.jpg properly needs the header search to use the same
    robust, multi-hop slope-estimation layout/rows.py now has for row
    assembly, adapted to the "find one boundary" problem — flagged as a
    concrete next step, not attempted further given the risk of
    regressing the formats this stage now handles correctly.
    """
    typed_lines, header_window = _segment_lines(tokens)
    if header_window is None:
        return [], []

    # _segment_lines assigns lines to TypedLine objects in the same
    # (cluster_into_lines) order it internally computed header_window
    # against, so indices line up directly — no need to re-cluster or fall
    # back to token-identity matching (which risked misbehaving on two
    # short tokens with identical text/bbox/confidence).
    header_start, header_end = header_window
    header_tokens: list[OcrToken] = []
    body_tokens: list[OcrToken] = []
    for i, ln in enumerate(typed_lines):
        if ln.region_type != RegionType.stock_table:
            continue
        if header_start <= i < header_end:
            # A header-window line can still carry one stray body token —
            # found on doc2.jpg: "300490 Free Revd. Free Sold Total Sold"
            # mixes a genuine product/HSN code with 3 real trailing header
            # phrases in one cluster_into_lines line (tight vertical
            # spacing between the header's last row and the first body
            # row). A bare numeric token is never legitimate header text
            # (see columns.py's is_numeric), so route it to body_tokens
            # instead of dropping it — it's real data, just misfiled by
            # line-clustering, and row assembly picks it up by geometry
            # regardless of which "line" it came from.
            #
            # Checked per space-separated part, not just the whole token —
            # found on doc1.jpg: OCR fused a value and its stock-status word
            # into one text box, "1440.00 UNSOLD", which is not numeric as a
            # whole string but is obviously body data (real header text
            # never contains a numeric sub-word; even OCR-garbled header
            # words like "DOM2" keep letters mixed with a digit throughout,
            # never a clean numeral as one whitespace-delimited piece).
            for t in ln.tokens:
                is_body = any(is_numeric(part) for part in t.text.split())
                (body_tokens if is_body else header_tokens).append(t)
        else:
            body_tokens.extend(ln.tokens)

    return header_tokens, body_tokens


def _segment_lines(tokens: list[OcrToken]) -> tuple[list[TypedLine], tuple[int, int] | None]:
    if not tokens:
        return [], None

    # Auto-fit slope (not forced flat, and not bypassed via a token-level
    # search — both were tried and reverted; see stock_table_header_and_body's
    # docstring for the full account) — but with a much smaller gap_frac
    # than cluster_into_lines' own default (0.55 -> 0.15). At the default,
    # a real table's ~15-20 similar body rows collapse into one giant "line"
    # no matter the slope (verified: doc1.jpg and doc6.jpg both hit
    # max-line sizes in the hundreds at gap_frac=0.55, for different
    # underlying reasons). At gap_frac=0.15, both instead over-split into
    # many small pieces (doc1: max 12 tokens/line; doc6: max 13) — which is
    # exactly what _find_header_window's growth loop below already exists
    # to handle: it was built because doc6.jpg's own header cascades across
    # several separate line-clusters, so accumulating several small,
    # correctly-separated pieces is the design center, not an edge case.
    lines, _slope = cluster_into_lines(tokens, gap_frac=0.15)
    n = len(lines)

    # Pre-pass: locate the header window by scanning past any lines that are
    # themselves clearly something else (purchase-detail/footer anchors) —
    # see _find_header_window's docstring for why this must be windowed
    # rather than checked one line at a time.
    header_window: tuple[int, int] | None = None
    scan_from = 0
    while header_window is None and scan_from < n:
        text_upper = " ".join(t.text for t in lines[scan_from]).upper()
        if _contains_any(text_upper, PURCHASE_DETAIL_ANCHORS) or _contains_any(text_upper, FOOTER_ANCHORS):
            scan_from += 1
            continue
        header_window = _find_header_window(lines, scan_from)
        break  # _find_header_window already scans forward internally

    header_start, header_end = header_window if header_window else (None, None)

    typed: list[TypedLine] = []
    in_purchase_detail = False
    in_footer = False
    seen_table_header = False

    for i, line in enumerate(lines):
        text_upper = " ".join(t.text for t in line).upper()

        if _contains_any(text_upper, PURCHASE_DETAIL_ANCHORS):
            in_purchase_detail = True
            in_footer = False
            typed.append(TypedLine(line, RegionType.purchase_detail))
            continue

        if _contains_any(text_upper, FOOTER_ANCHORS):
            in_purchase_detail = False
            in_footer = True
            typed.append(TypedLine(line, RegionType.page_footer))
            continue

        if in_purchase_detail:
            # Once inside a purchase-detail block, its own data rows don't
            # re-trigger the anchor — everything belongs to the block until
            # a footer/new-section anchor ends it.
            typed.append(TypedLine(line, RegionType.purchase_detail))
            continue

        if in_footer:
            # Same persistence, and for the same reason: found on doc1.jpg
            # — "For New Tripura Pharmaco" sits between "Thanking You" and
            # "(Authorised Signatory)" and matches no footer anchor itself,
            # so without this flag it fell through to the seen_table_header
            # catch-all below and came back as a spurious second
            # stock_table region after the footer had already started.
            typed.append(TypedLine(line, RegionType.page_footer))
            continue

        if header_start is not None and header_start <= i < header_end:
            seen_table_header = True
            typed.append(TypedLine(line, RegionType.stock_table))
            continue

        if seen_table_header and matches_totals_row(line):
            typed.append(TypedLine(line, RegionType.totals))
            continue

        if seen_table_header:
            typed.append(TypedLine(line, RegionType.stock_table))
            continue

        if _contains_any(text_upper, STATEMENT_META_ANCHORS):
            typed.append(TypedLine(line, RegionType.statement_meta))
            continue

        typed.append(TypedLine(line, RegionType.page_header))

    return typed, header_window


def _lines_to_regions(typed_lines: list[TypedLine]) -> list[Region]:
    if not typed_lines:
        return []

    regions: list[Region] = []
    current_type = typed_lines[0].region_type
    current_lines = [typed_lines[0]]

    def flush():
        bboxes = [ln.bbox for ln in current_lines]
        region_bbox = BBox(
            x0=min(b.x0 for b in bboxes),
            y0=min(b.y0 for b in bboxes),
            x1=max(b.x1 for b in bboxes),
            y1=max(b.y1 for b in bboxes),
        )
        regions.append(Region(region_type=current_type, bbox=region_bbox))

    for ln in typed_lines[1:]:
        if ln.region_type == current_type:
            current_lines.append(ln)
        else:
            flush()
            current_type = ln.region_type
            current_lines = [ln]
    flush()
    return regions
