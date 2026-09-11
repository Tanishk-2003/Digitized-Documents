"""P8 integration test: persistence + Excel export against a real, fully
assembled and validated document (doc6.jpg) — the same document
test_validate_real_images.py already verified rule-by-rule against real,
hand-checked figures (CLAUDE.md finding #4: opening 16 * 408.86 = 6541.76).

This file doesn't re-verify validation logic itself (that's
test_validate_real_images.py's job) — it verifies that what P6/P7 already
produce for doc6.jpg survives a real round trip through SQLAlchemy models
(P8) and back out as an Excel export, unchanged in the fields that matter:
product identity, quantities/values, and the review/confidence metadata a
human reviewer would rely on.

Gated on the same two preconditions as test_resolve_products_real_images.py
(warm OCR cache + a bootstrapped product master catalogue), since this test
exercises resolve_products too, to also confirm a resolved product_id
survives persistence.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from pharma_di.assemble.canonical import assemble_document
from pharma_di.config import load_column_mappings, load_distributors, load_settings, load_templates, load_validation_rules
from pharma_di.detect.document import detect_company, detect_distributor, detect_document_type, detect_period, header_region_text
from pharma_di.export.excel import CANONICAL_COLUMNS, export_to_excel
from pharma_di.layout.regions import segment_regions
from pharma_di.layout.tables import assemble_stock_table
from pharma_di.mapping.dictionary import load_field_entries
from pharma_di.mapping.resolver import DictionaryResolver, ReviewQueueResolver, resolve_header
from pharma_di.ocr.cache import OcrCache, hash_image_file
from pharma_di.persist.db import get_engine
from pharma_di.persist.models import Base
from pharma_di.persist.repository import load_canonical_rows, save_document
from pharma_di.preprocess.pipeline import preprocess_document
from pharma_di.resolve.masters import load_products_master
from pharma_di.resolve.products import resolve_product
from pharma_di.schemas.canonical import DocumentRecord
from pharma_di.schemas.mapping import ColumnMapping, TableContext
from pharma_di.validate.engine import validate_document

REPO_ROOT = Path(__file__).resolve().parents[2]
INPUT_DIR = REPO_ROOT / "data" / "input"
MASTERS_PATH = REPO_ROOT / "data" / "masters" / "products.csv"
DOC_NAME = "doc6.jpg"


@lru_cache(maxsize=None)
def _preprocessed_hash(doc_name: str) -> str:
    settings = load_settings()
    result = preprocess_document(str(INPUT_DIR / doc_name), settings, debug_dir=None)
    return hash_image_file(result.working_image_path)


def _cache_prewarmed() -> bool:
    settings = load_settings()
    cache = OcrCache(settings.ocr.cache_dir)
    return cache.get(_preprocessed_hash(DOC_NAME)) is not None


pytestmark = pytest.mark.skipif(
    not (_cache_prewarmed() and MASTERS_PATH.exists()),
    reason="Needs both a warm OCR cache (doc6.jpg) and data/masters/products.csv "
    "(run scripts/bootstrap_products_master.py once first).",
)


@lru_cache(maxsize=None)
def _assembled_and_validated():
    """Runs the real P3-P7 pipeline stages for doc6.jpg — the same sequence
    test_validate_real_images.py uses — and additionally resolves products
    (P6), so persistence has a real product_id to round-trip, not just an
    unresolved one."""
    settings = load_settings()
    cache = OcrCache(settings.ocr.cache_dir)
    page = cache.get(_preprocessed_hash(DOC_NAME))
    assert page is not None, f"{DOC_NAME}: expected a pre-warmed cache entry"

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
        document_id="doc6-persist-test",
        source_file=DOC_NAME,
        page_number=1,
        page_count=1,
        distributor_id=distributor_id,
        distributor_name=distributor_name,
        company_name=company_name,
        statement_from=statement_from,
        statement_to=statement_to,
        document_type=document_type,
    )

    products, transactions, canonical_rows, _errors = assemble_document(grid, column_mapping, document_record)

    masters = load_products_master(MASTERS_PATH)
    updated_products = []
    updated_rows = list(canonical_rows)
    for i, product in enumerate(products):
        product_id, _reason = resolve_product(product, masters)
        updated_products.append(product if product_id is None else product.model_copy(update={"product_id": product_id}))
        if product_id is not None:
            updated_rows[i] = updated_rows[i].model_copy(update={"product_id": product_id})

    validation_rules_cfg = load_validation_rules()
    rate_tolerance_pct = validation_rules_cfg.get("rate_coherence", {}).get("tolerance_pct", settings.validation.rate_tolerance_pct)
    results, validated_rows = validate_document(
        document_id="doc6-persist-test",
        canonical_rows=updated_rows,
        grid=grid,
        column_mapping=column_mapping,
        page_tokens=page.tokens,
        regions=regions,
        page_quality_ok=True,
        distributor_id=distributor_id,
        distributors_cfg=distributors_cfg,
        validation_rules_cfg=validation_rules_cfg,
        rate_tolerance_pct=rate_tolerance_pct,
        totals_tolerance_abs=settings.validation.totals_tolerance_abs,
        min_field_confidence=settings.validation.min_field_confidence,
    )

    return document_record, updated_products, transactions, validated_rows, results


def _persisted_session(tmp_path) -> Session:
    engine = get_engine(f"sqlite:///{tmp_path / 'doc6.db'}")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_doc6_all_fourteen_rows_persist(tmp_path):
    document_record, products, transactions, rows, results = _assembled_and_validated()
    assert len(rows) == 14  # same real row count test_validate_real_images.py verifies

    with _persisted_session(tmp_path) as session:
        save_document(session, document_record, products, transactions, rows, results)
        loaded = load_canonical_rows(session, document_id="doc6-persist-test")

    assert len(loaded) == 14


def test_doc6_row_zero_opening_figures_survive_the_round_trip(tmp_path):
    # CLAUDE.md finding #4, already hand-verified: 16 * 408.86 = 6541.76.
    document_record, products, transactions, rows, results = _assembled_and_validated()

    with _persisted_session(tmp_path) as session:
        save_document(session, document_record, products, transactions, rows, results)
        loaded = load_canonical_rows(session, document_id="doc6-persist-test")

    row0 = loaded[0]
    assert row0["opening_quantity"] == rows[0].opening_quantity
    assert row0["opening_value"] == rows[0].opening_value
    assert row0["rate"] == rows[0].rate
    assert row0["opening_quantity"] == 16.0
    assert row0["opening_value"] == 6541.76


def test_doc6_review_status_and_reasons_survive_the_round_trip(tmp_path):
    # P7's own real, verified finding: doc6 rows fail at least one rule
    # (R2's received_quantity cross-foot mismatch applies to every row) —
    # persistence must preserve that needs_review verdict, not silently
    # upgrade it to auto_accepted.
    document_record, products, transactions, rows, results = _assembled_and_validated()
    assert any(r.review_status.value == "needs_review" for r in rows), "expected doc6 to have real needs_review rows"

    with _persisted_session(tmp_path) as session:
        save_document(session, document_record, products, transactions, rows, results)
        loaded = load_canonical_rows(session, document_id="doc6-persist-test")

    for original, persisted in zip(rows, loaded):
        assert persisted["review_status"] == original.review_status.value
        assert persisted["review_reasons"] == original.review_reasons


def test_doc6_resolved_product_ids_survive_the_round_trip(tmp_path):
    document_record, products, transactions, rows, results = _assembled_and_validated()
    resolved_count = sum(1 for p in products if p.product_id is not None)
    assert resolved_count > 0, "expected at least one real hsn_code match against the bootstrapped catalogue"

    with _persisted_session(tmp_path) as session:
        save_document(session, document_record, products, transactions, rows, results)
        loaded = load_canonical_rows(session, document_id="doc6-persist-test")

    for original, persisted in zip(rows, loaded):
        assert persisted["product_id"] == original.product_id


def test_doc6_exports_to_excel_with_canonical_columns_and_matching_row_count(tmp_path):
    document_record, products, transactions, rows, results = _assembled_and_validated()

    with _persisted_session(tmp_path) as session:
        save_document(session, document_record, products, transactions, rows, results)
        output_path = export_to_excel(session, tmp_path / "doc6.xlsx", document_id="doc6-persist-test")

    df = pd.read_excel(output_path)
    assert list(df.columns) == CANONICAL_COLUMNS
    assert len(df) == 14
    assert df.iloc[0]["opening_quantity"] == 16.0
    assert (df["source_document"] == "doc6.jpg").all()
