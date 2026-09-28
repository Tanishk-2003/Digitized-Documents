"""Document detection (IMPLEMENTATION_PLAN.md P4 / section 4.9's
detect_document node): distributor, company, and statement period read off
page_header/statement_meta text, resolved against the distributor master
(config/distributors.yaml) rather than persisted as free OCR text — CLAUDE.md:
"Resolved against a distributor master, not free text."

Real per-document header/statement_meta text (read directly off the cached
OCR output for all 5 documents that reach OCR) informed every design choice
below:

- doc1.jpg: "STOCK ANDSALLE STATEMENT Period 29/06/2026 To 29/07/2026 From
  TRIPURA PHARMACO NEW ... ZORVIA HEALTHCARE LIMITED ..." — OCR's own
  reading order scrambles word order ("To" before "From"), so period
  extraction below matches raw date substrings in the order they appear,
  not the words around them.
- doc3.jpg: "NABIN DRUG CENTRE ... From :01/07/2026 To :31/07/2026" — a
  clean, differently-formatted (slash, colon) period string; no company
  name anywhere in page_header/statement_meta text at all, confirmed by
  direct inspection, even though CLAUDE.md's own table says this document
  covers Eris Lifescience. A real, honest gap — not fabricated here.
- doc5.jpg: "B.N.DRUG DISTRIBOTOR ... GSTIN : 16ADOPD2894E1ZH" plus,
  separately, "(ZORVIA HEALTHCARE LIMITE(ZH)) 01-07-2026 - 30-07-2026" — a
  DASH-separated date format, different from doc1/doc3's slashes, and a
  real, exact-match GSTIN (matches config/distributors.yaml's
  bn-drug-distributor entry digit-for-digit) that's a far stronger signal
  than fuzzy name matching on OCR noise like "DISTRIBOTOR".
- doc6.jpg: page_header/statement_meta contain NEITHER a company name NOR
  any date pattern at all (confirmed: zero tokens anywhere on the page
  match a date regex). Its company name ("ZORVIA...LTD") instead survives
  only as a `TableGrid.section_label_row` inside the table body — the same
  row layout/rows.py's is_section_label_row exists to catch. Its period is
  a genuine, honestly-unresolved gap (the source photograph may simply not
  frame whatever line would have shown it), not a bug in this module.
- doc2.jpg: page_header/statement_meta text is just "HSN Code" — this is
  the documented E2 finding (IMPLEMENTATION_PLAN.md section 8b): "NABIN
  DRUG CENTRE" sits at a sharp paper fold crease that PP-OCR's text
  *detection* (not recognition) misses entirely. Neither distributor nor
  company resolves for this document, and that must surface as a
  needs_review reason (see graph/nodes.py::detect_document), not silently
  proceed with null identity fields.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

from rapidfuzz import fuzz

from pharma_di.schemas.canonical import DocumentType
from pharma_di.schemas.layout import ColumnBand, Region, RegionType
from pharma_di.schemas.ocr import OcrToken

# Matches P5's own fuzzy-accept floor (IMPLEMENTATION_PLAN.md section 4.6:
# ">=90 accept; 75-90 accept but mark low-confidence") — reusing the same
# threshold philosophy rather than inventing a separate number for identity
# resolution.
_NAME_FUZZY_THRESHOLD = 75.0

# Standard 15-character GSTIN shape: 2-digit state code, 10-char PAN
# (5 letters, 4 digits, 1 letter), 1-char entity code, 'Z' by convention,
# 1 checksum char. 2 + 10 + 1 + 1 + 1 = 15 — verified against a real GSTIN
# (doc5.jpg's config entry, "16ADOPD2894E1ZH").
_GSTIN_PATTERN = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]\b")

# Deliberately NOT anchored to surrounding words ("Period", "From", "To") —
# OCR's own reading order scrambles them (see module docstring, doc1.jpg).
# The two dates themselves reliably appear in (from, to) order regardless.
_DATE_PATTERN = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")


def header_region_text(tokens: list[OcrToken], regions: list[Region]) -> str:
    """Concatenated text of every page_header/statement_meta region, in
    reading order — the two region types (section 4.2) a distributor prints
    its own identity and the statement period into."""
    header_bboxes = [r.bbox for r in regions if r.region_type in (RegionType.page_header, RegionType.statement_meta)]
    if not header_bboxes:
        return ""
    matched = [
        t
        for t in tokens
        if any(b.x0 <= t.bbox.cx <= b.x1 and b.y0 <= t.bbox.cy <= b.y1 for b in header_bboxes)
    ]
    return " ".join(t.text for t in sorted(matched, key=lambda t: (t.bbox.y0, t.bbox.x0)))


def detect_distributor(
    text: str, distributors_cfg: dict[str, Any], extra_texts: list[str] | None = None
) -> tuple[str | None, str | None, float]:
    """Returns (distributor_id, distributor_name, confidence in [0, 1]).

    GSTIN, when present, is checked first and short-circuits to an exact
    match: a distributor's own tax ID misprinting into a false positive is
    far less likely than a fuzzy name match misfiring on OCR noise (found on
    doc5.jpg: "B.N.DRUG DISTRIBOTOR" is garbled enough that name-fuzzy-match
    confidence alone would be worth cross-checking, but its GSTIN reads
    perfectly and matches config/distributors.yaml exactly). Falls through
    to fuzzy alias matching otherwise, at the same acceptance threshold P5's
    mapping tiers use (section 4.6).

    `extra_texts` mirrors detect_company's own fallback-candidates pattern:
    pass whole-page OCR text here (see graph/nodes.py::detect_document) so a
    distributor identity block that region segmentation didn't classify as
    page_header/statement_meta still resolves. Found on doc9.jpg: "M/S ARATI
    ENTERPRISE" sits in a signature-block line ("Authorised By:") that
    doesn't match any known page_footer anchor phrase, so it landed in
    whatever region type the classifier fell back to instead — chasing every
    real-world phrasing of a signature block is a losing game, so this
    fallback searches the whole page instead of the region text alone.
    header/statement_meta text stays the FIRST candidate (highest-priority
    on a tie) precisely because it's the reliable, common case; the full
    page is a last-resort net, not the primary signal.
    """
    candidates = [text, *(extra_texts or [])]
    combined_compact = "".join(c.replace(" ", "") for c in candidates if c)
    gstin_match = _GSTIN_PATTERN.search(combined_compact)
    if gstin_match:
        found = gstin_match.group(0)
        for d in distributors_cfg.get("distributors", []):
            if d.get("gstin") == found:
                return d["distributor_id"], d["name"], 1.0

    best: tuple[str, str, float] | None = None
    for d in distributors_cfg.get("distributors", []):
        for alias in [d["name"], *d.get("aliases", [])]:
            for candidate_text in candidates:
                if not candidate_text:
                    continue
                score = fuzz.partial_ratio(alias.upper(), candidate_text.upper())
                if score >= _NAME_FUZZY_THRESHOLD and (best is None or score > best[2]):
                    best = (d["distributor_id"], d["name"], score / 100.0)
    return best if best is not None else (None, None, 0.0)


def detect_company(text: str, distributors_cfg: dict[str, Any], extra_texts: list[str] | None = None) -> str | None:
    """Fuzzy match against config/distributors.yaml's companies list.

    Also checks `extra_texts` — pass a TableGrid's section_label_rows
    values here. Some MARG documents print the company name only as a row
    inside the table body, never in the page header at all (doc6.jpg:
    "ZORVIA...LTD" is a section-label row — confirmed absent from
    page_header/statement_meta text entirely, by direct inspection).
    """
    candidates = [text, *(extra_texts or [])]
    best: tuple[str, float] | None = None
    for c in distributors_cfg.get("companies", []):
        for alias in [c["company_name"], *c.get("aliases", [])]:
            for candidate_text in candidates:
                if not candidate_text:
                    continue
                score = fuzz.partial_ratio(alias.upper(), candidate_text.upper())
                if score >= _NAME_FUZZY_THRESHOLD and (best is None or score > best[1]):
                    best = (c["company_name"], score)
    return best[0] if best is not None else None


def detect_period(text: str) -> tuple[dt.date | None, dt.date | None]:
    """First two valid date-like substrings in reading order become
    (statement_from, statement_to). An invalid calendar date (rare OCR
    digit-swap) is skipped rather than raising — this is best-effort
    extraction from noisy text, not a validated user input."""
    dates: list[dt.date] = []
    for m in _DATE_PATTERN.finditer(text):
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            dates.append(dt.date(year, month, day))
        except ValueError:
            continue
    if len(dates) >= 2:
        return dates[0], dates[1]
    if len(dates) == 1:
        return dates[0], None
    return None, None


def detect_document_type(columns: list[ColumnBand], product_name_aliases: list[str]) -> DocumentType:
    """product_level if the table has a column that fuzzy-matches a known
    product-name alias (config/column_mappings.yaml's product_name_raw
    entry, reused here rather than duplicating the vocabulary); summary
    otherwise.

    This is deliberately NOT based on row_count or column_count: doc3.jpg
    (CLAUDE.md's own summary-only example — one company-level row, values
    only) still produces a small multi-"row" TableGrid from
    layout/tables.py's assembly (confirmed by direct inspection — the
    value-only summary block has no product-name seed column at all, so
    assemble_stock_table's leftmost-column-is-the-seed assumption doesn't
    cleanly apply and its line-wrapping gets misread as several short
    rows). Row/column counts alone can't distinguish that from a genuinely
    small per-product table; the presence of a real product-name-shaped
    column can.
    """
    for column in columns:
        header_text = " ".join(column.header.path)
        for alias in product_name_aliases:
            if fuzz.partial_ratio(alias.upper(), header_text.upper()) >= _NAME_FUZZY_THRESHOLD:
                return DocumentType.product_level
    return DocumentType.summary
