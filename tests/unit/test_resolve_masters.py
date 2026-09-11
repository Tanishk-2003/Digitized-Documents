"""P6 unit tests for resolve/masters.py — product master catalogue loading
(IMPLEMENTATION_PLAN.md section 4.8)."""
from __future__ import annotations

import csv

from pharma_di.resolve.masters import MasterProduct, load_products_master


def test_load_products_master_returns_empty_list_when_file_missing(tmp_path):
    # Section 4.8's own dependency note: "Until it exists, product
    # resolution returns unmatched... correct behaviour, not a failure."
    assert load_products_master(tmp_path / "does-not-exist.csv") == []


def test_load_products_master_reads_real_rows(tmp_path):
    csv_path = tmp_path / "products.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["product_id", "product_name_raw", "pack", "hsn_code", "source_document"])
        writer.writeheader()
        writer.writerow(
            {"product_id": "p1", "product_name_raw": "COSKLOT REG TAB.", "pack": "10'S", "hsn_code": "", "source_document": "doc6.jpg"}
        )
        writer.writerow(
            {"product_id": "300490", "product_name_raw": "COSKLOT 500 10 TAB", "pack": "", "hsn_code": "300490", "source_document": "doc2.jpg"}
        )

    products = load_products_master(csv_path)
    assert products == [
        MasterProduct(product_id="p1", product_name_raw="COSKLOT REG TAB.", pack="10'S", hsn_code=None),
        MasterProduct(product_id="300490", product_name_raw="COSKLOT 500 10 TAB", pack=None, hsn_code="300490"),
    ]


def test_load_products_master_treats_empty_string_pack_and_hsn_as_none(tmp_path):
    # A blank CSV cell must not become the empty string "" as a value —
    # that would be a subtly different (and wrong) thing from "not present".
    csv_path = tmp_path / "products.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["product_id", "product_name_raw", "pack", "hsn_code"])
        writer.writeheader()
        writer.writerow({"product_id": "p1", "product_name_raw": "X", "pack": "", "hsn_code": ""})

    products = load_products_master(csv_path)
    assert products[0].pack is None
    assert products[0].hsn_code is None
