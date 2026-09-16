"""Pipeline nodes (CLAUDE.md pipeline architecture, IMPLEMENTATION_PLAN.md
section 4.9).

P0 scope: `ingest` does real work (reads the actual image, builds a real
DocumentRecord stub). Every other node is an explicit, clearly-labeled no-op
that only records that it ran — the logic for each lands in the phase named
in its docstring. This file is the thing scripts/run_pipeline.py drives, and
the thing tests/integration/test_pipeline_smoke.py exercises end-to-end.

Each node takes the full PipelineState and returns a dict of the fields it
changes (the LangGraph convention for a Pydantic state schema) — never the
whole state object, so unrelated fields are never accidentally clobbered.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from pharma_di.assemble import canonical as canonical_module
from pharma_di.config import (
    load_abbreviations,
    load_column_mappings,
    load_distributors,
    load_settings,
    load_templates,
    load_validation_rules,
)
from pharma_di.detect import document as detect_document_module
from pharma_di.detect import fingerprint as fingerprint_module
from pharma_di.export.excel import export_to_excel
from pharma_di.graph.state import PipelineState
from pharma_di.layout import regions as layout_regions
from pharma_di.layout import tables as layout_tables
from pharma_di.mapping import dictionary as mapping_dictionary
from pharma_di.mapping import template_cache as template_cache_module
from pharma_di.mapping.resolver import DictionaryResolver, ReviewQueueResolver, resolve_header
from pharma_di.ocr.cache import OcrCache
from pharma_di.ocr.paddle_engine import run_ocr
from pharma_di.persist import db as persist_db
from pharma_di.persist.repository import save_document
from pharma_di.preprocess.pipeline import preprocess_document
from pharma_di.resolve.masters import load_products_master
from pharma_di.resolve.products import resolve_product
from pharma_di.schemas.canonical import DocumentRecord, ReviewStatus
from pharma_di.schemas.layout import LayoutResult
from pharma_di.schemas.mapping import ColumnMapping, MappingStatus, TableContext
from pharma_di.validate.engine import validate_document

# ---------------------------------------------------------------------------
# P0 — real logic
# ---------------------------------------------------------------------------


def ingest(state: PipelineState) -> dict:
    """Read the source image and build the initial Level-1 DocumentRecord.

    This is the one node with real behaviour in P0: it proves the scaffold
    can load an actual file from data/input/ and produce a schema-valid
    record from it, rather than only passing an empty state through no-ops.
    """
    path = Path(state.source_file)
    if not path.exists():
        return {"trace": ["ingest"], "errors": [f"ingest: source file not found: {path}"]}

    try:
        with Image.open(path) as img:
            width, height = img.size
    except Exception as exc:
        return {"trace": ["ingest"], "errors": [f"ingest: invalid or unreadable image: {exc}"]}

    doc_record = DocumentRecord(
        document_id=state.document_id,
        source_file=str(path),
        page_number=state.page_number,
        page_count=state.page_count,
        # distributor_name / company_name / statement_from / statement_to /
        # document_type are intentionally left None here — resolving them is
        # detect_document's job (P4), not ingest's. An unpopulated field here
        # is the documented "correct output, not a failure" case.
    )

    return {
        "trace": ["ingest"],
        "image_width": width,
        "image_height": height,
        "document_record": doc_record,
    }


# ---------------------------------------------------------------------------
# P1 — real logic: boundary detect, perspective correct, dewarp, deskew,
# illumination flatten, denoise, quality gate. See
# IMPLEMENTATION_PLAN.md section 4.1 and src/pharma_di/preprocess/.
# ---------------------------------------------------------------------------


def preprocess(state: PipelineState) -> dict:
    """Run the full P1 preprocessing sequence and stash the result for
    quality_gate to read. If ingest already flagged an error (e.g. missing
    file), there is nothing to preprocess — pass through untouched rather
    than trying to open a file we already know doesn't exist."""
    if state.errors:
        return {"trace": ["preprocess"]}

    settings = load_settings()
    debug_dir = str(settings.resolve_path("data_interim") / state.document_id / "preprocess")

    try:
        result = preprocess_document(state.source_file, settings, debug_dir=debug_dir)
    except Exception as exc:  # noqa: BLE001 — a bad/corrupt image must route to review, never crash the graph
        return {"trace": ["preprocess"], "errors": [f"preprocess: {exc}"]}

    return {
        "trace": ["preprocess"],
        "preprocessed_image_path": result.working_image_path,
        "page_quality": result.quality,
        "page_quality_ok": result.quality.passed,
    }


