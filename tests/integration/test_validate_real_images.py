"""P7 integration test: R1-R7 validation against real, fully assembled
documents (IMPLEMENTATION_PLAN.md section 4.7).

Gated on the OCR cache being warm (same reasoning as test_ocr_real_images.py)
— validation runs on assemble/canonical.py's real output, which depends on
every earlier real stage.

Every assertion below reflects ACTUAL validation output (inspected directly
before writing this file), including real findings, not just clean passes:

- doc6.jpg: R4 (rate coherence) passes on all 14 real rows checking ONLY
  the opening pair — restricted to that pair specifically because checking
  all four qty/value pairs against real data showed the "sales" (ISSUE)
  pair reconciling on only 5 of 14 rows despite the SAME row's opening
  pair reconciling exactly every time; see validate/engine.py's own
  docstring for the connection to CLAUDE.md's open decision D1.
- doc6.jpg: R2 (totals cross-foot) passes on 3 of its 4 checkable fields
  exactly (or within float-summation epsilon) and correctly FAILS on
  received_quantity (sum of real rows: 380; printed total: 370) — a real,
  unresolved discrepancy this rule is supposed to surface, not a bug to
  chase away.
- doc5.jpg: R5 (sign/plausibility) correctly fails on a real negative
  RECEIPT QTY/VALUE — CLAUDE.md's own documented open decision D4
  ("almost certainly a purchase return posted as a negative receipt...
  the plan does not guess"), which must keep failing until D4 is resolved.
- doc2.jpg: R1 doesn't apply (no distributor identified — the
  already-documented E2 fold-crease finding, so no template_family to look
  up) and R3 doesn't fire on any row (free_sales_quantity/
  free_received_quantity are never populated on the same row as
  sales_quantity/received_quantity — a further downstream consequence of
  doc2.jpg's already-documented code/name-split limitation, not a new P7 defect).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pytest

from pharma_di.assemble.canonical import assemble_document
from pharma_di.config import (
    load_column_mappings,
    load_distributors,
    load_settings,
    load_templates,
    load_validation_rules,
)
from pharma_di.detect.document import detect_company, detect_distributor, detect_document_type, detect_period, header_region_text
from pharma_di.layout.regions import segment_regions
from pharma_di.layout.tables import assemble_stock_table
from pharma_di.mapping.dictionary import load_field_entries
from pharma_di.mapping.resolver import DictionaryResolver, ReviewQueueResolver, resolve_header
from pharma_di.ocr.cache import OcrCache, hash_image_file
from pharma_di.preprocess.pipeline import preprocess_document
from pharma_di.schemas.canonical import DocumentRecord
from pharma_di.schemas.mapping import ColumnMapping, TableContext
from pharma_di.schemas.validation import RuleId
from pharma_di.validate.engine import validate_document

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
def _validated_for(doc_name: str):
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

    _products, _transactions, canonical_rows, _errors = assemble_document(grid, column_mapping, document_record)

    settings = load_settings()
    validation_rules_cfg = load_validation_rules()
    rate_tolerance_pct = validation_rules_cfg.get("rate_coherence", {}).get("tolerance_pct", settings.validation.rate_tolerance_pct)

    results, updated_rows = validate_document(
        document_id=f"test-{doc_name}",
        canonical_rows=canonical_rows,
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
    return results, updated_rows


def _rule_results(results, row_index: int, rule_id: RuleId):
    return [r for r in results[row_index].rule_results if r.rule_id == rule_id]


def test_doc6_r4_rate_coherence_passes_on_every_row_checking_only_the_opening_pair():
    results, _rows = _validated_for("doc6.jpg")
    assert len(results) == 14
    for i in range(14):
        r4_results = _rule_results(results, i, RuleId.r4_rate_coherence)
        assert len(r4_results) == 1, f"row {i}: expected exactly one R4 check (opening pair only)"
        assert "opening" in r4_results[0].detail
        assert r4_results[0].passed is True


def test_doc6_r2_totals_crossfoot_passes_on_three_of_four_fields_and_catches_a_real_discrepancy():
    results, _rows = _validated_for("doc6.jpg")
    r2_results = _rule_results(results, 0, RuleId.r2_totals_crossfoot)
    by_field = {r.detail.split(":")[0]: r for r in r2_results}
    assert len(by_field) == 4
    assert by_field["opening_quantity"].passed is True
    assert by_field["opening_value"].passed is True
    assert by_field["received_value"].passed is True
    assert by_field["received_quantity"].passed is False
    assert by_field["received_quantity"].actual == 380.0
    assert by_field["received_quantity"].expected == 370.0


def test_doc6_r1_reconciliation_does_not_apply_because_closing_quantity_is_unresolved():
    # CEY (doc6.jpg's own garbled "CLOSING QTY") is genuinely unresolved by
    # P5 (too corrupted to fuzzy-match) — R1's MARG formula needs
    # closing_quantity, so it correctly has nothing to check rather than
    # treating the missing field as zero.
    results, _rows = _validated_for("doc6.jpg")
    assert _rule_results(results, 0, RuleId.r1_reconciliation) == []


def test_doc5_r5_sign_plausibility_catches_the_real_documented_negative_receipt():
    # CLAUDE.md's own finding #8 / open decision D4.
    results, rows = _validated_for("doc5.jpg")
    failing = [
        (i, r)
        for i, row in enumerate(rows)
        for r in _rule_results(results, i, RuleId.r5_sign_plausibility)
        if not r.passed
    ]
    assert failing, "expected at least one real negative-value row on doc5.jpg"
    assert any("received_quantity" in detail for _i, r in failing for detail in [r.detail])


def test_doc2_r1_does_not_apply_without_an_identified_distributor():
    # The E2 finding: doc2.jpg's distributor/company are genuinely
    # undetected, so there's no template_family to look up a formula for.
    results, rows = _validated_for("doc2.jpg")
    assert rows  # sanity: real rows were assembled despite the E2 gap
    for i in range(len(rows)):
        assert _rule_results(results, i, RuleId.r1_reconciliation) == []


def test_every_review_reason_on_a_failing_row_names_a_real_failed_rule():
    for doc_name in DOCS_REACHING_OCR:
        results, rows = _validated_for(doc_name)
        for row, result in zip(rows, results):
            failed_rule_ids = {r.rule_id for r in result.rule_results if not r.passed}
            if failed_rule_ids:
                assert row.review_reasons, f"{doc_name}: row has failed rules but no review_reasons recorded"
            else:
                assert row.review_status.value == "auto_accepted", f"{doc_name}: row passed everything but wasn't auto_accepted"
