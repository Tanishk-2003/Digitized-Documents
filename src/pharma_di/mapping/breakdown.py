"""Many-to-one column grouping (IMPLEMENTATION_PLAN.md section 4.6): a
`combine: sum` canonical field (e.g. sales_return_quantity, which New
Tripura's Market Return / Return Outward / Short Quantity all feed into) can
be resolved FROM more than one source column on the same table. This module
identifies that grouping from a table's own ColumnMapping; actually summing
the per-row values and writing source_field_breakdown is P6's job
(assemble_canonical) once real row values are in hand — this only answers
"which source headers feed which combined field," a mapping-stage question.
"""
from __future__ import annotations

from collections import defaultdict

from pharma_di.schemas.mapping import ColumnMapping, MappingDecision


def group_combined_fields(column_mapping: ColumnMapping) -> dict[str, list[MappingDecision]]:
    """canonical_field -> every MappingDecision that resolved to it AND
    whose field is configured `combine: sum`, for fields with 2+
    contributing columns on this table (a single contributor isn't a
    many-to-one split — nothing to combine, and flagging it as one would
    misrepresent a plain 1:1 mapping as a combination)."""
    by_field: dict[str, list[MappingDecision]] = defaultdict(list)
    for decision in column_mapping.decisions:
        if decision.combine == "sum" and decision.canonical_field is not None:
            by_field[decision.canonical_field].append(decision)
    return {field: decisions for field, decisions in by_field.items() if len(decisions) >= 2}
