"""The uniform final output schema (IMPLEMENTATION_PLAN.md P14) — a NEW,
additional reporting table sitting downstream of the rich `CanonicalRow`
pipeline (schemas/canonical.py), not a replacement of it. R1-R7 validation,
confidence scoring, and the review queue all still depend on the detailed
schema; this is a deliberately narrower, always-uniform view built FROM it,
so the same 12 columns come out regardless of which distributor's layout
the source document used.

Field sourcing (see persist/repository.py::build_final_output_row and
IMPLEMENTATION_PLAN.md's P14 build notes for the full reasoning and the
mapping-choice caveats — several of these 12 columns have no natural,
unambiguous source in the existing data and were resolved by explicit
project-owner decision, not silently assumed):

- stockist_distributor_name <- Document.distributor_name
- address <- config/distributors.yaml's address field, looked up by
  distributor_id (NOT extracted from the page itself) — null with a
  reason when the distributor isn't in that config yet, same as an
  unresolved product routes to review rather than a guess.
- product_name <- Product.product_name_raw (the raw OCR'd string — there
  is no separately-cleaned "product name" anywhere in the schema)
- opening_qty / closing_qty <- Transaction.opening_qty / closing_qty
- dump_qty <- Transaction.dump_qty (P14's own new field — resolves open
  decision D2)
- file_name <- Document.source_file
- scan_date <- Document.created_at's date (when the pipeline ingested
  this document, NOT the statement's own printed period — a distinct
  concept already available in full via statement_from/statement_to on
  the richer schema)
- scan_by / update_by <- a fixed system-default string ("system") — no
  login/auth system exists in this MVP; per the project owner's own
  answer, this is deliberate, not a placeholder standing in for a
  missed requirement
- updated_on <- set at creation time, bumped whenever a human correction
  is applied via the review UI (api/routes_review.py::correct_document)
"""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class FinalStockSaleRow(BaseModel):
    """One row of the uniform final output table — always exactly these
    12 columns, in this order, regardless of the source document's format."""

    id: int | None = None
    stockist_distributor_name: str | None = None
    address: str | None = None
    product_name: str | None = None
    opening_qty: float | None = None
    closing_qty: float | None = None
    dump_qty: float | None = None
    scan_date: dt.date | None = None
    file_name: str | None = None
    scan_by: str = "system"
    update_by: str = "system"
    updated_on: dt.datetime | None = None
