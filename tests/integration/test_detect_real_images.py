"""P4 integration test: distributor/company/period detection and template
fingerprinting against real cached OCR + layout output.

Gated on the OCR cache being warm (same reasoning as test_ocr_real_images.py)
— detection runs on OcrPage tokens plus a re-run of P3's layout stage, which
in this environment come from a slow, unaccelerated PaddleOCR pass. Once the
cache is warm this runs in a couple of seconds (cache hits) plus P3's own
(fast) layout assembly.

Assertions below reflect REAL, directly-observed behavior on these six
documents (their page_header/statement_meta text, GSTIN, section-label rows,
and column structure were all inspected directly before writing this file),
not aspirational values. In particular:

- doc2.jpg identifies neither distributor nor company — this is the
  documented E2 finding (IMPLEMENTATION_PLAN.md section 8b): "NABIN DRUG
  CENTRE" sits at a paper fold crease PP-OCR's text detection misses
  entirely, confirmed by direct inspection of its OCR tokens.
- doc6.jpg's company name is recovered only via its section-label row (not
  page_header/statement_meta text, which contains neither a company name
  nor any date pattern at all), and its period is genuinely undetectable —
  both confirmed by direct inspection, not assumed.
- doc5.jpg and doc6.jpg — despite being the same underlying MARG ERP
  template (IMPLEMENTATION_PLAN.md section 1.3) — do NOT share a template
  fingerprint on real data: their OCR text garbles the same header words
  differently ("CLOSTNG" vs "CLOSINO", "ISSOZ" vs "ISSUE"), which an
  exact-hash fingerprint is sensitive to by design (see
  detect/fingerprint.py). This is a real, known limitation of the current
  exact-hash approach, not a bug in this test — see IMPLEMENTATION_PLAN.md's
  P4 build notes for the full account.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pytest

from pharma_di.config import load_column_mappings, load_distributors, load_settings
from pharma_di.detect.document import (
    detect_company,
    detect_distributor,
    detect_document_type,
    detect_period,
    header_region_text,
)
from pharma_di.detect.fingerprint import compute_fingerprint
from pharma_di.layout.regions import segment_regions
from pharma_di.layout.tables import assemble_stock_table
from pharma_di.ocr.cache import OcrCache, hash_image_file
from pharma_di.preprocess.pipeline import preprocess_document
from pharma_di.schemas.canonical import DocumentType

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
def _detection_for(doc_name: str):
    settings = load_settings()
    cache = OcrCache(settings.ocr.cache_dir)
    page = cache.get(_preprocessed_hash(doc_name))
    assert page is not None, f"{doc_name}: expected a pre-warmed cache entry"

    regions = segment_regions(page.tokens)
    grid = assemble_stock_table(page.tokens)
    columns = grid.columns if grid else []
    section_label_texts = list(grid.section_label_rows.values()) if grid else []

    distributors_cfg = load_distributors()
    header_text = header_region_text(page.tokens, regions)
    distributor_id, distributor_name, confidence = detect_distributor(header_text, distributors_cfg)
    company_name = detect_company(header_text, distributors_cfg, section_label_texts)
    statement_from, statement_to = detect_period(header_text)
    product_aliases = load_column_mappings()["product_name_raw"]["aliases"]
    document_type = detect_document_type(columns, product_aliases)
    fingerprint = compute_fingerprint(columns) if columns else None

    return {
        "distributor_id": distributor_id,
        "distributor_name": distributor_name,
        "confidence": confidence,
        "company_name": company_name,
        "statement_from": statement_from,
        "statement_to": statement_to,
        "document_type": document_type,
        "fingerprint": fingerprint,
    }


def test_doc1_identifies_new_tripura_pharmaco_and_zorvia_and_period():
    d = _detection_for("doc1.jpg")
    assert d["distributor_id"] == "new-tripura-pharmaco"
    assert d["company_name"] == "Zorvia Healthcare Limited"
    assert d["statement_from"].isoformat() == "2026-06-29"
    assert d["statement_to"].isoformat() == "2026-07-29"
    assert d["document_type"] == DocumentType.product_level


def test_doc2_identifies_neither_distributor_nor_company():
    # The E2 fold-crease finding: OCR detection finds no text there at all,
    # so there is nothing for fuzzy/GSTIN matching to work with. Must come
    # back None, not a guessed low-confidence match.
    d = _detection_for("doc2.jpg")
    assert d["distributor_id"] is None
    assert d["company_name"] is None


def test_doc3_identifies_nabin_and_is_classified_summary():
    d = _detection_for("doc3.jpg")
    assert d["distributor_id"] == "nabin-drug-centre"
    assert d["statement_from"].isoformat() == "2026-07-01"
    assert d["statement_to"].isoformat() == "2026-07-31"
    # CLAUDE.md's own summary-only example: company-level totals, no
    # product-name column at all.
    assert d["document_type"] == DocumentType.summary


def test_doc5_identifies_bn_drug_distributor_via_gstin_and_zorvia_and_period():
    d = _detection_for("doc5.jpg")
    assert d["distributor_id"] == "bn-drug-distributor"
    assert d["confidence"] == 1.0  # resolved via exact GSTIN match, not fuzzy text
    assert d["company_name"] == "Zorvia Healthcare Limited"
    assert d["statement_from"].isoformat() == "2026-07-01"
    assert d["statement_to"].isoformat() == "2026-07-30"
    assert d["document_type"] == DocumentType.product_level


def test_doc6_identifies_medico_and_zorvia_via_section_label_row():
    d = _detection_for("doc6.jpg")
    assert d["distributor_id"] == "medico-drug-agency"
    # Recovered only via the section-label row inside the table body — not
    # page_header/statement_meta text, which contains no company name at all.
    assert d["company_name"] == "Zorvia Healthcare Limited"
    assert d["document_type"] == DocumentType.product_level


def test_doc6_period_is_genuinely_undetectable_not_a_bug():
    # Confirmed by direct inspection: zero tokens anywhere in doc6.jpg's OCR
    # output match a date pattern. A real data gap, not a detection failure.
    d = _detection_for("doc6.jpg")
    assert d["statement_from"] is None
    assert d["statement_to"] is None


def test_marg_family_fingerprints_do_not_unify_on_real_ocr_noise():
    # Known limitation (see module docstring): doc5.jpg and doc6.jpg share
    # the same underlying ERP template but OCR garbles the same header
    # words differently, so an exact-hash fingerprint treats them as
    # different templates. Documented here so a future fix (fuzzy
    # normalization before hashing) has a concrete regression test to
    # flip, rather than this gap being silently rediscovered later.
    doc5 = _detection_for("doc5.jpg")
    doc6 = _detection_for("doc6.jpg")
    assert doc5["fingerprint"] is not None
    assert doc6["fingerprint"] is not None
    assert doc5["fingerprint"] != doc6["fingerprint"]


def test_same_document_produces_the_same_fingerprint_every_time():
    a = _detection_for("doc6.jpg")["fingerprint"]
    b = compute_fingerprint(assemble_stock_table(
        OcrCache(load_settings().ocr.cache_dir).get(_preprocessed_hash("doc6.jpg")).tokens
    ).columns)
    assert a == b
