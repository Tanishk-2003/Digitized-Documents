#!/usr/bin/env python
"""Bootstrap the product master catalogue (IMPLEMENTATION_PLAN.md section
4.8): extract distinct (product_name_raw, pack, hsn_code) triples across
all six real sample documents into data/masters/products.csv, for human
confirmation. Until this file exists, product resolution correctly returns
unmatched and routes rows to review ("correct behaviour, not a failure",
per section 4.8) — this script is what turns that into a real, working seed
catalogue.

    python scripts/bootstrap_products_master.py

Runs the real pipeline end to end on every data/input/doc*.jpg (doc4.jpg
contributes nothing — it fails the P1 quality gate and never reaches table
assembly, same as in normal operation) and collects every ProductRecord
assemble_canonical (P6) produced. Product IDs are deterministic (the
hsn_code itself when present, else a slug of name+pack, disambiguated with
a numeric suffix only on a genuine collision) rather than random, so
re-running this script on unchanged input reproduces the same IDs — a human
reviewing/editing the output isn't chasing a moving target.

Re-running OVERWRITES the file with a freshly-extracted set — deliberately
not merged with a human-edited version (detecting "was this row edited by a
person" isn't implemented). Back up a confirmed file before re-running this.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from pharma_di.graph.build import compiled_graph  # noqa: E402
from pharma_di.graph.state import PipelineState  # noqa: E402

INPUT_DIR = REPO_ROOT / "data" / "input"
OUTPUT_PATH = REPO_ROOT / "data" / "masters" / "products.csv"

_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    return _SLUG_PATTERN.sub("-", text.strip().lower()).strip("-")[:40]


def _make_product_id(name: str, pack: str | None, hsn_code: str | None, used_ids: set[str]) -> str:
    if hsn_code:
        return hsn_code
    base = _slugify(name) + (f"-{_slugify(pack)}" if pack else "") or "product"
    if base not in used_ids:
        return base
    n = 2
    while f"{base}-{n}" in used_ids:
        n += 1
    return f"{base}-{n}"


def main() -> int:
    graph = compiled_graph()
    seen: dict[tuple[str, str | None, str | None], str] = {}
    used_ids: set[str] = set()
    rows: list[dict[str, str]] = []

    for doc_path in sorted(INPUT_DIR.glob("doc*.jpg")):
        state = PipelineState(source_file=str(doc_path), document_id=f"bootstrap-{doc_path.stem}")
        result = PipelineState.model_validate(graph.invoke(state))
        for product in result.product_records:
            key = (
                product.product_name_raw.strip().lower(),
                (product.pack or "").strip().lower() or None,
                product.hsn_code,
            )
            if key in seen:
                continue
            product_id = _make_product_id(product.product_name_raw, product.pack, product.hsn_code, used_ids)
            used_ids.add(product_id)
            seen[key] = product_id
            rows.append(
                {
                    "product_id": product_id,
                    "product_name_raw": product.product_name_raw,
                    "pack": product.pack or "",
                    "hsn_code": product.hsn_code or "",
                    "source_document": doc_path.name,
                }
            )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["product_id", "product_name_raw", "pack", "hsn_code", "source_document"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {len(rows)} distinct products to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
