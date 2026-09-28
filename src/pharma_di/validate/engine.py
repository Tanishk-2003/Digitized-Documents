"""Ties R1-R7 together into one row-by-row validation pass
(IMPLEMENTATION_PLAN.md section 4.7) — the single function
graph/nodes.py::validate calls, so the node itself stays a thin adapter over
PipelineState, consistent with how every other real-logic node in this
project delegates to its own dedicated module.

R2 (totals cross-foot) is computed once per document (it's inherently
whole-table, not per-row — see validate/totals.py's own docstring) and the
same RuleResult(s) are attached to every row; R1/R3/R4/R5/R6/R7 are each
computed fresh per row.

R7's "no uncertain row assignment" sub-check is deliberately not wired up
yet: it would need the original TableGrid row_index threaded through
assemble/canonical.py's return value (currently lost once a row becomes a
CanonicalRow), which is a real, contained follow-up, not implemented here
to avoid invasive, risky changes to already-tested P6 code under this
phase's time budget — see IMPLEMENTATION_PLAN.md's P7 build notes.
"""
from __future__ import annotations

from typing import Any

from pharma_di.assemble.canonical import LEVEL3_CANONICAL_FIELDS
from pharma_di.schemas.canonical import CanonicalRow, ReviewStatus
from pharma_di.schemas.layout import Region, RegionType, TableGrid
from pharma_di.schemas.mapping import ColumnMapping
from pharma_di.schemas.ocr import OcrToken
from pharma_di.schemas.validation import FieldConfidence, ReviewReason, RowValidationResult, RuleResult
from pharma_di.validate import confidence as confidence_module
from pharma_di.validate import derived as derived_module
from pharma_di.validate import reconcile as reconcile_module
from pharma_di.validate import rules as rules_module
from pharma_di.validate import totals as totals_module

# Derived from assemble/canonical.py's own LEVEL3_CANONICAL_FIELDS (P14 —
# see validate/rules.py::_SIGNED_FIELDS's own comment for why this used to
# be a second, independently hand-maintained copy of the same list).
_LEVEL3_FIELD_NAMES = [f for f in LEVEL3_CANONICAL_FIELDS if f != "stock_status"]
# R4 checks ONLY the opening pair, not all four qty/value pairs — checked
# against real doc6.jpg data before shipping, not assumed: CLAUDE.md's own
# finding #4 hand-verifies rate coherence exclusively on opening-stock
# examples ("16 x 408.86 = 6541.76", "72 x 250.47 = 18033.84 vs printed
# 18034.08"), and running all four pairs against every real row confirmed
# why — opening_quantity * rate matches opening_value on all 14/14 real
# rows, while the "sales" (ISSUE) pair fails on 9 of them, sometimes by a
# large margin (e.g. 3 * 250.47 = 751.41 vs a printed 925.04). That's not
# an extraction bug (the same row's opening pair reconciles exactly from
# the same rate) — it's evidence that ISSUE's value isn't simply
# quantity * rate, which connects directly to CLAUDE.md's own open
# decision D1 ("Map ISSUE {QTY, VALUE} to sales_quantity/sales_value? ...
# sales vs. transfer-out matters downstream" — a transfer-out or a
# different valuation basis wouldn't be expected to price at the same
# rate as opening stock). Checking pairs the real data doesn't support
# would manufacture false failures on otherwise-correct rows.
_RATE_PAIRS = [
    ("opening_quantity", "opening_value", "opening"),
]


def _row_values(row: CanonicalRow) -> dict[str, float | None]:
    return {field: getattr(row, field) for field in _LEVEL3_FIELD_NAMES}


def _lookup_template_family(distributor_id: str | None, distributors_cfg: dict[str, Any]) -> str | None:
    if not distributor_id:
        return None
    for d in distributors_cfg.get("distributors", []):
        if d.get("distributor_id") == distributor_id:
            return d.get("template_family")
    return None


def _compute_r2(
    grid: TableGrid | None,
    column_mapping: ColumnMapping | None,
    page_tokens: list[OcrToken],
    regions: list[Region],
    canonical_rows: list[CanonicalRow],
    totals_tolerance_abs: float,
) -> list[RuleResult]:
    if grid is None or column_mapping is None:
        return []
    totals_regions = [r for r in regions if r.region_type == RegionType.totals]
    if not totals_regions:
        return []
    printed_totals = totals_module.extract_totals_row(page_tokens, totals_regions[0], grid.columns, column_mapping)
    if not printed_totals:
        return []
    rows_values = [_row_values(r) for r in canonical_rows]
    column_sums: dict[str, float] = {}
    for field in printed_totals:
        total = totals_module.sum_canonical_field(rows_values, field)
        if total is not None:
            column_sums[field] = total
    return totals_module.check_totals_crossfoot(printed_totals, column_sums, totals_tolerance_abs)


