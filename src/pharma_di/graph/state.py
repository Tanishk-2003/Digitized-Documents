"""LangGraph pipeline state (CLAUDE.md: "each pipeline stage above is a node,
with explicit state passed between nodes, not implicit globals").

PipelineState is the one object that flows through every node in
graph/build.py. Every stage reads its inputs from here and writes its outputs
back here — no stage reaches into another stage's internals or into a global.
"""
from __future__ import annotations

import datetime as dt
import operator
from typing import Annotated

from pydantic import BaseModel, Field

from pharma_di.schemas.canonical import CanonicalRow, DocumentRecord, DocumentType, ProductRecord, TransactionRecord
from pharma_di.schemas.layout import LayoutResult
from pharma_di.schemas.mapping import ColumnMapping
from pharma_di.schemas.ocr import OcrPage
from pharma_di.schemas.preprocess import PageQualityResult
from pharma_di.schemas.validation import RowValidationResult


class PipelineState(BaseModel):
    # --- input -------------------------------------------------------------
    source_file: str
    document_id: str
    debug: bool = False

    # --- ingest --------------------------------------------------------------
    page_number: int = 1
    page_count: int = 1
    image_width: int | None = None
    image_height: int | None = None

    # --- preprocess (P1) -----------------------------------------------------
    preprocessed_image_path: str | None = None
    page_quality: PageQualityResult | None = None
    page_quality_ok: bool | None = None   # convenience mirror of page_quality.passed

    # --- ocr (P2) --------------------------------------------------------------
    ocr_page: OcrPage | None = None

    # --- layout (P3) -----------------------------------------------------------
    layout_result: LayoutResult | None = None

    # --- detect (P4) -----------------------------------------------------------
    distributor_id: str | None = None
    distributor_name: str | None = None
    company_name: str | None = None
    statement_from: dt.date | None = None
    statement_to: dt.date | None = None
    document_type: DocumentType | None = None
    template_fingerprint: str | None = None

    # --- mapping (P5) ----------------------------------------------------------
    column_mapping: ColumnMapping | None = None

    # --- canonical assembly (P6) -----------------------------------------------
    document_record: DocumentRecord | None = None
    product_records: list[ProductRecord] = Field(default_factory=list)
    transaction_records: list[TransactionRecord] = Field(default_factory=list)
    canonical_rows: list[CanonicalRow] = Field(default_factory=list)

    # --- validation (P7) --------------------------------------------------------
    validation_results: list[RowValidationResult] = Field(default_factory=list)

    # --- persist / export (P8) --------------------------------------------------
    persisted: bool = False
    export_path: str | None = None
    routed_to_review: bool = False

    # --- cross-cutting: every node appends here, nothing overwrites these -------
    trace: Annotated[list[str], operator.add] = Field(default_factory=list)
    errors: Annotated[list[str], operator.add] = Field(default_factory=list)