def quality_gate(state: PipelineState) -> dict:
    """Record the quality verdict already computed by preprocess(). Kept as
    its own node (rather than folded into preprocess) because it is the
    stage name the pipeline diagram and section 4.9's node list name
    explicitly, and because P1's conditional edge (route_after_quality_gate)
    branches on its output before OCR ever runs."""
    if state.page_quality is None:
        # preprocess() didn't run (upstream error) or failed before producing
        # a quality verdict — a document with no quality assessment must be
        # treated as not-passed, never assumed OK by default.
        return {"trace": ["quality_gate"], "page_quality_ok": False}
    return {"trace": ["quality_gate"]}


def ocr(state: PipelineState) -> dict:
    """P2: PaddleOCR -> OcrPage (tokens + bboxes + per-token confidence),
    through a disk cache keyed on the preprocessed image's content hash so
    re-runs on the same document are fast (see ocr/cache.py — this matters
    even more than usual given the documented environment performance issue
    in ocr/paddle_engine.py)."""
    if not state.preprocessed_image_path:
        # quality_gate already short-circuits a failed/errored document to
        # review before this node would run in the real graph, but guard
        # anyway rather than assume that always holds.
        return {"trace": ["ocr"], "errors": ["ocr: no preprocessed image available"]}

    settings = load_settings()
    # Cache lives at a fixed, content-addressed location (settings.ocr.cache_dir),
    # not under this run's document_id folder — see ocr/cache.py docstring.
    cache = OcrCache(settings.ocr.cache_dir)

    try:
        page, cache_hit = cache.get_or_compute(
            state.preprocessed_image_path,
            lambda: run_ocr(state.preprocessed_image_path, settings, source_file=state.source_file, page_number=state.page_number),
        )
    except Exception as exc:  # noqa: BLE001 — an OCR failure routes to review, never crashes the graph
        return {"trace": ["ocr"], "errors": [f"ocr: {exc}"]}

    return {"trace": ["ocr"], "ocr_page": page}


def segment_regions(state: PipelineState) -> dict:
    """P3: region typer (page_header/stock_table/purchase_detail/totals/...).
    See IMPLEMENTATION_PLAN.md section 4.2."""
    if state.ocr_page is None:
        return {"trace": ["segment_regions"], "errors": ["segment_regions: no OCR tokens available"]}

    try:
        regions = layout_regions.segment_regions(state.ocr_page.tokens)
    except Exception as exc:  # noqa: BLE001 — a layout failure routes to review, never crashes the graph
        return {"trace": ["segment_regions"], "errors": [f"segment_regions: {exc}"]}

    result = LayoutResult(
        source_file=state.ocr_page.source_file,
        page_number=state.ocr_page.page_number,
        regions=regions,
    )
    return {"trace": ["segment_regions"], "layout_result": result}


def reconstruct_headers(state: PipelineState) -> dict:
    """P3: hierarchical header reconstruction (OPENING -> {QTY., VALUE}).
    See IMPLEMENTATION_PLAN.md section 4.5.

    A no-op pass-through here, not a gap: header reconstruction and column
    banding turned out tightly interdependent while building this (a leaf
    header's x-position directly determines its column's x-center — see
    layout/columns.py), so they run together as one step in assemble_table
    rather than as two independently-stateful nodes recomputing the same
    header split. Kept as its own node for fidelity to the plan's stage
    list and pipeline diagram, not because there is separate work to do
    here that assemble_table doesn't already do.
    """
    return {"trace": ["reconstruct_headers"]}


def assemble_table(state: PipelineState) -> dict:
    """P3: borderless column-band inference + sloped-baseline row assembly.
    See IMPLEMENTATION_PLAN.md sections 4.3-4.4 — the highest-risk stage.
    Also does reconstruct_headers' work — see that node's docstring."""
    if state.ocr_page is None:
        return {"trace": ["assemble_table"], "errors": ["assemble_table: no OCR tokens available"]}

    try:
        grid = layout_tables.assemble_stock_table(state.ocr_page.tokens)
    except Exception as exc:  # noqa: BLE001 — a layout failure routes to review, never crashes the graph
        return {"trace": ["assemble_table"], "errors": [f"assemble_table: {exc}"]}

    existing = state.layout_result
    tables = [grid] if grid is not None else []
    if existing is not None:
        updated = existing.model_copy(update={"tables": tables})
    else:
        updated = LayoutResult(
            source_file=state.ocr_page.source_file, page_number=state.ocr_page.page_number, tables=tables
        )
    return {"trace": ["assemble_table"], "layout_result": updated}


