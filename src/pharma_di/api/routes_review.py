"""Review queue management and human correction feedback loop routes (IMPLEMENTATION_PLAN.md P9/P10)."""
from __future__ import annotations

from collections import Counter
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from pharma_di.api.routes_documents import get_db
from pharma_di.assemble.canonical import LEVEL3_TO_TRANSACTION_FIELD, PRODUCT_CANONICAL_FIELDS, STRING_CANONICAL_FIELDS
from pharma_di.mapping.update import add_column_alias
from pharma_di.persist.models import Correction, Document, ReviewRecord, Transaction
from pharma_di.schemas.api import (
    ApproveDocumentRequest,
    ApproveDocumentResponse,
    CorrectionRequest,
    CorrectionResponse,
    ReviewQueueItem,
    ReviewReasonSummary,
)
from pharma_di.schemas.canonical import ReviewStatus

# UI-UX-Implementation.md Phase A.4 / a real, pre-existing gap this closes
# (flagged honestly in this project's own history rather than fixed in a
# rush at the time): FinalOutput is its own stored table (P14), not a
# computed view over Transaction/Product, so a correction that changes one
# of these four fields has to be written there too or the "Approved Data"
# export would keep showing the pre-correction value forever.
_FINAL_OUTPUT_FIELD = {
    "product_name_raw": "product_name",
    "opening_quantity": "opening_qty",
    "closing_quantity": "closing_qty",
    "dump_quantity": "dump_qty",
}


def _apply_correction(txn: Transaction, field_name: str, raw_value: str) -> None:
    """Actually applies a correction's value to the real column it belongs
    to. Until this existed, correct_document only ever wrote to the
    Correction audit table and flipped review_status — the corrected value
    itself never reached Transaction, Product, or FinalOutput, so "Correct"
    looked like it worked but silently didn't change the stored or exported
    data. Unrecognized field names are left alone rather than guessed at;
    the audit record still captures what was requested either way."""
    value: float | str | None
    if field_name in STRING_CANONICAL_FIELDS:
        value = raw_value or None
    else:
        try:
            value = float(raw_value) if raw_value not in ("", None) else None
        except ValueError:
            return

    if field_name in PRODUCT_CANONICAL_FIELDS:
        if txn.product is not None:
            setattr(txn.product, field_name, value)
    elif field_name in LEVEL3_TO_TRANSACTION_FIELD:
        setattr(txn, LEVEL3_TO_TRANSACTION_FIELD[field_name], value)

    final_output_field = _FINAL_OUTPUT_FIELD.get(field_name)
    if final_output_field and txn.final_output is not None:
        setattr(txn.final_output, final_output_field, value)

router = APIRouter(prefix="/api/review", tags=["review"])


@router.get(
    "-queue",
    response_model=list[ReviewQueueItem],
    summary="List all documents requiring human review",
)
async def get_review_queue(session: Session = Depends(get_db)) -> list[ReviewQueueItem]:
    documents = session.query(Document).order_by(Document.created_at.desc()).all()
    queue: list[ReviewQueueItem] = []

    for doc in documents:
        transactions = session.query(Transaction).filter(Transaction.document_id == doc.id).all()
        flagged_count = 0
        # UI-UX-Implementation.md Phase A.2: grouped by rule_id (a count per
        # R1-R7 rule, e.g. "3 rows failed R3") instead of a deduplicated set
        # of raw pre-formatted sentences — the old distinct_review_reasons
        # gave a UI nothing to key a business-friendly label off of besides
        # parsing the sentence itself.
        rule_counts: Counter[str] = Counter()
        rule_samples: dict[str, str] = {}

        for txn in transactions:
            if txn.review and txn.review.review_status == "needs_review":
                flagged_count += 1
                for r in txn.review.review_reasons or []:
                    # Rows persisted before this structured shape landed
                    # (UI-UX-Implementation.md Phase A.2) still hold a plain
                    # string in the real database — the JSON column doesn't
                    # retroactively reshape historical rows. Nothing to
                    # group such a reason by, so it's skipped here rather
                    # than crashing the whole queue; it'll gain a rule_id
                    # the next time that document is reprocessed.
                    if not isinstance(r, dict):
                        continue
                    rule_id = r.get("rule_id")
                    if not rule_id:
                        continue
                    rule_counts[rule_id] += 1
                    rule_samples.setdefault(rule_id, r.get("message", ""))

        if flagged_count > 0 or len(transactions) == 0:
            period_str = None
            if doc.statement_from or doc.statement_to:
                period_str = f"{doc.statement_from or ''} - {doc.statement_to or ''}"

            reason_summary = [
                ReviewReasonSummary(rule_id=rule_id, count=count, sample_detail=rule_samples[rule_id])
                for rule_id, count in sorted(rule_counts.items(), key=lambda kv: (-kv[1], kv[0]))
            ]

            queue.append(
                ReviewQueueItem(
                    document_id=doc.id,
                    distributor_name=doc.distributor_name,
                    company_name=doc.company_name,
                    statement_period=period_str,
                    document_type=doc.document_type,
                    source_file=doc.source_file,
                    total_rows=len(transactions),
                    flagged_rows_count=flagged_count,
                    review_reason_summary=reason_summary,
                )
            )

    return queue


