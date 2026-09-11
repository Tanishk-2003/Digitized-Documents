"""P0: prove the LangGraph scaffold itself is correct, independent of any
real document — node order, state-reducer behaviour (trace/errors must
accumulate, not overwrite), and conditional routing.

The `ocr` node stopped being a no-op in P2 (real PaddleOCR calls, disk
cache). Graph-wiring tests here mock it out — this file's job is "does the
graph traverse correctly", not "does OCR work" (that's
tests/integration/test_ocr_real_images.py), and in this environment a real
OCR call is genuinely slow (see ocr/paddle_engine.py) — letting it slip into
an ostensibly-fast unit test file would silently make the whole suite slow.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from pharma_di.config import load_settings
from pharma_di.graph import nodes
from pharma_di.graph.build import compiled_graph
from pharma_di.graph.state import PipelineState
from pharma_di.ocr.cache import OcrCache
from pharma_di.persist.db import database_url
from pharma_di.persist.models import Base
from pharma_di.schemas.ocr import BBox, OcrPage, OcrToken


@pytest.fixture(autouse=True)
def _stub_ocr(monkeypatch, tmp_path):
    """Replace the real PaddleOCR call with a fast, deterministic stub for
    every test in this file — graph-wiring correctness doesn't depend on
    OCR producing real content, only on the node running and returning
    something schema-valid. Also redirects the cache to an isolated tmp
    directory: found this session that a stub result written through the
    real `ocr` node lands in the project's real, shared OCR cache
    (data/interim/ocr_cache) exactly like a real result would — a synthetic
    test document must not pollute it."""

    def _fake_run_ocr(image_path, settings, source_file, page_number=1):
        return OcrPage(
            source_file=source_file,
            page_number=page_number,
            image_width=10,
            image_height=10,
            tokens=[OcrToken(text="STUB", bbox=BBox(x0=0, y0=0, x1=5, y1=5), confidence=0.9)],
        )

    monkeypatch.setattr(nodes, "run_ocr", _fake_run_ocr)
    monkeypatch.setattr(nodes, "OcrCache", lambda cache_dir: OcrCache(tmp_path / "ocr_cache_test_isolation"))

    # detect_document (P4) now does real fuzzy-matching against
    # config/distributors.yaml — stubbed to a deterministic success so this
    # file's graph-WIRING tests don't depend on the single "STUB" OCR token
    # above coincidentally matching (or not matching) real distributor text.
    # Whether real detection actually works is tested for real, against real
    # documents, in tests/integration/test_detect_real_images.py — not here.
    monkeypatch.setattr(
        nodes.detect_document_module,
        "detect_distributor",
        lambda text, cfg: ("stub-distributor", "Stub Distributor", 1.0),
    )
    monkeypatch.setattr(nodes.detect_document_module, "detect_company", lambda *args, **kwargs: "Stub Company")


@pytest.fixture(autouse=True)
def _isolated_persistence(monkeypatch, tmp_path):
    """P8: persist/review_queue/export now do real work (a database write,
    an Excel file) — every test in this file must use an isolated tmp
    database and output directory, never the real data/interim/pharma_di.db
    or data/output/ a genuine pipeline run would use.

    Overrides only `paths.data_output` on a copy of the real Settings
    object (not a fully fake one) so every other node's real thresholds
    stay exactly what production uses — this file's job is graph wiring,
    not re-verifying settings values other test files already cover.
    """
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test_graph.db'}")
    Base.metadata.create_all(create_engine(database_url()))

    real_settings = load_settings()
    fake_settings = real_settings.model_copy(
        update={"paths": {**real_settings.paths, "data_output": str(tmp_path / "output")}}
    )
    monkeypatch.setattr(nodes, "load_settings", lambda: fake_settings)


EXPECTED_HAPPY_PATH_ORDER = [
    "ingest",
    "preprocess",
    "quality_gate",
    "ocr",
    "segment_regions",
    "reconstruct_headers",
    "assemble_table",
    "detect_document",
    "map_columns",
    "assemble_canonical",
    "resolve_products",
    "validate",
    "persist",
    "export",
]


def _run(source_file: str, document_id: str) -> PipelineState:
    state = PipelineState(source_file=source_file, document_id=document_id)
    result = compiled_graph().invoke(state)
    return PipelineState.model_validate(result)


def test_graph_compiles():
    graph = compiled_graph()
    assert graph is not None


def test_happy_path_visits_every_node_in_declared_order(tmp_path):
    img = tmp_path / "fake.jpg"
    _write_quality_gate_passing_document(img)
    final = _run(str(img), "test-doc")
    assert final.page_quality is not None and final.page_quality.passed, (
        f"test fixture image must clear the quality gate for this to test the happy path "
        f"(got reasons={final.page_quality.reasons if final.page_quality else '?'})"
    )
    assert final.trace == EXPECTED_HAPPY_PATH_ORDER
    assert final.errors == []
    assert final.persisted is True
    assert final.routed_to_review is False
    assert final.ocr_page is not None and final.ocr_page.tokens[0].text == "STUB"


def test_missing_file_routes_to_review_queue_not_persist():
    final = _run("data/input/this-file-does-not-exist.jpg", "test-missing")
    assert final.errors, "ingest must record the missing-file condition, not silently continue"
    assert "review_queue" in final.trace
    assert "persist" not in final.trace
    assert final.routed_to_review is True
    assert final.persisted is False
    # The pipeline must still reach the end of the graph even on error — a
    # bad document is flagged, never silently dropped (CLAUDE.md).
    assert final.trace[-1] == "export"
    # It should also short-circuit at the quality gate rather than run
    # OCR/layout/mapping on a document that never even loaded.
    assert final.trace == ["ingest", "preprocess", "quality_gate", "review_queue", "export"]


def test_trace_accumulates_via_reducer_not_overwrite(tmp_path):
    # If Annotated[list[str], operator.add] were missing, trace would only
    # ever contain the *last* node's contribution instead of all 14. Uses
    # the full happy path (not the error path) specifically because that
    # path is long enough to distinguish "accumulated" from "overwritten".
    img = tmp_path / "fake.jpg"
    _write_quality_gate_passing_document(img)
    final = _run(str(img), "test-reducer")
    assert len(final.trace) == len(EXPECTED_HAPPY_PATH_ORDER)
    assert len(final.trace) == len(set(final.trace)), "every node should appear exactly once"


def test_ocr_node_reports_error_when_no_preprocessed_image():
    # Exercises nodes.ocr() directly (not through the graph) — this hits the
    # early-return guard before ever calling run_ocr, so it's fast
    # regardless of the OCR stub above.
    state = PipelineState(source_file="doc.jpg", document_id="test-no-preprocessed")
    result = nodes.ocr(state)
    assert result["trace"] == ["ocr"]
    assert result["errors"] == ["ocr: no preprocessed image available"]


def _write_quality_gate_passing_document(path) -> None:
    """A synthetic 'document' with enough real structure (sharp edges, high
    contrast, no content near the frame edges) to clear the real P1 quality
    gate — a blank/trivial image legitimately fails it (near-zero blur
    variance and contrast), which would make this a test of the short-circuit
    path instead of the happy path it's named for."""
    import cv2
    import numpy as np

    img = np.full((900, 1200), 255, dtype=np.uint8)
    for y in range(100, 800, 50):
        for x0 in range(80, 1100, 120):
            cv2.rectangle(img, (x0, y), (x0 + 90, y + 20), 0, -1)
    cv2.imwrite(str(path), img)
