"""Stage boundary: validation engine output (P7).

Rules R1-R7 from IMPLEMENTATION_PLAN.md section 4.7. All deterministic
arithmetic/plausibility checks — no LLM involvement anywhere in this module,
consistent with CLAUDE.md's "Validation engine: deterministic checks, not
LLM-based". Results are data (persisted rows), never just a log line —
checklist: "Confidence scores ... and validation failures are first-class
data, not debug output."
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class RuleId(str, Enum):
    r1_reconciliation = "R1_reconciliation"
    r2_totals_crossfoot = "R2_totals_crossfoot"
    r3_derived_columns = "R3_derived_columns"
    r4_rate_coherence = "R4_rate_coherence"
    r5_sign_plausibility = "R5_sign_plausibility"
    r6_confidence_gate = "R6_confidence_gate"
    r7_page_integrity = "R7_page_integrity"


class RuleResult(BaseModel):
    rule_id: RuleId
    passed: bool
    detail: str = ""
    expected: float | None = None
    actual: float | None = None
    delta: float | None = None


class FieldConfidence(BaseModel):
    """Per-field confidence, not just per-row (checklist)."""

    field_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = "ocr"  # "ocr" | "mapping" | "reconciliation" | "product_match"


class ReviewReason(BaseModel):
    code: str            # machine-readable, e.g. "reconciliation_mismatch", "unmapped_column"
    message: str
    rule_id: RuleId | None = None


class RowValidationResult(BaseModel):
    """All rule outcomes for one CanonicalRow, and the derived review verdict."""

    document_id: str
    row_index: int
    rule_results: list[RuleResult] = Field(default_factory=list)
    field_confidences: list[FieldConfidence] = Field(default_factory=list)
    review_reasons: list[ReviewReason] = Field(default_factory=list)

    @property
    def all_rules_passed(self) -> bool:
        return all(r.passed for r in self.rule_results)
