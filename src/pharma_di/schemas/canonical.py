"""The 3-level data model + canonical join-view row (CLAUDE.md "Data model:
3 levels, not one flat table" and "canonical Stock & Sale schema").

Naming note: CLAUDE.md itself uses two suffixes across its two tables — Level
3 ("Transaction/stock") lists `opening_qty`, `received_qty`, etc., while the
canonical join-view table lists `opening_quantity`, `received_quantity`, etc.
That is preserved here deliberately rather than "fixed": TransactionRecord
mirrors the Level-3 spec verbatim, CanonicalRow mirrors the canonical-schema
table verbatim, and producing one from the other is the assemble stage's job
(P6), not a naming decision made ahead of time in this module.

Every quantity/value field is Optional with no default-to-zero. CLAUDE.md is
explicit: "rate... null otherwise, not zero" and "You will not populate every
field for every document... That's a correct output, not a failure." A
summary-only document (doc3.jpg: Nabin page 1, PTR/PTS totals, no line items)
is the concrete case this exists for.
"""
from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class DocumentType(str, Enum):
    summary = "summary"
    product_level = "product_level"


class ReviewStatus(str, Enum):
    auto_accepted = "auto_accepted"
    needs_review = "needs_review"
    human_corrected = "human_corrected"


class DocumentRecord(BaseModel):
    """Level 1 — Document."""

    document_id: str
    distributor_id: str | None = None
    distributor_name: str | None = None
    company_name: str | None = None
    statement_from: dt.date | None = None
    statement_to: dt.date | None = None
    document_type: DocumentType | None = None
    source_file: str
    page_number: int = Field(ge=1)
    page_count: int = Field(ge=1)


class ProductRecord(BaseModel):
    """Level 2 — Product. Absent (None) entirely for summary-only documents —
    that is a modeling choice, not three null-filled fields standing in for
    "no products on this page"."""

    product_id: str | None = None   # None until product-master resolution (P6) runs
    product_name_raw: str
    hsn_code: str | None = None
    pack: str | None = None
    rate: float | None = None


class TransactionRecord(BaseModel):
    """Level 3 — Transaction/stock. One per product per period, or one per
    document for summary-only cases."""

    opening_qty: float | None = None
    opening_value: float | None = None
    received_qty: float | None = None
    received_value: float | None = None
    free_received_qty: float | None = None
    sales_qty: float | None = None
    free_sales_qty: float | None = None
    sales_value: float | None = None
    sales_return_qty: float | None = None
    purchase_return_qty: float | None = None
    expired_qty: float | None = None
    closing_qty: float | None = None
    closing_value: float | None = None
    dump_qty: float | None = None
    stock_status: str | None = None
    months_to_expiry: float | None = None


class CanonicalRow(BaseModel):
    """The canonical Stock & Sale schema: a join view across the three levels
    plus pipeline metadata. This is what gets validated, reviewed, exported to
    Excel, and written to MySQL — one row per (document, product) pair, or one
    row per document for summary-only statements.
    """

    # --- identity / provenance -------------------------------------------------
    distributor_id: str | None = None
    distributor_name: str | None = None
    company_name: str | None = None
    statement_from: dt.date | None = None
    statement_to: dt.date | None = None
    document_type: DocumentType

    # --- product (Level 2 join) -------------------------------------------------
    product_id: str | None = None
    product_name_raw: str | None = None
    hsn_code: str | None = None
    pack: str | None = None
    rate: float | None = None

    # --- transaction (Level 3 join), canonical-schema field names --------------
    opening_quantity: float | None = None
    opening_value: float | None = None
    received_quantity: float | None = None
    received_value: float | None = None
    free_received_quantity: float | None = None
    sales_quantity: float | None = None
    sales_value: float | None = None
    free_sales_quantity: float | None = None
    sales_return_quantity: float | None = None
    purchase_return_quantity: float | None = None
    expired_quantity: float | None = None
    closing_quantity: float | None = None
    closing_value: float | None = None
    dump_quantity: float | None = None
    months_to_expiry: float | None = None
    stock_status: str | None = None

    # --- pipeline metadata (checklist: first-class, not debug output) ----------
    source_field_breakdown: dict[str, Any] = Field(default_factory=dict)
    source_document: str
    page_number: int = Field(ge=1)
    extraction_confidence: dict[str, float] = Field(default_factory=dict)  # per FIELD, not per row
    review_status: ReviewStatus = ReviewStatus.needs_review
    review_reasons: list[str] = Field(default_factory=list)

    # checklist: "Every field ... populated or explicitly null with a reason"
    null_field_reasons: dict[str, str] = Field(default_factory=dict)

    # P10: columns that the mapping stage could not resolve — source header -> list of raw cell values.
    # Surfaced in the review UI's UnmappedColumnPanel for human mapping; promoted to
    # config/column_mappings.yaml via the /api/review/{id}/correct feedback loop.
    unmapped_columns: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _summary_documents_have_no_product_fields(self) -> "CanonicalRow":
        if self.document_type == DocumentType.summary:
            if self.product_id is not None or self.hsn_code is not None:
                raise ValueError(
                    "document_type=summary must not carry resolved product_id/hsn_code "
                    "— a summary document has no line items by definition."
                )
        return self
