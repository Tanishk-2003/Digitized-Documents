"""P6 integration test: product master resolution against the real
bootstrap catalogue (IMPLEMENTATION_PLAN.md section 4.8).

Gated on BOTH the OCR cache being warm (same reasoning as
test_ocr_real_images.py) AND data/masters/products.csv existing —
scripts/bootstrap_products_master.py must be run once before this file can
do anything meaningful (section 4.8: "Until it exists, product resolution
returns unmatched and rows route to review, which is correct behaviour, not
a failure" — this file's own skip, mirroring that same reasoning, rather
than treating a not-yet-bootstrapped catalogue as a test failure).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pytest

from pharma_di.assemble.canonical import assemble_document
from pharma_di.config import load_column_mappings, load_distributors, load_settings, load_templates
from pharma_di.detect.document import detect_document_type, header_region_text
from pharma_di.layout.regions import segment_regions
from pharma_di.layout.tables import assemble_stock_table
from pharma_di.mapping.dictionary import load_field_entries
from pharma_di.mapping.resolver import DictionaryResolver, ReviewQueueResolver, resolve_header
from pharma_di.ocr.cache import OcrCache, hash_image_file
from pharma_di.preprocess.pipeline import preprocess_document
from pharma_di.resolve.masters import load_products_master
from pharma_di.resolve.products import resolve_product
from pharma_di.schemas.canonical import DocumentRecord
from pharma_di.schemas.mapping import ColumnMapping, TableContext

REPO_ROOT = Path(__file__).resolve().parents[2]
INPUT_DIR = REPO_ROOT / "data" / "input"
MASTERS_PATH = REPO_ROOT / "data" / "masters" / "products.csv"


@lru_cache(maxsize=None)
def _preprocessed_hash(doc_name: str) -> str:
    settings = load_settings()
    result = preprocess_document(str(INPUT_DIR / doc_name), settings, debug_dir=None)
    return hash_image_file(result.working_image_path)


def _cache_prewarmed() -> bool:
    settings = load_settings()
    cache = OcrCache(settings.ocr.cache_dir)
    return cache.get(_preprocessed_hash("doc6.jpg")) is not None


pytestmark = pytest.mark.skipif(
    not (_cache_prewarmed() and MASTERS_PATH.exists()),
    reason="Needs both a warm OCR cache (doc6.jpg) and data/masters/products.csv "
    "(run scripts/bootstrap_products_master.py once first).",
)


def _products_for(doc_name: str) -> list:
    settings = load_settings()
    cache = OcrCache(settings.ocr.cache_dir)
    page = cache.get(_preprocessed_hash(doc_name))
    assert page is not None

    grid = assemble_stock_table(page.tokens)
    regions = segment_regions(page.tokens)
    field_entries = load_field_entries(load_column_mappings())
    resolvers = [DictionaryResolver(field_entries, load_templates()), ReviewQueueResolver()]
    ctx = TableContext()
    columns = grid.columns if grid else []
    decisions = [resolve_header(c.header, ctx, resolvers) for c in columns]
    column_mapping = ColumnMapping(decisions=decisions)

    product_aliases = load_column_mappings()["product_name_raw"]["aliases"]
    document_type = detect_document_type(columns, product_aliases)
    document_record = DocumentRecord(
        document_id=f"test-{doc_name}", source_file=doc_name, page_number=1, page_count=1, document_type=document_type
    )
    products, _transactions, _rows, _errors = assemble_document(grid, column_mapping, document_record)
    return products


def test_doc6_products_resolve_against_the_bootstrap_catalogue_built_from_the_same_document():
    # The catalogue was bootstrapped FROM these same six documents, so every
    # real product extracted from doc6.jpg should find its own entry —
    # verifying the resolution path actually connects end to end, not that
    # it generalizes to genuinely new products (a different, harder claim
    # this test doesn't make).
    masters = load_products_master(MASTERS_PATH)
    products = _products_for("doc6.jpg")
    assert products, "expected real products from doc6.jpg"

    resolved = 0
    for product in products:
        product_id, _reason = resolve_product(product, masters)
        if product_id is not None:
            resolved += 1
    assert resolved == len(products)


def test_a_genuinely_unknown_product_does_not_match_anything():
    masters = load_products_master(MASTERS_PATH)
    from pharma_di.schemas.canonical import ProductRecord

    fictional = ProductRecord(product_name_raw="COMPLETELY FICTIONAL MEDICATION XYZ999", pack="1UNIT")
    product_id, reason = resolve_product(fictional, masters)
    assert product_id is None
    assert "no confident match" in reason
