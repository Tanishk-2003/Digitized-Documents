"""R1 (reconciliation) + a small, safe arithmetic evaluator it's built on
(IMPLEMENTATION_PLAN.md section 4.7).

Formulas live in config/validation_rules.yaml as plain arithmetic strings,
keyed by `template_family` — "this is why the formula lives in config, not
in a per-distributor code branch" (the config file's own comment). Honoring
that design means evaluating an arbitrary string from config, which is
exactly the situation `eval()` should never be used for, even for a
trusted, local, non-attacker-controlled file — arbitrary code execution has
no legitimate role in comparing two sums. `eval_formula` below parses with
Python's own `ast` module and walks a small, explicit allow-list of node
types (Name, BinOp/UnaryOp for + - * /, numeric Constant) — anything else
raises rather than silently doing something unintended.
"""
from __future__ import annotations

import ast
import operator

from pharma_di.schemas.validation import RuleId, RuleResult

_ALLOWED_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_ALLOWED_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _eval_node(node: ast.AST, values: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, values)
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        return _ALLOWED_BINOPS[type(node.op)](_eval_node(node.left, values), _eval_node(node.right, values))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARYOPS:
        return _ALLOWED_UNARYOPS[type(node.op)](_eval_node(node.operand, values))
    if isinstance(node, ast.Name):
        if node.id not in values:
            raise KeyError(node.id)
        return values[node.id]
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    raise ValueError(f"unsupported expression node in validation formula: {ast.dump(node)}")


def eval_formula(expr: str, values: dict[str, float]) -> float:
    """Safely evaluate a plain arithmetic expression (names, + - * /, unary
    -, numeric literals) against `values`. Raises KeyError for any
    referenced name not in `values` — callers should treat that as "rule
    not applicable" (a missing field), not a formula bug; raises ValueError
    for anything outside the allowed grammar (function calls, attribute
    access, comparisons, ...)."""
    tree = ast.parse(expr, mode="eval")
    return _eval_node(tree, values)


def referenced_names(expr: str) -> set[str]:
    tree = ast.parse(expr, mode="eval")
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def check_reconciliation(
    values: dict[str, float | None], formula: str, tolerance_abs: float
) -> RuleResult | None:
    """R1: split `formula` on its one top-level '=' into (lhs, rhs),
    evaluate both sides, and compare within tolerance_abs.

    Returns None (rule not applicable to this row) rather than a failing
    RuleResult when any referenced field is missing (None or absent) —
    CLAUDE.md's null-vs-zero discipline applies to validation too: a field
    that was never extracted must never be silently treated as zero just
    to force a reconciliation check through.
    """
    lhs_expr, rhs_expr = (s.strip() for s in formula.split("=", 1))
    needed = referenced_names(lhs_expr) | referenced_names(rhs_expr)
    if any(values.get(name) is None for name in needed):
        return None

    numeric_values = {k: v for k, v in values.items() if v is not None}
    lhs = eval_formula(lhs_expr, numeric_values)
    rhs = eval_formula(rhs_expr, numeric_values)
    delta = lhs - rhs
    passed = abs(delta) <= tolerance_abs
    return RuleResult(
        rule_id=RuleId.r1_reconciliation,
        passed=passed,
        expected=rhs,
        actual=lhs,
        delta=delta,
        detail=f"{lhs_expr} = {lhs:g}; {rhs_expr} = {rhs:g}",
    )


def check_rate_coherence(
    quantity: float | None, rate: float | None, value: float | None, tolerance_pct: float, label: str
) -> RuleResult | None:
    """R4: `abs(quantity * rate - value) <= tolerance_pct% of value`.

    Implemented directly rather than parsed from
    config/validation_rules.yaml's `rate_coherence.formula` string: that
    formula (documentation of intent, kept in config for the same
    "verified against real data" traceability every other rule has) uses
    `abs()` and a `<=` comparison, both outside the small, deliberately
    restrictive grammar `eval_formula` accepts — extending that general
    evaluator just to parse one fixed, universal (not per-family) check
    would add real evaluator complexity for a check that's the same
    every time, rather than genuinely config-varying like R1's formulas.

    Returns None (not applicable) when quantity, rate, or value is missing
    — never guesses a coherence result from partial data — or when `value`
    is exactly 0 (a percentage-of-value tolerance is undefined at zero;
    that specific case still gets a hard equality check instead, since
    "qty * rate should be ~0 too" is well-defined even when the percentage
    form isn't).
    """
    if quantity is None or rate is None or value is None:
        return None

    expected = quantity * rate
    delta = expected - value
    if value == 0:
        passed = abs(delta) <= 1e-9
    else:
        passed = abs(delta) <= tolerance_pct * abs(value) / 100
    return RuleResult(
        rule_id=RuleId.r4_rate_coherence,
        passed=passed,
        expected=expected,
        actual=value,
        delta=delta,
        detail=f"{label}: {quantity:g} * {rate:g} = {expected:g} vs printed {value:g}",
    )
