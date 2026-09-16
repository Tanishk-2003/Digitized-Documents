"""P0/P1 integration smoke test: run the real scaffold against all six real
sample photographs in data/input/. Checks that the scaffold survives
contact with real, messy input: large images, varied dimensions, no
crashes, schema-valid output, CORRECT node traversal (no longer always all
14 nodes, since P1 added the quality-gate short-circuit), and — since P8 —
that persistence and Excel export actually happen for every document
regardless of which route it takes.

As of P7, EVERY one of the six real samples correctly ends in
"review_queue", not "persist" — verified directly, not assumed. That's not
a bug in this test's expectations; it's the honest, unsurprising result of
P4 (distributor/company detection) and P7 (R1-R7 validation) both doing
real, thorough work against genuinely imperfect camera-photographed
dot-matrix input: doc4.jpg fails the P1 quality gate outright; the other
five each have at least one already-documented detection gap or a real,
characterized validation finding (a genuine negative receipt CLAUDE.md
itself flags as an open, unresolved question — D4; a totals-row digit that
doesn't cross-foot; OCR confidence below the review threshold on some
cells; ...). Exactly which rule fires on which row is covered in detail by
tests/integration/test_validate_real_images.py and
test_detect_real_images.py — this file only checks that node traversal
and routing are correct, not the specific content of every finding.

Every parametrized run gets its own isolated tmp-file SQLite database (via
DATABASE_URL — see persist/db.py), its own tmp Excel output directory, and
(P13) its own tmp templates.yaml (overriding only `paths.data_output`/
`paths.templates` on a copy of the real Settings, so every other real
threshold stays production-accurate) rather than touching the real
data/interim/pharma_di.db, data/output/, or config/templates.yaml a
genuine `python scripts/run_pipeline.py` run would use: a test suite must
not accumulate rows or files in, or depend on prior state of, any of them.
This file runs the real pipeline against all 6 real documents, several of
which resolve columns with real high confidence (P5 build notes) — exactly
the condition that now triggers a real template-cache write (P13), so this
isolation matters here more than almost anywhere else in the suite.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from pharma_di import config as config_module
from pharma_di.config import load_settings
from pharma_di.graph import nodes
from pharma_di.persist.db import database_url
from pharma_di.persist.models import Base
from pharma_di.persist.repository import load_canonical_rows
from scripts.run_pipeline import run_pipeline

REPO_ROOT = Path(__file__).resolve().parents[2]
INPUT_DIR = REPO_ROOT / "data" / "input"
SAMPLE_DOCS = sorted(INPUT_DIR.glob("doc*.jpg"))


@pytest.fixture(autouse=True)
def _isolated_database(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'test_pipeline.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    Base.metadata.create_all(create_engine(database_url()))

    real_settings = load_settings()
    fake_settings = real_settings.model_copy(
        update={
            "paths": {
                **real_settings.paths,
                "data_output": str(tmp_path / "output"),
                "templates": str(tmp_path / "templates.yaml"),
            }
        }
    )
    monkeypatch.setattr(nodes, "load_settings", lambda: fake_settings)
    # config.py::load_templates() resolves paths.templates via its OWN
    # load_settings() call (its own module namespace, not nodes.py's) —
    # patching nodes.load_settings alone doesn't reach it, so the tier-1
    # cache READ would still hit the real file even though the WRITE
    # (which goes through nodes.py's own, correctly-patched settings) is
    # isolated. Same fake_settings object, so load_column_mappings()/
    # load_distributors()/load_validation_rules() keep reading the real
    # files, matching this fixture's own "every other real threshold stays
    # production-accurate" intent.
    monkeypatch.setattr(config_module, "load_settings", lambda: fake_settings)

    return db_url


@pytest.mark.parametrize("doc_path", SAMPLE_DOCS, ids=[p.name for p in SAMPLE_DOCS])
def test_scaffold_runs_end_to_end_on_real_document(doc_path: Path, _isolated_database):
    final = run_pipeline(doc_path)

    assert final.trace[0] == "ingest"
    assert final.trace[-1] == "export"
    assert len(final.trace) == len(set(final.trace)), "every node should appear at most once"

    # No real bug in the P8 write/export path should ever surface as a
    # generic pipeline error — distinct from the validation-driven errors
    # every real document is expected to carry (checked below).
    p8_errors = [e for e in final.errors if e.startswith(("persist:", "review_queue:", "export:"))]
    assert not p8_errors, f"{doc_path.name}: unexpected persistence/export failure: {p8_errors}"

    if final.page_quality_ok:
        # Verified directly: all five documents that clear the quality gate
        # currently reach review_queue, not persist — see module docstring.
        assert final.trace == [
            "ingest", "preprocess", "quality_gate", "ocr", "segment_regions",
            "reconstruct_headers", "assemble_table", "detect_document", "map_columns",
            "assemble_canonical", "resolve_products", "validate", "review_queue", "export",
        ], f"{doc_path.name}: passed quality gate but didn't take the expected path: {final.trace}"
        assert final.errors, f"{doc_path.name}: reached review_queue but recorded no reason why"
    else:
        assert final.trace == ["ingest", "preprocess", "quality_gate", "review_queue", "export"], (
            f"{doc_path.name}: failed quality gate ({final.page_quality.reasons if final.page_quality else '?'}) "
            f"but didn't short-circuit correctly: {final.trace}"
        )

    # P8: every document — including doc4.jpg, which never gets past the
    # quality gate — reaches review_queue -> export (see graph/build.py),
    # and review_queue persists exactly like persist() would (see
    # graph/nodes.py::_persist_document's own docstring for why). So every
    # real sample document, with zero exceptions, must actually land in the
    # database and produce a real Excel file — this is P8's own stated
    # done-criterion ("All 6 land in MySQL"), checked here against real
    # pipeline output, not assumed from the node wiring alone.
    assert final.persisted != final.routed_to_review, (
        f"{doc_path.name}: persisted={final.persisted} routed_to_review={final.routed_to_review} "
        "— exactly one write-path flag should be set"
    )
    assert final.export_path is not None
    assert Path(final.export_path).exists(), f"{doc_path.name}: export_path recorded but file missing"

    engine = create_engine(_isolated_database)
    with Session(engine) as session:
        persisted_rows = load_canonical_rows(session, document_id=final.document_id)
    assert len(persisted_rows) == len(final.canonical_rows), (
        f"{doc_path.name}: {len(final.canonical_rows)} canonical row(s) in pipeline state "
        f"but {len(persisted_rows)} landed in the database"
    )

    # ingest's real (non-no-op) work: actual image dimensions were read.
    assert final.image_width and final.image_width > 0
    assert final.image_height and final.image_height > 0

    # Level-1 DocumentRecord was constructed and is schema-valid.
    assert final.document_record is not None
    assert final.document_record.source_file.endswith(doc_path.name)
    assert final.document_record.page_number == 1
    assert final.document_record.page_count == 1

    # P4 writes its detection result to state.document_type (and
    # distributor_id/distributor_name/company_name/statement_from/to)
    # directly; assemble_canonical (P6) merges those into this
    # DocumentRecord instance once the graph reaches it. A document that
    # never reaches assemble_canonical (doc4.jpg, short-circuited at the
    # quality gate) correctly still has it unset — never a guessed default
    # for a document nothing downstream ever classified.
    if "assemble_canonical" in final.trace:
        assert final.document_record.document_type is not None
    else:
        assert final.document_record.document_type is None


def test_all_six_expected_sample_documents_are_present():
    names = {p.name for p in SAMPLE_DOCS}
    assert names == {f"doc{i}.jpg" for i in range(1, 7)}, (
        "expected exactly doc1.jpg..doc6.jpg in data/input/ — "
        "IMPLEMENTATION_PLAN.md's phase table is written against these six files"
    )
