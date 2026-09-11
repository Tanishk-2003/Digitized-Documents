"""The mapping dictionary (config/column_mappings.yaml) as a queryable
structure — IMPLEMENTATION_PLAN.md section 4.6. One FieldEntry per canonical
field, each carrying the hierarchical `paths` and flat `aliases` variants a
real source header might appear as, plus an optional `combine` mode for
many-to-one fields (e.g. sales_return_quantity sums three New Tripura
columns — section 4.6, `combine: sum`).

`derived_check_only` is included like any other entry, not filtered out: its
own comment in the config says its columns are "consumed by validation rule
R3 ... instead" of being written to a CanonicalRow field, but that's a
downstream (P7) consumption detail — at the mapping stage a "TOTAL RCVD."
column is just as real and resolvable as any other, and leaving it
excluded here would wrongly send it to unmapped_columns/needs_review.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FieldEntry:
    canonical_field: str
    paths: list[list[str]] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    combine: str | None = None


def load_field_entries(column_mappings_cfg: dict[str, Any]) -> list[FieldEntry]:
    return [
        FieldEntry(
            canonical_field=field_name,
            paths=spec.get("paths", []),
            aliases=spec.get("aliases", []),
            combine=spec.get("combine"),
        )
        for field_name, spec in column_mappings_cfg.items()
    ]