def detect_document(state: PipelineState) -> dict:
    """P4: distributor/company/period + template fingerprint. See
    IMPLEMENTATION_PLAN.md section 4.9 and the P4 phase-table entry.

    A missing distributor or company is not silently left null: it's
    appended to `errors`, which `route_after_validate` already routes to
    review_queue for any reason (IMPLEMENTATION_PLAN.md section 8b, E2 —
    "no distributor/company text found anywhere in the OCR output" must be
    an explicit needs_review condition). A missing statement period is NOT
    flagged the same way: confirmed on doc6.jpg that no date pattern exists
    anywhere in its OCR output at all, most likely because the source
    photograph simply doesn't frame whatever line would show it — a real,
    honest data gap distinct from a detection failure.
    """
    if state.ocr_page is None or state.layout_result is None:
        return {"trace": ["detect_document"], "errors": ["detect_document: no OCR/layout result available"]}

    try:
        distributors_cfg = load_distributors()
        header_text = detect_document_module.header_region_text(state.ocr_page.tokens, state.layout_result.regions)
        section_label_texts = [
            text for table in state.layout_result.tables for text in table.section_label_rows.values()
        ]

        distributor_id, distributor_name, _confidence = detect_document_module.detect_distributor(
            header_text, distributors_cfg
        )
        company_name = detect_document_module.detect_company(header_text, distributors_cfg, section_label_texts)
        statement_from, statement_to = detect_document_module.detect_period(header_text)

        column_mappings_cfg = load_column_mappings()
        product_name_aliases = column_mappings_cfg.get("product_name_raw", {}).get("aliases", [])
        columns = state.layout_result.tables[0].columns if state.layout_result.tables else []
        document_type = detect_document_module.detect_document_type(columns, product_name_aliases)

        # P13: fingerprinted with the same field dictionary + abbreviation
        # table real column resolution uses (not bare lowercase+strip), so
        # two OCR-garbled spellings of one real header that both
        # confidently fuzzy-match the same canonical field converge to the
        # same fingerprint — see detect/fingerprint.py::leaf_fingerprint_key.
        field_entries = mapping_dictionary.load_field_entries(column_mappings_cfg)
        abbreviations = load_abbreviations()
        template_fingerprint = (
            fingerprint_module.compute_fingerprint(columns, field_entries, abbreviations) if columns else None
        )
    except Exception as exc:  # noqa: BLE001 — a detection failure routes to review, never crashes the graph
        return {"trace": ["detect_document"], "errors": [f"detect_document: {exc}"]}

    missing = []
    if distributor_id is None:
        missing.append("distributor")
    if company_name is None:
        missing.append("company")
    errors = (
        [f"detect_document: could not identify {' and '.join(missing)} from OCR text "
         "(page_header/statement_meta text may be undetected or unrecognized)"]
        if missing
        else []
    )

    result = {
        "trace": ["detect_document"],
        "distributor_id": distributor_id,
        "distributor_name": distributor_name,
        "company_name": company_name,
        "statement_from": statement_from,
        "statement_to": statement_to,
        "document_type": document_type,
        "template_fingerprint": template_fingerprint,
    }
    if errors:
        result["errors"] = errors
    return result


def map_columns(state: PipelineState) -> dict:
    """P5: DictionaryResolver -> ReviewQueueResolver (SemanticResolver seam,
    section 0). No LLM call exists anywhere in this node in the MVP — adding
    LocalLlmResolver later means inserting one more entry into `resolvers`
    below, nothing else.

    A page with no assembled stock_table (e.g. it never reached one, or P3
    genuinely found none) has no columns to map — an empty ColumnMapping,
    not an error; a summary-only document is a legitimate outcome (CLAUDE.md
    section "3-level data model"), not a mapping failure.
    """
    if not state.layout_result or not state.layout_result.tables:
        return {"trace": ["map_columns"], "column_mapping": ColumnMapping(decisions=[])}

    try:
        field_entries = mapping_dictionary.load_field_entries(load_column_mappings())
        settings = load_settings()
        abbreviations = load_abbreviations()
        accept_threshold = settings.semantic_mapping.fuzzy_accept_threshold
        resolvers = [
            DictionaryResolver(
                field_entries,
                load_templates(),
                accept_threshold=accept_threshold,
                low_confidence_threshold=settings.semantic_mapping.fuzzy_review_threshold,
                abbreviations=abbreviations,
            ),
            ReviewQueueResolver(),
        ]
        ctx = TableContext(distributor_id=state.distributor_id, fingerprint=state.template_fingerprint)

        grid = state.layout_result.tables[0]
        decisions = [resolve_header(column.header, ctx, resolvers) for column in grid.columns]

        _cache_resolved_template(
            ctx.fingerprint, grid.columns, decisions, field_entries, abbreviations, accept_threshold,
            settings.resolve_path("templates"),
        )
    except Exception as exc:  # noqa: BLE001 — a mapping failure routes to review, never crashes the graph
        return {"trace": ["map_columns"], "errors": [f"map_columns: {exc}"]}

    return {"trace": ["map_columns"], "column_mapping": ColumnMapping(decisions=decisions)}


