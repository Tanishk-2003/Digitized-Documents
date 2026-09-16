"""P5 integration test: column mapping against real, assembled TableGrids
(IMPLEMENTATION_PLAN.md section 4.6).

Gated on the OCR cache being warm (same reasoning as test_ocr_real_images.py)
— mapping runs on layout/tables.py's real output, which depends on OCR.

Every assertion below reflects the ACTUAL resolver output against real
column data (printed and inspected directly before writing this file), not
assumed values. In particular, this file also pins down a real fuzzy-scoring
bug found and fixed while building this stage: rapidfuzz's token_set_ratio
alone scores a short header that's a pure word-subset of a longer alias as a
near-perfect match regardless of what's missing (doc1.jpg's own "Stock"
column scored 100.0 against the "opening stock" alias before the fix, which
is a real, wrong, HIGH-CONFIDENCE mis-mapping — not a safe "flagged for
review" outcome). Fixed in mapping/fuzzy.py by taking the minimum of
token_set_ratio and token_sort_ratio; `test_doc1_ambiguous_single_word_stock_header_is_not_falsely_mapped`
below is the regression test for that fix specifically.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pytest
import yaml

from pharma_di.config import load_abbreviations, load_column_mappings, load_settings, load_templates
from pharma_di.detect.fingerprint import compute_fingerprint, leaf_fingerprint_key
from pharma_di.layout.tables import assemble_stock_table
from pharma_di.mapping.dictionary import load_field_entries
from pharma_di.mapping.resolver import DictionaryResolver, ReviewQueueResolver, resolve_header
from pharma_di.mapping.template_cache import save_fingerprint
from pharma_di.ocr.cache import OcrCache, hash_image_file
from pharma_di.preprocess.pipeline import preprocess_document
from pharma_di.schemas.mapping import ColumnMapping, MappingStatus, TableContext

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
def _column_mapping_for(doc_name: str) -> ColumnMapping:
    settings = load_settings()
    cache = OcrCache(settings.ocr.cache_dir)
    page = cache.get(_preprocessed_hash(doc_name))
    assert page is not None, f"{doc_name}: expected a pre-warmed cache entry"

    grid = assemble_stock_table(page.tokens)
    assert grid is not None, f"{doc_name}: expected a real assembled TableGrid"

    field_entries = load_field_entries(load_column_mappings())
    resolvers = [DictionaryResolver(field_entries, load_templates()), ReviewQueueResolver()]
    ctx = TableContext()
    decisions = [resolve_header(col.header, ctx, resolvers) for col in grid.columns]
    return ColumnMapping(decisions=decisions)


def _field_for(mapping: ColumnMapping, path: list[str]) -> str | None:
    for d in mapping.decisions:
        if d.source_header.path == path:
            return d.canonical_field
    raise AssertionError(f"no column with path={path!r} in this table's decisions")


def _status_for(mapping: ColumnMapping, path: list[str]) -> MappingStatus:
    for d in mapping.decisions:
        if d.source_header.path == path:
            return d.status
    raise AssertionError(f"no column with path={path!r} in this table's decisions")


def test_doc6_marg_columns_resolve_deterministically():
    mapping = _column_mapping_for("doc6.jpg")
    assert _status_for(mapping, ["ITEM DESCRIPTION"]) == MappingStatus.exact
    assert _field_for(mapping, ["ITEM DESCRIPTION"]) == "product_name_raw"
    assert _field_for(mapping, ["PACK"]) == "pack"
    assert _field_for(mapping, ["RATE"]) == "rate"
    assert _status_for(mapping, ["OPENING", "QTY."]) == MappingStatus.exact
    assert _field_for(mapping, ["OPENING", "QTY."]) == "opening_quantity"
    assert _field_for(mapping, ["OPENING", "VALUE"]) == "opening_value"
    assert _field_for(mapping, ["RECEIPT", "QTY"]) == "received_quantity"
    assert _field_for(mapping, ["RECEIPT", "VALUE"]) == "received_value"


def test_doc6_dom2_qty_resolves_low_confidence_to_dump_quantity_after_d2():
    # P14 resolved D2 by giving DUMP QTY its own real dump_quantity field
    # (config/column_mappings.yaml) — checked directly against real doc6.jpg
    # data (not assumed unchanged): "DOM2 QTY" now fuzzy-matches
    # dump_quantity at exactly 75.0, the LOW_CONFIDENCE_THRESHOLD floor —
    # genuinely borderline (fewer shared characters with "dump" than
    # doc5.jpg's "DUP" has), so it resolves but forces its row to review
    # rather than silently trusting a borderline OCR-noise match. This test
    # used to assert DOM2 QTY stayed unresolved — that was accurate before
    # D2 was resolved, not a fact this change should have preserved.
    mapping = _column_mapping_for("doc6.jpg")
    assert _status_for(mapping, ["DOM2", "QTY"]) == MappingStatus.fuzzy_low_confidence
    assert _field_for(mapping, ["DOM2", "QTY"]) == "dump_quantity"


def test_doc6_cey_stays_unresolved_severely_garbled_closing_qty():
    # "CEY" is OCR's own severe garbling of "CLOSING QTY" — too corrupted
    # to safely fuzzy-match (the same "never guess" discipline layout/
    # headers.py::is_leaf_label already applies), unaffected by D2's
    # resolution (a different column, still absent from the dictionary
    # under any spelling close enough to "CEY" to matter).
    mapping = _column_mapping_for("doc6.jpg")
    assert _status_for(mapping, ["CEY"]) == MappingStatus.unresolved


def test_doc6_issue_columns_resolve_via_the_documented_d1_assumption():
    # "ISSOZ" is OCR's garbling of "ISSUE" — config/column_mappings.yaml
    # maps ISSUE -> sales_* under the plan's open decision D1 (marked
    # ASSUMPTION there), confirmed to actually resolve here (fuzzy,
    # low-confidence given the OCR noise on top of an already-provisional
    # mapping).
    mapping = _column_mapping_for("doc6.jpg")
    assert _field_for(mapping, ["ISSOZ", "QTY"]) == "sales_quantity"
    assert _field_for(mapping, ["ISSOZ", "VALUE"]) == "sales_value"


def test_doc2_nabin_columns_resolve_completely():
    # doc2.jpg's header-window fix (P3) produced a fully clean column set;
    # every one of its real headers is in config/column_mappings.yaml
    # verbatim or near enough — should resolve 100%, not just mostly.
    mapping = _column_mapping_for("doc2.jpg")
    assert mapping.resolved_fraction == 1.0
    assert _field_for(mapping, ["PRODUCT NAME"]) == "product_name_raw"
    assert _field_for(mapping, ["Sale Rtn"]) == "sales_return_quantity"
    for d in mapping.decisions:
        if d.canonical_field == "sales_return_quantity":
            assert d.combine == "sum"
    # "Total Revd."/"Total Sold" are printed derived columns (R3), not
    # written to a canonical field directly — must still resolve, not be
    # sent to unmapped_columns.
    assert _field_for(mapping, ["Total Revd."]) == "derived_check_only"
    assert _field_for(mapping, ["Total Sold"]) == "derived_check_only"


def test_doc1_ambiguous_single_word_stock_header_is_not_falsely_mapped():
    # Regression test for the token_set_ratio subset-inflation fix (see
    # module docstring): before the fix, "Stock" alone (a real column on
    # this document, distinct from "Opening") scored a deceptive 100.0
    # (exact-equivalent confidence) against the "opening stock" alias just
    # because "stock" is one of its two words — the token_set_ratio blind
    # spot. After the fix it scores 76.9: still resolved (the tier-4 design
    # is accept-with-review from 75, not outright rejection), but now
    # correctly landing in fuzzy_low_confidence, not a false, unreviewed
    # certainty. "Stock Value" is a separate column that fell all the way
    # to unresolved — a stronger signal than low-confidence, also correct.
    mapping = _column_mapping_for("doc1.jpg")
    assert _status_for(mapping, ["Stock"]) == MappingStatus.fuzzy_low_confidence
    assert _status_for(mapping, ["Stock", "Value"]) == MappingStatus.unresolved


def test_doc1_clean_columns_still_resolve():
    mapping = _column_mapping_for("doc1.jpg")
    assert _field_for(mapping, ["Product"]) == "product_name_raw"
    assert _field_for(mapping, ["Pack"]) == "pack"
    assert _field_for(mapping, ["Sales", "Quantity"]) == "sales_quantity"


def test_doc5_dup_qty_resolves_confidently_to_dump_quantity_after_d2():
    # P14 resolved D2 by giving DUMP QTY its own real dump_quantity field.
    # Checked directly against real doc5.jpg data: "DUP QTY." — doc5's own
    # OCR rendering of "DUMP QTY" (closer to the real word than doc6.jpg's
    # "DOM2" — one character insertion away: d-u-p -> d-u-m-p) — fuzzy-
    # matches dump_quantity at 94.1, comfortably above ACCEPT_THRESHOLD, so
    # it resolves with full confidence like any other clean column. This
    # test used to assert it stayed unresolved — accurate before D2 was
    # resolved, not a fact this change should have preserved.
    mapping = _column_mapping_for("doc5.jpg")
    assert _status_for(mapping, ["DUP", "QTY."]) == MappingStatus.fuzzy
    assert _field_for(mapping, ["DUP", "QTY."]) == "dump_quantity"


def test_doc5_marg_columns_mostly_resolve_despite_heavier_ocr_noise():
    # doc5.jpg's OCR noise is heavier than doc6.jpg's on the same MARG
    # template ("VALDE"/"VALOE" for "VALUE" throughout) — still expected to
    # resolve the large majority of real columns. Was 9/10 before P14
    # resolved D2; DUP QTY (the one holdout) now resolves too (see
    # test_doc5_dup_qty_resolves_confidently_to_dump_quantity_after_d2),
    # so this is genuinely 10/10 as of P14 — the >=0.85 floor is kept
    # rather than tightened to ==1.0, since this test's own point is "the
    # large majority," not pinning today's exact count against a future
    # dictionary change.
    mapping = _column_mapping_for("doc5.jpg")
    assert mapping.resolved_fraction >= 0.85
    assert _field_for(mapping, ["OPENING", "QTY."]) == "opening_quantity"
    assert _field_for(mapping, ["OPENING", "VALDE"]) == "opening_value"


def test_every_resolved_decision_is_internally_consistent():
    # Cross-document schema sanity check: MappingDecision's own validator
    # already enforces "unresolved never carries a field, resolved always
    # does" at construction time — this asserts that invariant held for
    # every real column across every document, not just that construction
    # didn't raise.
    for doc_name in DOCS_REACHING_OCR:
        mapping = _column_mapping_for(doc_name)
        for d in mapping.decisions:
            if d.status == MappingStatus.unresolved:
                assert d.canonical_field is None, f"{doc_name}: {d.source_header.path} unresolved but has a field"
            else:
                assert d.canonical_field is not None, f"{doc_name}: {d.source_header.path} resolved but has no field"


def test_doc6_confidently_resolved_columns_hit_the_cache_on_a_second_pass(tmp_path):
    """P13, real end-to-end proof (not synthetic): resolve doc6.jpg's real
    columns once (tiers 2-4, as every other test in this file does), cache
    the result exactly the way graph/nodes.py::_cache_resolved_template
    does, then resolve the SAME real columns again with that cache in
    place — every column that was confidently resolved the first time
    (exact/normalized/fuzzy, i.e. NOT fuzzy_low_confidence) must come back
    MappingStatus.template_cache the second time, and land on the exact
    same canonical_field either way."""
    settings = load_settings()
    cache = OcrCache(settings.ocr.cache_dir)
    page = cache.get(_preprocessed_hash("doc6.jpg"))
    assert page is not None
    grid = assemble_stock_table(page.tokens)
    assert grid is not None

    column_mappings_cfg = load_column_mappings()
    field_entries = load_field_entries(column_mappings_cfg)
    abbreviations = load_abbreviations()
    accept_threshold = settings.semantic_mapping.fuzzy_accept_threshold

    fingerprint = compute_fingerprint(grid.columns, field_entries, abbreviations)
    assert fingerprint is not None

    first_mapping = _column_mapping_for("doc6.jpg")  # no fingerprint in context — pure tier 2-4, as normal
    cacheable_statuses = {MappingStatus.exact, MappingStatus.normalized, MappingStatus.fuzzy}
    leaf_mapping = {
        leaf_fingerprint_key(col.header, field_entries, abbreviations, accept_threshold): d.canonical_field
        for col, d in zip(grid.columns, first_mapping.decisions)
        if d.status in cacheable_statuses
    }
    assert leaf_mapping, "expected at least one confidently-resolved real column on doc6.jpg"

    templates_file = tmp_path / "templates.yaml"
    save_fingerprint(fingerprint, leaf_mapping, templates_file)

    templates_cfg = yaml.safe_load(templates_file.read_text(encoding="utf-8"))
    resolvers = [DictionaryResolver(field_entries, templates_cfg), ReviewQueueResolver()]
    ctx = TableContext(fingerprint=fingerprint)
    second_decisions = [resolve_header(col.header, ctx, resolvers) for col in grid.columns]

    checked = 0
    for col, first_decision, second_decision in zip(grid.columns, first_mapping.decisions, second_decisions):
        if first_decision.status in cacheable_statuses:
            assert second_decision.status == MappingStatus.template_cache, (
                f"{col.header.path!r}: expected a cache hit, got {second_decision.status}"
            )
            assert second_decision.canonical_field == first_decision.canonical_field
            checked += 1
    assert checked == len(leaf_mapping)
