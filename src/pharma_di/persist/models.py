"""SQLAlchemy models for the canonical 3-level schema, plus review and
corrections tables (IMPLEMENTATION_PLAN.md P8; CLAUDE.md's Level 1/2/3 data
model and "MySQL schema (3 levels + review + corrections tables)").

Written against SQLAlchemy's generic column types (String, Integer, Double,
Date, DateTime, JSON) rather than any MySQL-specific dialect types, so the
identical model definitions and generated Alembic migrations work against
either backend this project targets — see persist/db.py for which one a
given run actually connects to.

P15 (real MySQL verification): every quantity/value/rate column uses
Double, not SQLAlchemy's Float. Confirmed directly against a real MySQL
instance, not assumed: Float compiles to MySQL's genuinely single-precision
FLOAT (~7 significant digits), which silently rounded a real doc3.jpg value
(opening_value 109599.61) to 109600.0 on write. SQLite never exposed this —
it stores any declared floating-point column as full 8-byte double
precision regardless of the declared type affinity, so the same code and
the same value round-tripped exactly there. Double compiles to MySQL's
DOUBLE (8-byte, ~15-17 significant digits), which comfortably holds every
value this pipeline handles, while remaining a no-op change for SQLite.

The canonical Stock & Sale schema (CanonicalRow) is NOT its own stored
table here: CLAUDE.md describes it as "a join view across these three
levels, plus pipeline metadata" — Document + Product + Transaction (+
ReviewRecord) already carry every field it needs, and persist/repository.py
reads them back out joined for export, rather than this module storing the
same data twice.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Date, DateTime, Double, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Document(Base):
    """Level 1 — one row per source page/document (CLAUDE.md's Document
    level). `id` is the pipeline's own document_id (e.g. "doc6-fc739f28"),
    already a meaningful unique string — no separate surrogate key needed."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    distributor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    distributor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    statement_from: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    statement_to: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    document_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_file: Mapped[str] = mapped_column(String(512), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)

    products: Mapped[list["Product"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Product(Base):
    """Level 2 — one row per (document, product) instance. Absent entirely
    for a summary-only document (CLAUDE.md: "absent for summary-only
    documents") — no rows are written here for one, not rows with null
    fields standing in for "no product."

    `product_id` is the resolved master-catalogue identifier
    (resolve/products.py) when a confident match was found, else NULL —
    "Unmatched products go to review, not to a guessed ID" (checklist).
    It intentionally has no FK constraint to a `products_master` table:
    the master catalogue is a CSV file (data/masters/products.csv, section
    4.8), not itself a DB table in this MVP.
    """

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False)
    product_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    product_name_raw: Mapped[str] = mapped_column(String(255), nullable=False)
    hsn_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pack: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rate: Mapped[float | None] = mapped_column(Double, nullable=True)

    document: Mapped[Document] = relationship(back_populates="products")
    transaction: Mapped["Transaction | None"] = relationship(back_populates="product", uselist=False)


class Transaction(Base):
    """Level 3 — one row per product per period, OR one row per document
    for a summary-only statement (CLAUDE.md: "one per product per period,
    or one per document for summary-only cases") — `product_id` (the FK,
    distinct from the master-catalogue `Product.product_id` string above)
    is nullable for exactly that summary case; `document_id` is always set.

    Field names mirror CLAUDE.md's own Level-3 spec verbatim ("_qty"
    suffix), the same discipline schemas/canonical.py's TransactionRecord
    already follows and documents — this table is that record's storage
    form, not the canonical join-view's "_quantity" naming.
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False)
    product_row_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True, unique=True)

    opening_qty: Mapped[float | None] = mapped_column(Double, nullable=True)
    opening_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    received_qty: Mapped[float | None] = mapped_column(Double, nullable=True)
    received_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    free_received_qty: Mapped[float | None] = mapped_column(Double, nullable=True)
    sales_qty: Mapped[float | None] = mapped_column(Double, nullable=True)
    free_sales_qty: Mapped[float | None] = mapped_column(Double, nullable=True)
    sales_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    sales_return_qty: Mapped[float | None] = mapped_column(Double, nullable=True)
    purchase_return_qty: Mapped[float | None] = mapped_column(Double, nullable=True)
    expired_qty: Mapped[float | None] = mapped_column(Double, nullable=True)
    closing_qty: Mapped[float | None] = mapped_column(Double, nullable=True)
    closing_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    dump_qty: Mapped[float | None] = mapped_column(Double, nullable=True)  # P14: resolves open decision D2
    stock_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    months_to_expiry: Mapped[float | None] = mapped_column(Double, nullable=True)

    document: Mapped[Document] = relationship(back_populates="transactions")
    product: Mapped[Product | None] = relationship(back_populates="transaction")
    review: Mapped["ReviewRecord | None"] = relationship(back_populates="transaction", uselist=False, cascade="all, delete-orphan")
    corrections: Mapped[list["Correction"]] = relationship(back_populates="transaction", cascade="all, delete-orphan")
    final_output: Mapped["FinalOutput | None"] = relationship(
        back_populates="transaction", uselist=False, cascade="all, delete-orphan"
    )


class ReviewRecord(Base):
    """P7's validation output for one Transaction row — CLAUDE.md checklist:
    "Confidence scores (per field, not just per row) and validation
    failures are first-class data, not debug output." One row per
    Transaction (`transaction_id` is unique).

    JSON columns hold the same structures schemas/validation.py already
    defines (RuleResult list, per-field confidence dict) rather than
    normalizing them into their own tables — no query pattern needing
    per-rule-across-rows analytics exists yet (that's a P9/P10-era need,
    if it ever becomes one), and adding that normalization speculatively
    would be exactly the kind of premature schema design CLAUDE.md's own
    "do not gold-plate beyond this" MVP guidance warns against.
    """

    __tablename__ = "review_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False, unique=True)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False)
    review_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    rule_results: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    extraction_confidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_field_breakdown: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    null_field_reasons: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # P10: unresolved source headers — source header -> list of raw cell values
    unmapped_columns: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)

    transaction: Mapped[Transaction] = relationship(back_populates="review")


class Correction(Base):
    """A human's correction to one extracted field (CLAUDE.md: "Every
    correction is retained — it becomes future mapping-dictionary entries
    and, longer-term, evaluation data"). Schema defined in P8; the write
    path is `api/routes_review.py::correct_document` (P10) — every
    row-level correction submitted through the review UI's feedback loop
    lands here, `corrected_by` currently always the literal string
    "human_reviewer" (no per-user identity exists in this MVP).
    """

    __tablename__ = "corrections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    original_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_value: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    corrected_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)

    transaction: Mapped[Transaction] = relationship(back_populates="corrections")


class FinalOutput(Base):
    """The uniform final output table (IMPLEMENTATION_PLAN.md P14,
    schemas/final_output.py::FinalStockSaleRow — see that module's own
    docstring for the full field-sourcing reasoning and mapping-choice
    caveats). One row per Transaction, same 1:1 shape as ReviewRecord.

    A real, stored, mutable table — not a computed-on-read view like
    CanonicalRow — deliberately: `update_by`/`updated_on` only make sense
    for a row that persists across a later correction, the same reasoning
    ReviewRecord/Correction already establish for this schema. Populated
    by persist/repository.py::save_document alongside every other Level
    1-3 table; `updated_on` is the first column in this schema to use
    `onupdate=` (nothing before P14 tracked a true "last modified" time —
    every other timestamp column here is insert-only `default=`).
    """

    __tablename__ = "final_output"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False, unique=True)
    stockist_distributor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    opening_qty: Mapped[float | None] = mapped_column(Double, nullable=True)
    closing_qty: Mapped[float | None] = mapped_column(Double, nullable=True)
    dump_qty: Mapped[float | None] = mapped_column(Double, nullable=True)
    scan_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    scan_by: Mapped[str] = mapped_column(String(255), nullable=False, default="system")
    update_by: Mapped[str] = mapped_column(String(255), nullable=False, default="system")
    updated_on: Mapped[dt.datetime] = mapped_column(
        DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow, nullable=False
    )

    transaction: Mapped[Transaction] = relationship(back_populates="final_output")