_CACHEABLE_STATUSES = {MappingStatus.exact, MappingStatus.normalized, MappingStatus.fuzzy, MappingStatus.template_cache}


def _cache_resolved_template(
    fingerprint: str | None,
    columns,
    decisions,
    field_entries,
    abbreviations: dict[str, str],
    accept_threshold: float,
    templates_file,
) -> None:
    """P13: write this table's confidently-resolved columns into
    templates.yaml, keyed by its fingerprint, so a future document sharing
    this exact layout hits tier 1 for THOSE columns instead of re-running
    tiers 2-4 — closing the gap detect/fingerprint.py::lookup_fingerprint's
    own docstring already described but nothing ever implemented
    (confirmed: config/templates.yaml stayed `fingerprints: {}` through
    P5-P12).

    Caches PER COLUMN, not all-or-nothing for the whole table — tried an
    all-or-nothing gate first and verified directly against a real pipeline
    run that it never actually caches anything: every one of the 6 real
    sample documents has at least one genuinely unresolved or
    low-confidence column by design (CLAUDE.md's own open decisions D1/D2,
    OCR too garbled to trust — e.g. doc6.jpg's DOM2/CEY), so requiring
    every column to be confident before caching ANY of them means the
    cache would stay empty in practice. A column left out of a
    fingerprint's cached mapping simply falls through to a fresh tiers-2-4
    resolution next time (same as an uncached table today, not a
    regression) — its own raw text can legitimately differ from what
    produced this document's cache entry (P13's whole point), so
    re-checking it fresh is correct, not wasted work.

    Still never caches an unresolved or merely-fuzzy_low_confidence
    decision — caching a shaky guess would let one bad early read poison
    every later document sharing this fingerprint for that column (same
    reasoning lookup_fingerprint's own docstring states). A caching
    failure (e.g. a disk write issue) must not turn an otherwise-
    successful column resolution into a map_columns error — this is a
    performance/consistency optimization on top of already-correct
    resolution, not correctness-critical itself, so it's swallowed here
    rather than left to propagate out of the try block above.
    """
    if not fingerprint or not decisions:
        return
    try:
        leaf_mapping = {
            fingerprint_module.leaf_fingerprint_key(col.header, field_entries, abbreviations, accept_threshold): (
                d.canonical_field
            )
            for col, d in zip(columns, decisions)
            if d.status in _CACHEABLE_STATUSES
        }
        if leaf_mapping:
            template_cache_module.save_fingerprint(fingerprint, leaf_mapping, templates_file)
    except Exception:  # noqa: BLE001 — see docstring: never let a cache-write failure fail real resolution
        pass


