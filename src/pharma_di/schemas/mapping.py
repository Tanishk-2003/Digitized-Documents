"""Stage boundary: semantic mapping output.

Populated by the P5 mapping stage. This module also defines the
SemanticResolver seam described in IMPLEMENTATION_PLAN.md section 0: the MVP
ships DictionaryResolver + ReviewQueueResolver; a LocalLlmResolver can be
added later that implements the same Protocol, so no call site changes.
"""
from __future__ import annotations

from enum import Enum
from typing import Protocol

from pydantic import BaseModel, Field, model_validator

from pharma_di.schemas.layout import HeaderNode


class MappingStatus(str, Enum):
    exact = "exact"                # tier 2: exact normalized-path/alias match
    normalized = "normalized"      # tier 3: abbreviation-expanded match
    fuzzy = "fuzzy"                # tier 4: rapidfuzz match >= accept threshold
    fuzzy_low_confidence = "fuzzy_low_confidence"  # accepted but forces review
    template_cache = "template_cache"  # tier 1: header fingerprint hit
    unresolved = "unresolved"      # no column is ever guessed onto a field


class MappingDecision(BaseModel):
    """The resolver's verdict for one source header."""

    source_header: HeaderNode
    canonical_field: str | None = None   # None iff status == unresolved
    status: MappingStatus
    match_score: float | None = Field(default=None, ge=0.0, le=100.0)
    combine: str | None = None           # "sum" for many-to-one fields (e.g. sales_return_quantity)

    @model_validator(mode="after")
    def _unresolved_never_carries_a_field(self) -> "MappingDecision":
        # Section 0 invariant: "No column is ever guessed." Enforced structurally,
        # not just by convention — an unresolved column literally cannot carry a
        # canonical_field, and a resolved one cannot be missing one.
        if self.status == MappingStatus.unresolved and self.canonical_field is not None:
            raise ValueError("status=unresolved must not carry a canonical_field (that would be a guess)")
        if self.status != MappingStatus.unresolved and self.canonical_field is None:
            raise ValueError(f"status={self.status} requires a canonical_field")
        return self


class ColumnMapping(BaseModel):
    """All resolved (and unresolved) columns for one table."""

    decisions: list[MappingDecision] = Field(default_factory=list)

    @property
    def unmapped_columns(self) -> list[HeaderNode]:
        return [d.source_header for d in self.decisions if d.status == MappingStatus.unresolved]

    @property
    def resolved_fraction(self) -> float:
        if not self.decisions:
            return 1.0
        resolved = sum(1 for d in self.decisions if d.status != MappingStatus.unresolved)
        return resolved / len(self.decisions)


class TableContext(BaseModel):
    """Context passed to a resolver alongside the header being resolved —
    e.g. the distributor/template already detected, so resolution can prefer
    a cached template fingerprint over fuzzy matching from scratch."""

    distributor_id: str | None = None
    template_family: str | None = None
    fingerprint: str | None = None


class SemanticResolver(Protocol):
    """The seam. DictionaryResolver and ReviewQueueResolver implement this in
    the no-LLM MVP; LocalLlmResolver implements it post-MVP. Every
    implementation has this exact signature."""

    def resolve(self, header: HeaderNode, ctx: TableContext) -> MappingDecision: ...
