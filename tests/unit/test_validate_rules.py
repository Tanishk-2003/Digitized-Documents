"""P7 unit tests for validate/rules.py — R5 sign/plausibility + R7 page
integrity (IMPLEMENTATION_PLAN.md section 4.7)."""
from __future__ import annotations

from pharma_di.schemas.validation import RuleId
from pharma_di.validate.rules import check_page_integrity, check_sign_plausibility


# --- R5 sign/plausibility -------------------------------------------------------


def test_sign_plausibility_passes_for_all_nonnegative_values():
    result = check_sign_plausibility({"opening_quantity": 16, "closing_quantity": 16, "sales_quantity": 0})
    assert result.rule_id == RuleId.r5_sign_plausibility
    assert result.passed is True


def test_sign_plausibility_fails_on_a_negative_value():
    # Real doc5.jpg case (CLAUDE.md finding #8, open decision D4): RECEIPT
    # QTY = -1. Must fail by default — D4 is unresolved, not silently
    # exempted.
    result = check_sign_plausibility({"received_quantity": -1, "received_value": -216.27})
    assert result.passed is False
    assert "received_quantity" in result.detail


def test_sign_plausibility_respects_negative_allowed_fields():
    result = check_sign_plausibility({"received_quantity": -1}, negative_allowed_fields=frozenset({"received_quantity"}))
    assert result.passed is True


def test_sign_plausibility_ignores_none_values():
    result = check_sign_plausibility({"opening_quantity": None, "closing_quantity": 5})
    assert result.passed is True


def test_sign_plausibility_passes_with_no_fields_present():
    assert check_sign_plausibility({}).passed is True


# --- R7 page integrity -----------------------------------------------------------


def test_page_integrity_passes_when_everything_is_clean():
    result = check_page_integrity(page_quality_ok=True, header_column_count_mismatch=False, row_has_uncertain_cells=False)
    assert result.rule_id == RuleId.r7_page_integrity
    assert result.passed is True


def test_page_integrity_fails_when_quality_gate_failed():
    result = check_page_integrity(page_quality_ok=False, header_column_count_mismatch=False, row_has_uncertain_cells=False)
    assert result.passed is False
    assert "quality gate" in result.detail


def test_page_integrity_fails_when_quality_was_never_assessed():
    result = check_page_integrity(page_quality_ok=None, header_column_count_mismatch=False, row_has_uncertain_cells=False)
    assert result.passed is False


def test_page_integrity_fails_on_header_column_count_mismatch():
    result = check_page_integrity(page_quality_ok=True, header_column_count_mismatch=True, row_has_uncertain_cells=False)
    assert result.passed is False
    assert "column count" in result.detail


def test_page_integrity_fails_on_uncertain_row_assignment():
    result = check_page_integrity(page_quality_ok=True, header_column_count_mismatch=False, row_has_uncertain_cells=True)
    assert result.passed is False
    assert "uncertain" in result.detail


def test_page_integrity_reports_multiple_reasons_together():
    result = check_page_integrity(page_quality_ok=False, header_column_count_mismatch=True, row_has_uncertain_cells=True)
    assert result.passed is False
    assert result.detail.count(";") == 2  # three reasons joined by "; "
