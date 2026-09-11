"""R6 (confidence gate) — IMPLEMENTATION_PLAN.md section 4.7: "min per-field
OCR confidence >= threshold." Works directly off CanonicalRow's own
extraction_confidence dict (populated per-field by assemble/canonical.py
in P6, not recomputed here) — checklist: "Confidence scores (per field, not
just per row) ... are first-class data," so this rule is a straight
threshold check over data that already exists, not a new confidence
computation.
"""
from __future__ import annotations

from pharma_di.schemas.validation import RuleId, RuleResult


def check_confidence_gate(extraction_confidence: dict[str, float], min_confidence: float) -> RuleResult:
    """One RuleResult for the whole row: passes iff EVERY recorded field
    confidence clears `min_confidence`. A row with no recorded confidences
    at all (e.g. every field genuinely null) vacuously passes — there's
    nothing low-confidence to gate on, not evidence of anything wrong."""
    below_threshold = {field: conf for field, conf in extraction_confidence.items() if conf < min_confidence}
    passed = not below_threshold
    if passed:
        detail = "every field's confidence >= threshold" if extraction_confidence else "no fields with recorded confidence"
    else:
        worst_field = min(below_threshold, key=lambda f: below_threshold[f])
        detail = f"{len(below_threshold)} field(s) below {min_confidence:g}: worst is {worst_field} at {below_threshold[worst_field]:.2f}"
    return RuleResult(
        rule_id=RuleId.r6_confidence_gate,
        passed=passed,
        expected=min_confidence,
        actual=min(extraction_confidence.values()) if extraction_confidence else None,
        detail=detail,
    )
