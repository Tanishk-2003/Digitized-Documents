"""R5 (sign/plausibility) + R7 (page integrity) — IMPLEMENTATION_PLAN.md
section 4.7."""
from __future__ import annotations

from pharma_di.schemas.validation import RuleId, RuleResult

# Every Level-3 numeric canonical field a sign check could apply to
# (assemble/canonical.py's own _LEVEL3_CANONICAL_FIELDS, minus stock_status
# which is a string, not a signed quantity).
_SIGNED_FIELDS = [
    "opening_quantity", "opening_value", "received_quantity", "received_value",
    "free_received_quantity", "sales_quantity", "sales_value", "free_sales_quantity",
    "sales_return_quantity", "purchase_return_quantity", "expired_quantity",
    "closing_quantity", "closing_value", "months_to_expiry",
]


def check_sign_plausibility(values: dict[str, float | None], negative_allowed_fields: frozenset[str] = frozenset()) -> RuleResult:
    """R5: every signed field present on the row must be >= 0, unless it's
    named in `negative_allowed_fields`.

    Nothing is in that set by default — CLAUDE.md's own open decision D4
    (doc5.jpg shows RECEIPT QTY = -1, "almost certainly a purchase return
    posted as a negative receipt... the plan does not guess") is
    deliberately left unresolved here too: until a human confirms that
    reading, a negative receipt correctly fails this rule and routes its
    row to review, which is the right outcome for a genuinely open
    question — not a bug to silently work around by exempting the field.
    """
    violations = {
        field: values[field]
        for field in _SIGNED_FIELDS
        if values.get(field) is not None and values[field] < 0 and field not in negative_allowed_fields
    }
    passed = not violations
    if passed:
        detail = "no negative values" if any(values.get(f) is not None for f in _SIGNED_FIELDS) else "no signed fields present"
    else:
        detail = "negative value(s): " + ", ".join(f"{f}={v:g}" for f, v in violations.items())
    return RuleResult(rule_id=RuleId.r5_sign_plausibility, passed=passed, detail=detail)


def check_page_integrity(
    page_quality_ok: bool | None, header_column_count_mismatch: bool, row_has_uncertain_cells: bool
) -> RuleResult:
    """R7: the quality gate passed, the header/column-count invariant held
    (enforced by construction in layout/columns.py — section 4.3 — so this
    is a defensive re-check, not the primary guarantee), and this specific
    row has no cells layout/rows.py flagged row_assignment_uncertain."""
    reasons = []
    if page_quality_ok is False:
        reasons.append("page failed the P1 quality gate")
    if page_quality_ok is None:
        reasons.append("page quality was never assessed")
    if header_column_count_mismatch:
        reasons.append("header leaf count did not match inferred column count")
    if row_has_uncertain_cells:
        reasons.append("row has at least one cell with an uncertain row assignment")

    passed = not reasons
    detail = "page and row integrity checks passed" if passed else "; ".join(reasons)
    return RuleResult(rule_id=RuleId.r7_page_integrity, passed=passed, detail=detail)
