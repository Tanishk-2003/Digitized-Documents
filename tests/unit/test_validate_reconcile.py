"""P7 unit tests for validate/reconcile.py — R1 reconciliation + R4 rate
coherence (IMPLEMENTATION_PLAN.md section 4.7)."""
from __future__ import annotations

import pytest

from pharma_di.schemas.validation import RuleId
from pharma_di.validate.reconcile import check_rate_coherence, check_reconciliation, eval_formula, referenced_names


# --- eval_formula: the safe evaluator itself ----------------------------------


def test_eval_formula_basic_arithmetic():
    assert eval_formula("a + b - c", {"a": 10, "b": 5, "c": 3}) == 12


def test_eval_formula_supports_multiplication_and_division():
    assert eval_formula("a * b / c", {"a": 6, "b": 2, "c": 3}) == 4.0


def test_eval_formula_supports_unary_minus():
    assert eval_formula("-a + b", {"a": 5, "b": 10}) == 5


def test_eval_formula_supports_numeric_literals():
    assert eval_formula("a + 100", {"a": 5}) == 105


def test_eval_formula_raises_key_error_for_missing_name():
    with pytest.raises(KeyError):
        eval_formula("a + b", {"a": 1})


def test_eval_formula_rejects_function_calls():
    # The whole point of ast-walking with an allow-list: no eval(), no
    # arbitrary code execution via a config string.
    with pytest.raises(ValueError):
        eval_formula("__import__('os').system('echo hi')", {})


def test_eval_formula_rejects_attribute_access():
    with pytest.raises(ValueError):
        eval_formula("a.__class__", {"a": 1})


def test_referenced_names_finds_every_name_once():
    assert referenced_names("opening_quantity + received_quantity - closing_quantity") == {
        "opening_quantity", "received_quantity", "closing_quantity",
    }


# --- check_reconciliation (R1) --------------------------------------------------


def test_check_reconciliation_passes_within_tolerance():
    # Real doc6.jpg row (COSKLOT-PLUS TAB, plan section 1.2 finding 5): 55 + 120 - 81 = 94.
    values = {"opening_quantity": 55, "received_quantity": 120, "sales_quantity": 81, "closing_quantity": 94}
    result = check_reconciliation(values, "opening_quantity + received_quantity - sales_quantity = closing_quantity", tolerance_abs=0)
    assert result is not None
    assert result.rule_id == RuleId.r1_reconciliation
    assert result.passed is True
    assert result.delta == 0


def test_check_reconciliation_fails_outside_tolerance():
    values = {"opening_quantity": 55, "received_quantity": 120, "sales_quantity": 81, "closing_quantity": 999}
    result = check_reconciliation(values, "opening_quantity + received_quantity - sales_quantity = closing_quantity", tolerance_abs=0)
    assert result is not None
    assert result.passed is False
    assert result.delta == pytest.approx(94 - 999)


def test_check_reconciliation_returns_none_when_a_field_is_missing():
    # CLAUDE.md's null-vs-zero discipline: a genuinely unresolved field
    # must never be silently treated as 0 to force a check through.
    values = {"opening_quantity": 55, "received_quantity": None, "sales_quantity": 81, "closing_quantity": 94}
    result = check_reconciliation(values, "opening_quantity + received_quantity - sales_quantity = closing_quantity", tolerance_abs=0)
    assert result is None


def test_check_reconciliation_returns_none_when_a_field_is_entirely_absent():
    values = {"opening_quantity": 55, "sales_quantity": 81, "closing_quantity": 94}  # no received_quantity key at all
    result = check_reconciliation(values, "opening_quantity + received_quantity - sales_quantity = closing_quantity", tolerance_abs=0)
    assert result is None


def test_check_reconciliation_nabin_family_formula():
    # Real doc2.jpg row (plan section 1.2 finding 5): 85 + 0 - 15 - 0 + 0 - 25 = 45.
    values = {
        "opening_quantity": 85, "received_quantity": 0, "free_received_quantity": 0,
        "sales_quantity": 15, "free_sales_quantity": 0, "sales_return_quantity": 0,
        "purchase_return_quantity": 0, "expired_quantity": 25, "closing_quantity": 45,
    }
    formula = (
        "opening_quantity + received_quantity + free_received_quantity "
        "- sales_quantity - free_sales_quantity - sales_return_quantity "
        "+ purchase_return_quantity - expired_quantity = closing_quantity"
    )
    result = check_reconciliation(values, formula, tolerance_abs=0)
    assert result is not None and result.passed is True


# --- check_rate_coherence (R4) --------------------------------------------------


def test_check_rate_coherence_exact_match_passes():
    # Real doc6.jpg row1: 16 * 408.86 = 6541.76 exact (plan finding #4).
    result = check_rate_coherence(quantity=16, rate=408.86, value=6541.76, tolerance_pct=0.5, label="opening")
    assert result is not None
    assert result.rule_id == RuleId.r4_rate_coherence
    assert result.passed is True


def test_check_rate_coherence_within_rounding_tolerance_passes():
    # Real doc6.jpg row2: 72 * 250.47 = 18033.84 vs printed 18034.08 (~0.001%, plan finding #4).
    result = check_rate_coherence(quantity=72, rate=250.47, value=18034.08, tolerance_pct=0.5, label="opening")
    assert result is not None
    assert result.passed is True


def test_check_rate_coherence_fails_outside_tolerance():
    result = check_rate_coherence(quantity=16, rate=408.86, value=99999.0, tolerance_pct=0.5, label="opening")
    assert result is not None
    assert result.passed is False


def test_check_rate_coherence_returns_none_when_rate_missing():
    assert check_rate_coherence(quantity=16, rate=None, value=6541.76, tolerance_pct=0.5, label="opening") is None


def test_check_rate_coherence_zero_value_uses_hard_equality():
    assert check_rate_coherence(quantity=0, rate=408.86, value=0, tolerance_pct=0.5, label="opening").passed is True
    assert check_rate_coherence(quantity=1, rate=408.86, value=0, tolerance_pct=0.5, label="opening").passed is False
