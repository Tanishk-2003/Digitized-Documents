"""Product master catalogue loading (IMPLEMENTATION_PLAN.md section 4.8):
reads data/masters/products.csv, the bootstrap catalogue extracted from the
six real sample documents (scripts/bootstrap_products_master.py) for human
confirmation.

A missing file is a legitimate, expected state before that bootstrap script
has been run — section 4.8's own dependency note: "Until it exists, product
resolution returns unmatched and rows route to review, which is correct
behaviour, not a failure" — not something to error on.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MasterProduct:
    product_id: str
    product_name_raw: str
    pack: str | None
    hsn_code: str | None


def load_products_master(path: str | Path) -> list[MasterProduct]:
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [
            MasterProduct(
                product_id=row["product_id"],
                product_name_raw=row["product_name_raw"],
                pack=row.get("pack") or None,
                hsn_code=row.get("hsn_code") or None,
            )
            for row in reader
        ]
