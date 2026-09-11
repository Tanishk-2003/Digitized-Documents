"""P5 unit tests for mapping/dictionary.py — the mapping dictionary as a
queryable structure (IMPLEMENTATION_PLAN.md section 4.6)."""
from __future__ import annotations

from pharma_di.mapping.dictionary import load_field_entries


def test_load_field_entries_reads_paths_aliases_and_combine():
    cfg = {
        "opening_quantity": {"paths": [["opening", "qty."]], "aliases": ["opening stock"]},
        "sales_return_quantity": {"combine": "sum", "aliases": ["sale rtn", "market return"]},
    }
    entries = {e.canonical_field: e for e in load_field_entries(cfg)}

    assert entries["opening_quantity"].paths == [["opening", "qty."]]
    assert entries["opening_quantity"].aliases == ["opening stock"]
    assert entries["opening_quantity"].combine is None

    assert entries["sales_return_quantity"].combine == "sum"
    assert entries["sales_return_quantity"].aliases == ["sale rtn", "market return"]


def test_load_field_entries_defaults_missing_paths_and_aliases_to_empty():
    cfg = {"rate": {"aliases": ["rate"]}}
    entries = load_field_entries(cfg)
    assert entries[0].paths == []


def test_load_field_entries_includes_derived_check_only_like_any_other_field():
    # Its cells are consumed by validation (R3) rather than written to a
    # CanonicalRow field, but that is a downstream (P7) concern — at the
    # mapping stage it must still resolve like any other real column, not
    # be silently excluded and sent to unmapped_columns/needs_review.
    cfg = {"derived_check_only": {"aliases": ["total rcvd.", "total sold"]}}
    entries = load_field_entries(cfg)
    assert len(entries) == 1
    assert entries[0].canonical_field == "derived_check_only"


def test_load_field_entries_empty_config_returns_empty_list():
    assert load_field_entries({}) == []
