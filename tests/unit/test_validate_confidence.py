"""P7 unit tests for validate/confidence.py — R6 confidence gate
(IMPLEMENTATION_PLAN.md section 4.7)."""
from __future__ import annotations

from pharma_di.schemas.validation import RuleId
from pharma_di.validate.confidence import check_confidence_gate


def test_passes_when_every_field_clears_threshold():
    result = check_confidence_gate({"opening_quantity": 0.99, "rate": 0.90}, min_confidence=0.85)
    assert result.rule_id == RuleId.r6_confidence_gate
    assert result.passed is True


def test_fails_when_any_field_is_below_threshold():
    result = check_confidence_gate({"opening_quantity": 0.99, "sales_quantity": 0.42}, min_confidence=0.85)
    assert result.passed is False
    assert "sales_quantity" in result.detail


def test_passes_vacuously_with_no_recorded_confidences():
    result = check_confidence_gate({}, min_confidence=0.85)
    assert result.passed is True


def test_actual_reports_the_worst_confidence():
    result = check_confidence_gate({"a": 0.99, "b": 0.60, "c": 0.75}, min_confidence=0.85)
    assert result.actual == 0.60
