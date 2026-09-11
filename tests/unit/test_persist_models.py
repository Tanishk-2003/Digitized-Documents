"""P8 unit tests for persist/models.py — schema creation and the
relationships/cascades the repository layer depends on (IMPLEMENTATION_PLAN.md
P8: "MySQL schema (3 levels + review + corrections tables)").

Runs against SQLite (this environment's dev/test default — see persist/db.py)
using generic column types shared with the real MySQL target, so what these
tests prove (tables create, relationships resolve, cascades fire) holds for
either backend.
"""
from __future__ import annotations

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from pharma_di.persist.models import Base, Correction, Document, Product, ReviewRecord, Transaction


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_all_five_tables_are_created():
    engine = _engine()
    tables = set(inspect(engine).get_table_names())
    assert tables == {"documents", "products", "transactions", "review_records", "corrections"}


def test_product_level_relationship_chain_round_trips():
    engine = _engine()
    with Session(engine) as session:
        document = Document(id="doc-1", source_file="doc1.jpg", page_number=1, page_count=1)
        product = Product(document=document, product_name_raw="COSKLOT REG TAB.", hsn_code="30049099")
        transaction = Transaction(document=document, product=product, opening_qty=16.0, opening_value=6541.76)
        review = ReviewRecord(
            transaction=transaction,
            review_status="auto_accepted",
            review_reasons=[],
            rule_results=[{"rule_id": "R4_rate_coherence", "passed": True}],
            extraction_confidence={"opening_quantity": 0.98},
        )
        session.add_all([document, product, transaction, review])
        session.commit()

    with Session(engine) as session:
        loaded = session.get(Document, "doc-1")
        assert loaded is not None
        assert len(loaded.products) == 1
        assert loaded.products[0].hsn_code == "30049099"
        assert loaded.transactions[0].opening_qty == 16.0
        assert loaded.transactions[0].product.product_name_raw == "COSKLOT REG TAB."
        assert loaded.transactions[0].review.review_status == "auto_accepted"
        assert loaded.transactions[0].review.rule_results[0]["rule_id"] == "R4_rate_coherence"


def test_summary_document_has_a_transaction_with_no_product():
    # CLAUDE.md: Level 2 is "absent for summary-only documents" — modeled as
    # zero Product rows, not a Product with null fields (schemas/canonical.py
    # mirrors this: product_row_id is nullable for exactly this case).
    engine = _engine()
    with Session(engine) as session:
        document = Document(id="doc-3", source_file="doc3.jpg", page_number=1, page_count=1)
        transaction = Transaction(document=document, opening_value=109599.61, closing_value=47912.00)
        session.add_all([document, transaction])
        session.commit()

    with Session(engine) as session:
        loaded = session.get(Document, "doc-3")
        assert loaded.products == []
        assert loaded.transactions[0].product is None
        assert loaded.transactions[0].opening_value == 109599.61


def test_deleting_a_document_cascades_to_its_products_transactions_and_review():
    engine = _engine()
    with Session(engine) as session:
        document = Document(id="doc-1", source_file="doc1.jpg", page_number=1, page_count=1)
        product = Product(document=document, product_name_raw="COSKLOT REG TAB.")
        transaction = Transaction(document=document, product=product, opening_qty=16.0)
        review = ReviewRecord(transaction=transaction, review_status="needs_review", review_reasons=["r"])
        correction = Correction(transaction=transaction, field_name="opening_qty", corrected_value="17")
        session.add_all([document, product, transaction, review, correction])
        session.commit()

    with Session(engine) as session:
        session.delete(session.get(Document, "doc-1"))
        session.commit()

    with Session(engine) as session:
        assert session.get(Document, "doc-1") is None
        assert session.query(Product).count() == 0
        assert session.query(Transaction).count() == 0
        assert session.query(ReviewRecord).count() == 0
        assert session.query(Correction).count() == 0


def test_corrections_table_starts_and_stays_empty_with_no_write_path_yet():
    # models.py's own docstring: "no write path populates it yet — that's
    # the review UI's job (P10)". Documenting the current, correct state
    # rather than leaving it silently unverified.
    engine = _engine()
    with Session(engine) as session:
        assert session.query(Correction).count() == 0