@router.post(
    "/{document_id}/approve",
    response_model=ApproveDocumentResponse,
    summary="Approve all flagged transactions for a document",
)
async def approve_document(
    document_id: str,
    request: ApproveDocumentRequest | None = None,
    session: Session = Depends(get_db),
) -> ApproveDocumentResponse:
    doc = session.get(Document, document_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found",
        )

    reviews = (
        session.query(ReviewRecord)
        .join(Transaction)
        .filter(Transaction.document_id == document_id)
        .all()
    )

    updated_count = 0
    for rev in reviews:
        if rev.review_status == ReviewStatus.needs_review:
            # No distinct "approved without change" state exists in the
            # canonical schema's own closed review_status enum (CLAUDE.md:
            # auto_accepted | needs_review | human_corrected) — human_corrected
            # is the closest fit, since it's the only member representing a
            # human having acted on the row, whether or not a value changed.
            rev.review_status = ReviewStatus.human_corrected.value
            updated_count += 1

    session.commit()
    return ApproveDocumentResponse(
        document_id=document_id,
        status="approved",
        updated_rows=updated_count,
    )


@router.post(
    "/{document_id}/correct",
    response_model=CorrectionResponse,
    summary="Submit human corrections and promote confirmed aliases to configuration",
)
async def correct_document(
    document_id: str,
    request: CorrectionRequest,
    session: Session = Depends(get_db),
) -> CorrectionResponse:
    doc = session.get(Document, document_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found",
        )

    promoted: list[str] = []
    for mapping_corr in request.column_mappings:
        added = add_column_alias(
            canonical_field=mapping_corr.canonical_field,
            alias=mapping_corr.source_header,
        )
        if added:
            promoted.append(f"{mapping_corr.source_header} -> {mapping_corr.canonical_field}")

    transactions = session.query(Transaction).filter(Transaction.document_id == document_id).all()
    transactions_by_id = {t.id: t for t in transactions}
    updated_rows = 0

    for row_corr in request.row_corrections:
        txn_id = row_corr.get("transaction_id")
        field_name = row_corr.get("field_name")
        new_val = str(row_corr.get("corrected_value", ""))
        orig_val = str(row_corr.get("original_value", ""))

        if txn_id and field_name:
            corr_rec = Correction(
                transaction_id=int(txn_id),
                field_name=str(field_name),
                original_value=orig_val,
                corrected_value=new_val,
                corrected_by="human_reviewer",
                corrected_at=dt.datetime.now(dt.timezone.utc),
            )
            session.add(corr_rec)
            updated_rows += 1

            txn_for_field = transactions_by_id.get(int(txn_id))
            if txn_for_field is not None:
                _apply_correction(txn_for_field, str(field_name), new_val)

    corrected_transaction_ids = {int(rc["transaction_id"]) for rc in request.row_corrections if rc.get("transaction_id")}
    now = dt.datetime.utcnow()
    for txn in transactions:
        if txn.review and txn.review.review_status == "needs_review":
            txn.review.review_status = "human_corrected"
        # P14: a row a human touched should say so in the uniform final
        # table too, not just in the Correction audit log / review_status.
        if txn.id in corrected_transaction_ids and txn.final_output is not None:
            txn.final_output.update_by = "human_reviewer"
            txn.final_output.updated_on = now

    session.commit()

    return CorrectionResponse(
        document_id=document_id,
        status="corrected",
        promoted_mappings=promoted,
        updated_rows=updated_rows,
    )
