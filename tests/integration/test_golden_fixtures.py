"""P0: the golden fixtures themselves are a deliverable (IMPLEMENTATION_PLAN.md
section 6) — hand-transcribed ground truth for what P4 (document detection)
and later phases should extract. This test only checks internal consistency
now (every fixture parses, points at a real file, has a sane date range); it
becomes a real accuracy check once P4 exists to compare against.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = REPO_ROOT / "tests" / "fixtures" / "golden"
INPUT_DIR = REPO_ROOT / "data" / "input"

GOLDEN_FILES = sorted(GOLDEN_DIR.glob("doc*.json"))


@pytest.mark.parametrize("golden_path", GOLDEN_FILES, ids=[p.name for p in GOLDEN_FILES])
def test_golden_fixture_is_well_formed(golden_path: Path):
    data = json.loads(golden_path.read_text(encoding="utf-8"))

    for required in ("source_file", "distributor_name", "company_name", "document_type"):
        assert data.get(required), f"{golden_path.name}: missing required field {required!r}"

    assert (INPUT_DIR / data["source_file"]).exists(), (
        f"{golden_path.name} references {data['source_file']!r} which is not in data/input/"
    )

    assert data["document_type"] in ("summary", "product_level")

    if data["document_type"] == "summary":
        assert data["expected_line_item_count"] == 0
    else:
        assert data["expected_line_item_count"] > 0

    date_from = dt.date.fromisoformat(data["statement_from"])
    date_to = dt.date.fromisoformat(data["statement_to"])
    assert date_from < date_to, f"{golden_path.name}: statement_from must precede statement_to"


def test_all_six_golden_fixtures_exist():
    names = {p.stem for p in GOLDEN_FILES}
    assert names == {f"doc{i}" for i in range(1, 7)}


def test_exactly_one_summary_document_among_the_six():
    # doc3.jpg is the one company-level-only statement (Nabin Stock Value page).
    summary_docs = []
    for p in GOLDEN_FILES:
        data = json.loads(p.read_text(encoding="utf-8"))
        if data["document_type"] == "summary":
            summary_docs.append(data["source_file"])
    assert summary_docs == ["doc3.jpg"]


def test_purchase_detail_region_flagged_only_on_doc5():
    flagged = []
    for p in GOLDEN_FILES:
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("has_purchase_detail_region"):
            flagged.append(data["source_file"])
    assert flagged == ["doc5.jpg"]
