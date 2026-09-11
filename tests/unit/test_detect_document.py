"""P4 unit tests for detect/document.py — distributor/company/period
extraction (IMPLEMENTATION_PLAN.md section 4.9 / P4 phase entry)."""
from __future__ import annotations

import datetime as dt

from pharma_di.detect.document import (
    detect_company,
    detect_distributor,
    detect_document_type,
    detect_period,
    header_region_text,
)
from pharma_di.schemas.canonical import DocumentType
from pharma_di.schemas.layout import BBox, ColumnBand, HeaderNode, Region, RegionType
from pharma_di.schemas.ocr import OcrToken


def _tok(text, x0, y0, x1=None, y1=None, conf=0.95):
    return OcrToken(text=text, bbox=BBox(x0=x0, y0=y0, x1=x1 or x0 + 40, y1=y1 or y0 + 20), confidence=conf)


_DISTRIBUTORS_CFG = {
    "distributors": [
        {
            "distributor_id": "acme-pharma",
            "name": "Acme Pharma Distributors",
            "aliases": ["ACME PHARMA"],
            "gstin": "16AHPPS4885B1ZW",
        },
    ],
    "companies": [
        {"company_name": "Zorvia Healthcare Limited", "aliases": ["ZORVIA HEALTHCARE", "ZORVIA HEALTHCARE LTD"]},
    ],
}


# --- header_region_text ------------------------------------------------------


def test_header_region_text_includes_only_page_header_and_statement_meta():
    tokens = [
        _tok("ACME", 0, 0),
        _tok("PHARMA", 50, 0),
        _tok("Period", 0, 40),
        _tok("STOCK", 0, 200),  # outside every region — e.g. a stock_table token
    ]
    regions = [
        Region(region_type=RegionType.page_header, bbox=BBox(x0=0, y0=0, x1=200, y1=30)),
        Region(region_type=RegionType.statement_meta, bbox=BBox(x0=0, y0=30, x1=200, y1=60)),
        Region(region_type=RegionType.stock_table, bbox=BBox(x0=0, y0=150, x1=200, y1=250)),
    ]
    assert header_region_text(tokens, regions) == "ACME PHARMA Period"


def test_header_region_text_empty_when_no_matching_regions():
    tokens = [_tok("ACME", 0, 0)]
    regions = [Region(region_type=RegionType.stock_table, bbox=BBox(x0=0, y0=0, x1=200, y1=30))]
    assert header_region_text(tokens, regions) == ""


# --- detect_distributor -------------------------------------------------------


def test_detect_distributor_prefers_exact_gstin_over_fuzzy_name():
    # "DISTRIBOTOR"-style OCR noise on the name would still score decently
    # via fuzzy match, but a real GSTIN match is unambiguous and checked first.
    text = "ACME PHARMA DISTRIBOTOR GSTIN : 16AHPPS4885B1ZW"
    dist_id, name, confidence = detect_distributor(text, _DISTRIBUTORS_CFG)
    assert dist_id == "acme-pharma"
    assert name == "Acme Pharma Distributors"
    assert confidence == 1.0


def test_detect_distributor_falls_back_to_fuzzy_alias_match():
    text = "ACME PHARMA 72 MAIN ROAD"
    dist_id, name, confidence = detect_distributor(text, _DISTRIBUTORS_CFG)
    assert dist_id == "acme-pharma"
    assert 0.0 < confidence <= 1.0


def test_detect_distributor_returns_none_when_nothing_matches():
    # The doc2.jpg case (IMPLEMENTATION_PLAN.md E2): OCR detected no
    # distributor text at all — must not guess, not even a low-confidence one.
    assert detect_distributor("HSN Code", _DISTRIBUTORS_CFG) == (None, None, 0.0)


# --- detect_company ------------------------------------------------------------


def test_detect_company_matches_header_text():
    assert detect_company("(ZORVIA HEALTHCARE LIMITE(ZH))", _DISTRIBUTORS_CFG) == "Zorvia Healthcare Limited"


def test_detect_company_checks_extra_texts_when_header_text_has_none():
    # doc6.jpg's case: the company name is absent from page_header/
    # statement_meta entirely and only survives as a section-label row
    # inside the table body.
    result = detect_company("STOCK & SALES ANALYSIS", _DISTRIBUTORS_CFG, extra_texts=["ZORVIA BEALTECARE LTD"])
    assert result == "Zorvia Healthcare Limited"


def test_detect_company_returns_none_when_nothing_matches():
    assert detect_company("HSN Code", _DISTRIBUTORS_CFG) is None


# --- detect_period ---------------------------------------------------------------


def test_detect_period_extracts_two_dates_in_order_regardless_of_surrounding_words():
    # Real doc1.jpg OCR text: "Period 29/06/2026 To 29/07/2026 From" — the
    # word "From" ends up AFTER both dates due to OCR reading order, but the
    # dates themselves are still in (from, to) order.
    text = "Period 29/06/2026 To 29/07/2026 From"
    assert detect_period(text) == (dt.date(2026, 6, 29), dt.date(2026, 7, 29))


def test_detect_period_handles_dash_separated_format():
    # Real doc5.jpg OCR text.
    assert detect_period("01-07-2026 - 30-07-2026") == (dt.date(2026, 7, 1), dt.date(2026, 7, 30))


def test_detect_period_single_date_returns_from_only():
    assert detect_period("Statement date 01/07/2026") == (dt.date(2026, 7, 1), None)


def test_detect_period_no_dates_returns_none_none():
    # Real doc6.jpg case: confirmed no date pattern anywhere in its OCR text.
    assert detect_period("STOCK & SALES ANALYSIS") == (None, None)


def test_detect_period_skips_invalid_calendar_dates():
    assert detect_period("32/13/2026 01/07/2026") == (dt.date(2026, 7, 1), None)


# --- detect_document_type -----------------------------------------------------


def _header(path, x0=0, x1=100):
    return HeaderNode(path=path, bbox=BBox(x0=x0, y0=0, x1=x1, y1=20))


def test_detect_document_type_product_level_when_product_name_column_present():
    columns = [
        ColumnBand(header=_header(["ITEM DESCRIPTION"]), x0=0, x1=100),
        ColumnBand(header=_header(["RATE"]), x0=100, x1=200),
    ]
    aliases = ["product", "product name", "item description"]
    assert detect_document_type(columns, aliases) == DocumentType.product_level


def test_detect_document_type_summary_when_no_product_name_column():
    # doc3.jpg's real shape: value-only column headers, no product/item
    # description column anywhere.
    columns = [
        ColumnBand(header=_header(["OPENING"]), x0=0, x1=100),
        ColumnBand(header=_header(["CLOSING", "VALUE[PT"]), x0=100, x1=200),
    ]
    aliases = ["product", "product name", "item description"]
    assert detect_document_type(columns, aliases) == DocumentType.summary


def test_detect_document_type_summary_for_empty_columns():
    assert detect_document_type([], ["product"]) == DocumentType.summary
