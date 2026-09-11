"""P6 integration test: 3-level canonical assembly against real, fully
resolved documents (IMPLEMENTATION_PLAN.md P6).

Gated on the OCR cache being warm (same reasoning as test_ocr_real_images.py)
— assembly runs on layout/tables.py + mapping/resolver.py's real output,
which both depend on OCR.

Assertions reflect ACTUAL assembled output (inspected directly before
writing this file), including one honest finding: doc3.jpg's "opening_quantity"
field is semantically wrong (it holds a currency VALUE, not a quantity) —
a downstream consequence of the already-documented P3 header-fragmentation
limitation on this specific document (its "OPENING" header lost its
"VALUE[PTS]" pairing during header reconstruction), not a new P6 defect.
`test_doc3_summary_values_reflect_the_known_p3_limitation_honestly` pins
this down explicitly so it's never silently "fixed" by accident without
someone noticing the root cause moved.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pytest

from pharma_di.assemble.canonical import assemble_document
from pharma_di.config import load_column_mappings, load_distributors, load_settings, load_templates
from pharma_di.detect.document import detect_company, detect_distributor, detect_document_type, detect_period, header_region_text
from pharma_di.layout.regions import segment_regions
from pharma_di.layout.tables import assemble_stock_table
from pharma_di.mapping.dictionary import load_field_entries
from pharma_di.mapping.resolver import DictionaryResolver, ReviewQueueResolver, resolve_header
from pharma_di.ocr.cache import OcrCache, hash_image_file
from pharma_di.preprocess.pipeline import preprocess_document
from pharma_di.schemas.canonical import DocumentRecord, DocumentType
from pharma_di.schemas.mapping import ColumnMapping, TableContext

REPO_ROOT = Path(__file__).resolve().parents[2]
INPUT_DIR = REPO_ROOT / "data" / "input"
DOCS_REACHING_OCR = ["doc1.jpg", "doc2.jpg", "doc3.jpg", "doc5.jpg", "doc6.jpg"]


@lru_cache(maxsize=None)
def _preprocessed_hash(doc_name: str) -> str:
    settings = load_settings()
    result = preprocess_document(str(INPUT_DIR / doc_name), settings, debug_dir=None)
    return hash_image_file(result.working_image_path)


def _cache_prewarmed() -> bool:
    settings = load_settings()
    cache = OcrCache(settings.ocr.cache_dir)
    return all(cache.get(_preprocessed_hash(name)) is not None for name in DOCS_REACHING_OCR)


pytestmark = pytest.mark.skipif(
    not _cache_prewarmed(),
    reason="OCR cache not pre-warmed for all 5 documents that reach OCR — see test_ocr_real_images.py.",
)


@lru_cache(maxsize=None)
def _assembled_for(doc_name: str):
    settings = load_settings()
    cache = OcrCache(settings.ocr.cache_dir)
    page = cache.get(_preprocessed_hash(doc_name))
    assert page is not None, f"{doc_name}: expected a pre-warmed cache entry"

    grid = assemble_stock_table(page.tokens)
    regions = segment_regions(page.tokens)

    field_entries = load_field_entries(load_column_mappings())
    resolvers = [DictionaryResolver(field_entries, load_templates()), ReviewQueueResolver()]
    ctx = TableContext()
    columns = grid.columns if grid else []
    decisions = [resolve_header(c.header, ctx, resolvers) for c in columns]
    column_mapping = ColumnMapping(decisions=decisions)

    distributors_cfg = load_distributors()
    header_text = header_region_text(page.tokens, regions)
    distributor_id, distributor_name, _confidence = detect_distributor(header_text, distributors_cfg)
    section_label_texts = list(grid.section_label_rows.values()) if grid else []
    company_name = detect_company(header_text, distributors_cfg, section_label_texts)
    statement_from, statement_to = detect_period(header_text)
    product_aliases = load_column_mappings()["product_name_raw"]["aliases"]
    document_type = detect_document_type(columns, product_aliases)

    document_record = DocumentRecord(
        document_id=f"test-{doc_name}",
        source_file=doc_name,
        page_number=1,
        page_count=1,
        distributor_id=distributor_id,
        distributor_name=distributor_name,
        company_name=company_name,
        statement_from=statement_from,
        statement_to=statement_to,
        document_type=document_type,
    )

    return assemble_document(grid, column_mapping, document_record)


def test_doc6_row1_matches_hand_transcribed_ground_truth_exactly():
    # The same product/row the P3 regression test locks in
    # (tests/integration/test_layout_real_images.py) — verifying the full
    # assembly pipeline reproduces it end to end, not just table assembly.
    products, transactions, rows, errors = _assembled_for("doc6.jpg")
    assert errors == []
    idx = next(i for i, p in enumerate(products) if p.product_name_raw == "COSKLOT REG TAB.")
    assert products[idx].pack == "10'S"
    assert products[idx].rate == 408.86
    assert transactions[idx].opening_qty == 16.0
    assert transactions[idx].opening_value == 6541.76
    assert rows[idx].closing_value == 6541.76


def test_doc6_section_label_row_does_not_become_a_product():
    products, _transactions, _rows, _errors = _assembled_for("doc6.jpg")
    names = [p.product_name_raw for p in products]
    assert not any("ZORVIA" in n.upper() for n in names)
    assert len(products) == 14  # 15 rows total, 1 section label excluded


def test_doc6_document_record_fields_propagate_to_every_canonical_row():
    _products, _transactions, rows, _errors = _assembled_for("doc6.jpg")
    assert all(r.distributor_id == "medico-drug-agency" for r in rows)
    assert all(r.company_name == "Zorvia Healthcare Limited" for r in rows)
    assert all(r.document_type == DocumentType.product_level for r in rows)


def test_doc1_combine_sum_reflects_only_the_columns_p5_actually_resolved():
    # P5's own finding (IMPLEMENTATION_PLAN.md build notes): doc1.jpg's
    # "Market"/"Return"/"Outsard" fragments stay unresolved (ambiguous
    # single words after the P3 header-fragmentation limitation), so only
    # "Short Quantity" ever contributes to sales_return_quantity here —
    # this propagates that finding through to P6's breakdown, not a new bug.
    _products, _transactions, rows, _errors = _assembled_for("doc1.jpg")
    rows_with_breakdown = [r for r in rows if "sales_return_quantity" in r.source_field_breakdown]
    assert rows_with_breakdown, "expected at least one row with a sales_return_quantity breakdown"
    for r in rows_with_breakdown:
        assert set(r.source_field_breakdown["sales_return_quantity"].keys()) <= {"Short Quantity"}


def test_doc3_summary_emits_exactly_one_row_with_no_product_levels():
    products, transactions, rows, errors = _assembled_for("doc3.jpg")
    assert errors == []
    assert products == [] and transactions == []
    assert len(rows) == 1
    assert rows[0].document_type == DocumentType.summary
    assert rows[0].product_id is None
    assert rows[0].product_name_raw is None


def test_doc3_summary_values_reflect_the_known_p3_limitation_honestly():
    # Documents a real, already-traced-to-root-cause oddity rather than
    # silently accepting or hiding it: doc3.jpg's real "OPENING" header
    # fuzzy-matches opening_quantity (P5's own low-confidence tier), even
    # though the value is clearly a currency amount (this document has NO
    # quantity columns at all — CLAUDE.md: "No quantities at all on this
    # page"). If P3's header-fragmentation limitation is ever fixed, this
    # specific assertion should start failing — that's the intended signal
    # to revisit it, not evidence P6 is doing anything wrong today.
    _products, _transactions, rows, _errors = _assembled_for("doc3.jpg")
    assert rows[0].opening_quantity == 109599.61


def test_every_canonical_row_across_every_document_is_schema_internally_consistent():
    for doc_name in DOCS_REACHING_OCR:
        _products, _transactions, rows, _errors = _assembled_for(doc_name)
        for r in rows:
            if r.document_type == DocumentType.summary:
                assert r.product_id is None and r.hsn_code is None
            # Every null Level-3 field must carry a reason (CLAUDE.md
            # checklist: "Every field ... populated or explicitly null
            # with a reason").
            for field in (
                "opening_quantity", "opening_value", "received_quantity", "received_value",
                "sales_quantity", "sales_value", "closing_quantity", "closing_value",
            ):
                if getattr(r, field) is None:
                    assert field in r.null_field_reasons, f"{doc_name}: {field} is null with no reason recorded"