def assemble_canonical(state: PipelineState) -> dict:
    """P6: write Level 2/3 + CanonicalRow join view, many-to-one fields summed
    into source_field_breakdown.

    Also merges P4's detection results into the final DocumentRecord —
    ingest (P0) intentionally left distributor/company/period/document_type
    None (its own docstring: "resolving them is detect_document's job"),
    since detect_document (P4) runs after ingest in the graph and could not
    have populated them yet at that point.
    """
    if state.document_record is None:
        return {"trace": ["assemble_canonical"], "errors": ["assemble_canonical: no DocumentRecord from ingest"]}

    document_record = state.document_record.model_copy(
        update={
            "distributor_id": state.distributor_id,
            "distributor_name": state.distributor_name,
            "company_name": state.company_name,
            "statement_from": state.statement_from,
            "statement_to": state.statement_to,
            "document_type": state.document_type,
        }
    )

    grid = state.layout_result.tables[0] if state.layout_result and state.layout_result.tables else None
    column_mapping = state.column_mapping or ColumnMapping(decisions=[])

    try:
        products, transactions, rows, assembly_errors = canonical_module.assemble_document(
            grid, column_mapping, document_record
        )
    except Exception as exc:  # noqa: BLE001 — an assembly failure routes to review, never crashes the graph
        return {
            "trace": ["assemble_canonical"],
            "document_record": document_record,
            "errors": [f"assemble_canonical: {exc}"],
        }

    result: dict = {
        "trace": ["assemble_canonical"],
        "document_record": document_record,
        "product_records": products,
        "transaction_records": transactions,
        "canonical_rows": rows,
    }
    if assembly_errors:
        result["errors"] = assembly_errors
    return result


def resolve_products(state: PipelineState) -> dict:
    """P6: hsn_code -> fuzzy match against the master catalogue (see
    resolve/products.py's own docstring for why "product code" isn't a
    separate tier — no such field exists anywhere in the data model or the
    real samples). Unmatched -> review, never guessed.

    Updates canonical_rows' product_id by POSITION, matching them 1:1
    against product_records — assemble_canonical builds both lists from the
    same per-row loop, in the same order (one CanonicalRow per
    ProductRecord for a product_level document; a summary document has no
    ProductRecords at all, so this is a no-op for it, correctly).
    """
    if not state.product_records:
        return {"trace": ["resolve_products"]}

    try:
        settings = load_settings()
        masters = load_products_master(settings.resolve_path("data_masters") / "products.csv")

        updated_products: list = []
        updated_rows = list(state.canonical_rows)
        for i, product in enumerate(state.product_records):
            product_id, _reason = resolve_product(product, masters)
            updated_products.append(product if product_id is None else product.model_copy(update={"product_id": product_id}))
            if product_id is not None and i < len(updated_rows):
                updated_rows[i] = updated_rows[i].model_copy(update={"product_id": product_id})
    except Exception as exc:  # noqa: BLE001 — a resolution failure routes to review, never crashes the graph
        return {"trace": ["resolve_products"], "errors": [f"resolve_products: {exc}"]}

    return {
        "trace": ["resolve_products"],
        "product_records": updated_products,
        "canonical_rows": updated_rows,
    }


def validate(state: PipelineState) -> dict:
    """P7: rules R1-R7 (reconciliation, cross-foot, rate coherence, ...).
    See validate/engine.py for the actual rule orchestration — this node
    stays a thin adapter over PipelineState, matching every other
    real-logic node in this file.

    Any row failing one or more applicable rules appends a descriptive
    error, which the existing `route_after_validate` conditional edge
    (unmodified — already routes on any accumulated error) sends to
    `review_queue` instead of `persist`: this MVP has no mechanism to
    persist some rows from a document while reviewing others, so one
    failing row routes the whole document to review, matching how the
    review UI is described (a human reviews a document's rows together,
    not one row in isolation)."""
    if not state.canonical_rows:
        return {"trace": ["validate"]}

    try:
        grid = state.layout_result.tables[0] if state.layout_result and state.layout_result.tables else None
        regions = state.layout_result.regions if state.layout_result else []
        page_tokens = state.ocr_page.tokens if state.ocr_page else []
        settings = load_settings()
        validation_rules_cfg = load_validation_rules()
        rate_tolerance_pct = validation_rules_cfg.get("rate_coherence", {}).get(
            "tolerance_pct", settings.validation.rate_tolerance_pct
        )
        derived_groups = load_column_mappings().get("derived_check_only", {}).get("received_sold_groups", {})

        results, updated_rows = validate_document(
            document_id=state.document_id,
            canonical_rows=state.canonical_rows,
            grid=grid,
            column_mapping=state.column_mapping,
            page_tokens=page_tokens,
            regions=regions,
            page_quality_ok=state.page_quality_ok,
            distributor_id=state.distributor_id,
            distributors_cfg=load_distributors(),
            validation_rules_cfg=validation_rules_cfg,
            derived_received_aliases=derived_groups.get("received"),
            derived_sold_aliases=derived_groups.get("sold"),
            rate_tolerance_pct=rate_tolerance_pct,
            totals_tolerance_abs=settings.validation.totals_tolerance_abs,
            min_field_confidence=settings.validation.min_field_confidence,
        )
    except Exception as exc:  # noqa: BLE001 — a validation failure routes to review, never crashes the graph
        return {"trace": ["validate"], "errors": [f"validate: {exc}"]}

    needs_review_count = sum(1 for r in updated_rows if r.review_status == ReviewStatus.needs_review)
    result: dict = {"trace": ["validate"], "validation_results": results, "canonical_rows": updated_rows}
    if needs_review_count:
        result["errors"] = [f"validate: {needs_review_count} of {len(updated_rows)} row(s) failed one or more validation rules"]
    return result


