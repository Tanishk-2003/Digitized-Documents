"""Excel export (IMPLEMENTATION_PLAN.md P8; CLAUDE.md's pipeline diagram
draws Excel export as downstream of MYSQL, not of in-memory pipeline
state — `K[MYSQL] --> M[Excel export / API]` — so this reads back through
persist/repository.py's DB join rather than from a PipelineState directly.
That also makes it usable standalone (export whatever's currently in the
database, independent of any one pipeline run), matching how CLAUDE.md
frames Excel as a "consumption surface" for the system of record.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from pharma_di.persist.repository import load_canonical_rows, load_final_output_rows
from pharma_di.schemas.canonical import CanonicalRow
from pharma_di.schemas.final_output import FinalStockSaleRow

# Derived from the schema itself, not hand-copied, so a future field added to
# CanonicalRow is picked up automatically rather than silently missing from
# every export — checklist: "Output matches canonical schema exactly."
CANONICAL_COLUMNS = list(CanonicalRow.model_fields.keys())
FINAL_OUTPUT_COLUMNS = list(FinalStockSaleRow.model_fields.keys())

# Fields whose values are dicts/lists (JSON columns in review_records) — Excel
# cells hold only primitives, so these are serialized to a JSON string rather
# than dropped or left to fail inside openpyxl. `unmapped_columns` was found
# missing from this set while building the P14 export below (a real, if
# minor, bug — not left unfixed once spotted): without it, pandas/openpyxl
# silently fall back to Python's own repr() for that one column (single-
# quoted, not valid JSON), inconsistent with every other dict column here,
# which all get a real json.dumps() string via _stringify.
_JSON_FIELDS = {
    "source_field_breakdown", "extraction_confidence", "review_reasons", "null_field_reasons", "unmapped_columns",
}


def _stringify(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return value


def export_to_excel(session: Session, output_path: str | Path, document_id: str | None = None) -> Path:
    """Writes the canonical Stock & Sale schema to one .xlsx sheet, one row
    per persisted Transaction, columns matching CanonicalRow's field order
    exactly. `document_id=None` exports every document currently in the
    database, not just one run's — the natural default for a "give me
    everything persisted so far" export.
    """
    rows = load_canonical_rows(session, document_id=document_id)
    for row in rows:
        for field in _JSON_FIELDS:
            row[field] = _stringify(row.get(field))

    df = pd.DataFrame(rows, columns=CANONICAL_COLUMNS)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(output_path, index=False, engine="openpyxl")
    return output_path


def export_final_output_to_excel(session: Session, output_path: str | Path, document_id: str | None = None) -> Path:
    """P14: exports the uniform 12-column final output table — always
    these exact columns, in this order, regardless of which distributor's
    layout the source document used. Same DB-sourced, standalone-usable
    design as export_to_excel above, over schemas/final_output.py::
    FinalStockSaleRow instead of the richer CanonicalRow.
    """
    rows = load_final_output_rows(session, document_id=document_id)
    df = pd.DataFrame(rows, columns=FINAL_OUTPUT_COLUMNS)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(output_path, index=False, engine="openpyxl")
    return output_path
