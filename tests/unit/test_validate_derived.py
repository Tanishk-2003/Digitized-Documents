"""P7 unit tests for validate/derived.py — R3 derived columns cross-check
(IMPLEMENTATION_PLAN.md section 4.7)."""
from __future__ import annotations

from pharma_di.schemas.validation import RuleId
from pharma_di.validate.derived import check_derived_columns


def test_recognizes_total_received_and_checks_it():
    # Real doc2.jpg-shaped case.
    breakdown = {"Total Revd.": 68.0}
    values = {"received_quantity": 60.0, "free_received_quantity": 8.0}
    results = check_derived_columns(breakdown, values)
    assert len(results) == 1
    assert results[0].rule_id == RuleId.r3_derived_columns
    assert results[0].passed is True


def test_recognizes_total_sold_and_checks_it():
    breakdown = {"Total Sold": 49.0}
    values = {"sales_quantity": 45.0, "free_sales_quantity": 4.0}
    results = check_derived_columns(breakdown, values)
    assert len(results) == 1
    assert results[0].passed is True


def test_fails_when_components_do_not_sum_to_printed_total():
    breakdown = {"Total Revd.": 999.0}
    values = {"received_quantity": 60.0, "free_received_quantity": 8.0}
    results = check_derived_columns(breakdown, values)
    assert results[0].passed is False
    assert results[0].delta != 0


def test_checks_both_totals_independently_when_both_present():
    breakdown = {"Total Revd.": 68.0, "Total Sold": 49.0}
    values = {
        "received_quantity": 60.0, "free_received_quantity": 8.0,
        "sales_quantity": 45.0, "free_sales_quantity": 4.0,
    }
    results = check_derived_columns(breakdown, values)
    assert len(results) == 2
    assert all(r.passed for r in results)


def test_skips_check_when_a_component_is_missing():
    # CLAUDE.md's null-vs-zero discipline: an unresolved component must not
    # be silently treated as 0 to force the check through.
    breakdown = {"Total Revd.": 68.0}
    values = {"received_quantity": 60.0, "free_received_quantity": None}
    assert check_derived_columns(breakdown, values) == []


def test_ignores_unrecognized_derived_header():
    breakdown = {"Some Unrelated Total": 100.0}
    values = {"received_quantity": 60.0, "free_received_quantity": 8.0}
    assert check_derived_columns(breakdown, values) == []


def test_empty_breakdown_produces_no_results():
    assert check_derived_columns({}, {"received_quantity": 60.0}) == []
