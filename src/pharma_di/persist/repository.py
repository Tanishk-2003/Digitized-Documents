"""Repository layer (IMPLEMENTATION_PLAN.md P8): writes one document's full
Level 1/2/3 + review output to the database, and reads the canonical
Stock & Sale schema back out as a join across those tables for export.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from pharma_di.assemble.canonical import LEVEL3_TO_TRANSACTION_FIELD
from pharma_di.persist.models import Document, Product, ReviewRecord, Transaction
from pharma_di.schemas.canonical import CanonicalRow, DocumentRecord, ProductRecord, TransactionRecord
from pharma_di.schemas.validation import RowValidationResult


def save_document(
    session: Session,
    document_record: DocumentRecord,
    product_records: list[ProductRecord],
    transaction_records: list[TransactionRecord],
    canonical_rows: list[CanonicalRow],
    validation_results: list[RowValidationResult],
) -> None:
    """Writes (or replaces, if this document_id was already persisted) one
    document's full Level 1/2/3 + review data — every row carries
    `source_document`/`page_number` traceability back to `document_record`
    (checklist). Re-persisting the same document_id deletes its prior rows
    first rather than duplicating them; in normal operation this doesn't
    matter (scripts/run_pipeline.py mints a fresh document_id per run), but
    a deliberate re-run of the same id should replace, not accumulate.

    `product_records`/`transaction_records`/`canonical_rows`/
    `validation_results` are assumed positionally aligned — assemble/
    canonical.py builds the first three from the same per-row loop, and
    validate/engine.py preserves that order — since neither ProductRecord
    nor TransactionRecord carries a key back to its originating row.
    """
    existing = session.get(Document, document_record.document_id)
    if existing is not None:
        session.delete(existing)
        session.flush()

    document = Document(
        id=document_record.document_id,
        distributor_id=document_record.distributor_id,
        distributor_name=document_record.distributor_name,
        company_name=document_record.company_name,
        statement_from=document_record.statement_from,
        statement_to=document_record.statement_to,
        document_type=document_record.document_type.value if document_record.document_type else None,
        source_file=document_record.source_file,
        page_number=document_record.page_number,
        page_count=document_record.page_count,
    )
    session.add(document)

    if product_records:
        # Product-level document: one Product + one Transaction per real row.
        for product_rec, txn_rec, canonical_row, validation_result in zip(
            product_records, transaction_records, canonical_rows, validation_results
        ):
            product = Product(
                document=document,
                product_id=product_rec.product_id,
                product_name_raw=product_rec.product_name_raw,
                hsn_code=product_rec.hsn_code,
                pack=product_rec.pack,
                rate=product_rec.rate,
            )
            session.add(product)
            _add_transaction_and_review(session, document, product, txn_rec, canonical_row, validation_result)
    else:
        # Summary-only document (CLAUDE.md: "emit a document-level
        # summary... not an error state") — assemble_document still emits
        # exactly one CanonicalRow with no ProductRecord; write it as a
        # Transaction with no Product, matching the schema's own nullable
        # product_row_id for exactly this case.
        for canonical_row, validation_result in zip(canonical_rows, validation_results):
            txn_kwargs = {
                txn_field: getattr(canonical_row, canon_field)
                for canon_field, txn_field in LEVEL3_TO_TRANSACTION_FIELD.items()
            }
            txn_rec = TransactionRecord(**txn_kwargs)
            _add_transaction_and_review(session, document, None, txn_rec, canonical_row, validation_result)

    session.commit()


def _add_transaction_and_review(
    session: Session,
    document: Document,
    product: Product | None,
    txn_rec: TransactionRecord,
    canonical_row: CanonicalRow,
    validation_result: RowValidationResult,
) -> None:
    transaction = Transaction(
        document=document,
        product=product,
        opening_qty=txn_rec.opening_qty,
        opening_value=txn_rec.opening_value,
        received_qty=txn_rec.received_qty,
        received_value=txn_rec.received_value,
        free_received_qty=txn_rec.free_received_qty,
        sales_qty=txn_rec.sales_qty,
        free_sales_qty=txn_rec.free_sales_qty,
        sales_value=txn_rec.sales_value,
        sales_return_qty=txn_rec.sales_return_qty,
        purchase_return_qty=txn_rec.purchase_return_qty,
        expired_qty=txn_rec.expired_qty,
        closing_qty=txn_rec.closing_qty,
        closing_value=txn_rec.closing_value,
        stock_status=txn_rec.stock_status,
        months_to_expiry=txn_rec.months_to_expiry,
    )
    session.add(transaction)

    review = ReviewRecord(
        transaction=transaction,
        review_status=canonical_row.review_status.value,
        review_reasons=list(canonical_row.review_reasons),
        rule_results=[r.model_dump(mode="json") for r in validation_result.rule_results],
        extraction_confidence=dict(canonical_row.extraction_confidence),
        source_field_breakdown=dict(canonical_row.source_field_breakdown),
        null_field_reasons=dict(canonical_row.null_field_reasons),
        unmapped_columns=dict(canonical_row.unmapped_columns),  # P10: unresolved headers for review UI
    )
    session.add(review)


def load_canonical_rows(session: Session, document_id: str | None = None) -> list[dict[str, Any]]:
    """Reads the canonical Stock & Sale schema back out as a join across
    Document + Product + Transaction + ReviewRecord (CLAUDE.md: the
    canonical schema "is a join view across these three levels, plus
    pipeline metadata") — one dict per Transaction row, field names matching
    CanonicalRow's own exactly (checklist: "Output matches canonical schema
    exactly"). Plain dicts, not CanonicalRow instances: the stricter
    validation CanonicalRow's own model enforces already ran once, when
    these rows were first assembled in P6 — reading them back doesn't need
    to repeat it.
    """
    query = session.query(Transaction).join(Document)
    if document_id is not None:
        query = query.filter(Document.id == document_id)

    rows: list[dict[str, Any]] = []
    for txn in query.all():
        doc = txn.document
        product = txn.product
        review = txn.review
        rows.append(
            {
                "distributor_id": doc.distributor_id,
                "distributor_name": doc.distributor_name,
                "company_name": doc.company_name,
                "statement_from": doc.statement_from,
                "statement_to": doc.statement_to,
                "document_type": doc.document_type,
                "product_id": product.product_id if product else None,
                "product_name_raw": product.product_name_raw if product else None,
                "hsn_code": product.hsn_code if product else None,
                "pack": product.pack if product else None,
                "rate": product.rate if product else None,
                "opening_quantity": txn.opening_qty,
                "opening_value": txn.opening_value,
                "received_quantity": txn.received_qty,
                "received_value": txn.received_value,
                "free_received_quantity": txn.free_received_qty,
                "sales_quantity": txn.sales_qty,
                "sales_value": txn.sales_value,
                "free_sales_quantity": txn.free_sales_qty,
                "sales_return_quantity": txn.sales_return_qty,
                "purchase_return_quantity": txn.purchase_return_qty,
                "expired_quantity": txn.expired_qty,
                "closing_quantity": txn.closing_qty,
                "closing_value": txn.closing_value,
                "months_to_expiry": txn.months_to_expiry,
                "stock_status": txn.stock_status,
                "source_field_breakdown": review.source_field_breakdown if review else {},
                "source_document": doc.source_file,
                "page_number": doc.page_number,
                "extraction_confidence": review.extraction_confidence if review else {},
                "review_status": review.review_status if review else None,
                "review_reasons": review.review_reasons if review else [],
                "null_field_reasons": review.null_field_reasons if review else {},
                # P10: unresolved source headers for the React UnmappedColumnPanel
                "unmapped_columns": review.unmapped_columns if review else {},
                # P10: internal transaction id for the React correction form's transaction_id field
                "_transaction_id": txn.id,
            }
        )
    return rows