def validate_document(
    document_id: str,
    canonical_rows: list[CanonicalRow],
    grid: TableGrid | None,
    column_mapping: ColumnMapping | None,
    page_tokens: list[OcrToken],
    regions: list[Region],
    page_quality_ok: bool | None,
    distributor_id: str | None,
    distributors_cfg: dict[str, Any],
    validation_rules_cfg: dict[str, Any],
    rate_tolerance_pct: float,
    totals_tolerance_abs: float,
    min_field_confidence: float,
    derived_received_aliases: list[str] | None = None,
    derived_sold_aliases: list[str] | None = None,
) -> tuple[list[RowValidationResult], list[CanonicalRow]]:
    """Returns (validation_results, updated_canonical_rows) — the rows come
    back with review_status/review_reasons set from the rule outcomes
    (auto_accepted only when every applicable rule passed, per section 4.7:
    "review_status = auto_accepted only when every applicable rule passes.
    Any failure produces needs_review with a machine-readable reason;
    nothing is ever dropped").

    `derived_received_aliases`/`derived_sold_aliases` (P12) default to
    validate/derived.py's own table when omitted — the real pipeline
    (graph/nodes.py::validate) passes config/column_mappings.yaml's
    derived_check_only.received_sold_groups instead, same config-driven
    reasoning as mapping/resolver.py's thresholds/abbreviations."""
    if not canonical_rows:
        return [], []

    family = _lookup_template_family(distributor_id, distributors_cfg)
    family_cfg = validation_rules_cfg.get("families", {}).get(family) if family else None
    header_mismatch = grid.header_column_count_mismatch if grid else False
    r2_results = _compute_r2(grid, column_mapping, page_tokens, regions, canonical_rows, totals_tolerance_abs)

    results: list[RowValidationResult] = []
    updated_rows: list[CanonicalRow] = []

    for row_index, row in enumerate(canonical_rows):
        values = _row_values(row)
        rule_results: list[RuleResult] = list(r2_results)

        if family_cfg:
            r1 = reconcile_module.check_reconciliation(
                values, family_cfg["reconciliation"]["formula"], family_cfg["reconciliation"].get("tolerance_abs", 0)
            )
            if r1 is not None:
                rule_results.append(r1)

        rule_results.extend(
            derived_module.check_derived_columns(
                row.source_field_breakdown.get("derived_check_only", {}),
                values,
                received_aliases=derived_received_aliases,
                sold_aliases=derived_sold_aliases,
            )
        )

        if row.rate is not None:
            for qty_field, value_field, label in _RATE_PAIRS:
                r4 = reconcile_module.check_rate_coherence(
                    values.get(qty_field), row.rate, values.get(value_field), rate_tolerance_pct, label
                )
                if r4 is not None:
                    rule_results.append(r4)

        rule_results.append(rules_module.check_sign_plausibility(values))
        rule_results.append(confidence_module.check_confidence_gate(row.extraction_confidence, min_field_confidence))
        rule_results.append(rules_module.check_page_integrity(page_quality_ok, header_mismatch, row_has_uncertain_cells=False))

        review_reasons = [
            ReviewReason(code=r.rule_id.value.lower(), message=r.detail, rule_id=r.rule_id)
            for r in rule_results
            if not r.passed
        ]
        field_confidences = [FieldConfidence(field_name=f, confidence=c) for f, c in row.extraction_confidence.items()]

        result = RowValidationResult(
            document_id=document_id,
            row_index=row_index,
            rule_results=rule_results,
            field_confidences=field_confidences,
            review_reasons=review_reasons,
        )
        results.append(result)

        new_status = ReviewStatus.auto_accepted if result.all_rules_passed else ReviewStatus.needs_review
        # UI-UX-Implementation.md Phase A.2: keep the structured ReviewReason
        # objects (code/message/rule_id) instead of flattening to `.message`
        # strings — CanonicalRow.review_reasons is list[ReviewReason] now, so
        # a UI can render its own label per rule_id instead of parsing text.
        updated_rows.append(
            row.model_copy(update={"review_status": new_status, "review_reasons": review_reasons})
        )

    return results, updated_rows