def _persist_document(state: PipelineState) -> None:
    """Shared write path for both `persist` and `review_queue` below (P8).

    route_after_validate sends a document to EXACTLY ONE of those two nodes,
    never both — but P8's done-criterion is "All 6 land in MySQL", and P7's
    own real, verified finding (see IMPLEMENTATION_PLAN.md's P7 build notes
    and test_pipeline_smoke.py) is that every one of the 6 real sample
    documents currently routes to review_queue, not persist. If only
    persist() wrote to the database, none of the 6 real documents would
    ever reach it. schemas/canonical.py's ReviewStatus values
    (auto_accepted/needs_review/human_corrected) describe the status of a
    row already in the dataset, not a gate on whether it's written at all —
    so both nodes call this, and only the state flag they set afterward
    differs.

    A no-op when ingest never produced a DocumentRecord at all (e.g. the
    source file didn't exist) — there is nothing to persist, and no real
    sample document hits this path (see graph/nodes.py::ingest).
    """
    if state.document_record is None:
        return

    session = persist_db.get_session()
    try:
        save_document(
            session,
            state.document_record,
            state.product_records,
            state.transaction_records,
            state.canonical_rows,
            state.validation_results,
        )
    finally:
        session.close()


def persist(state: PipelineState) -> dict:
    """P8: write to MySQL (canonical schema, full traceability)."""
    try:
        _persist_document(state)
    except Exception as exc:  # noqa: BLE001 — a persistence failure routes to review-visible errors, never crashes the graph
        return {"trace": ["persist"], "persisted": False, "errors": [f"persist: {exc}"]}
    return {"trace": ["persist"], "persisted": True}


def review_queue(state: PipelineState) -> dict:
    """P9/P10: route needs_review rows to the human review UI instead of
    silently accepting them. Still persists first (see _persist_document) —
    a row awaiting review is in the dataset already, just flagged, not
    withheld from it."""
    try:
        _persist_document(state)
    except Exception as exc:  # noqa: BLE001 — a persistence failure must not crash the graph
        return {"trace": ["review_queue"], "routed_to_review": True, "errors": [f"review_queue: {exc}"]}
    return {"trace": ["review_queue"], "routed_to_review": True}


def export(state: PipelineState) -> dict:
    """P8: Excel export. Reads back through the database (persist/
    repository.py) rather than from in-memory state, matching CLAUDE.md's
    own pipeline diagram, which draws Excel export downstream of MYSQL
    (`K[MYSQL] --> M[Excel export / API]`), not as a second consumer of
    pipeline state — this document's own persist/review_queue step (both
    routes call _persist_document) already ran by the time this node is
    reached, per graph/build.py's edges."""
    settings = load_settings()
    output_path = settings.resolve_path("data_output") / f"{state.document_id}.xlsx"

    session = persist_db.get_session()
    try:
        export_to_excel(session, output_path, document_id=state.document_id)
    except Exception as exc:  # noqa: BLE001 — an export failure must not crash the graph
        return {"trace": ["export"], "errors": [f"export: {exc}"]}
    finally:
        session.close()

    return {"trace": ["export"], "export_path": str(output_path)}


def route_after_quality_gate(state: PipelineState) -> str:
    """A page that fails the quality gate is NOT passed to OCR (CLAUDE.md /
    IMPLEMENTATION_PLAN.md section 4.1) — it short-circuits straight to the
    review queue instead of running OCR/layout/mapping on input already
    known to be poor (page_truncated, too blurry, ...)."""
    if state.errors or state.page_quality_ok is False:
        return "review_queue"
    return "ocr"


def route_after_validate(state: PipelineState) -> str:
    """Conditional edge: any error recorded so far sends the document to the
    review queue instead of straight to persist. In P0/P1 this only ever
    exists to prove the graph can branch; the real signal (rule failures /
    needs_review rows) lands in P7.
    """
    return "review_queue" if state.errors else "persist"
