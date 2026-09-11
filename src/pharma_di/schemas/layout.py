"""Stage boundary: layout analysis output.

Populated by the P3 layout stage. This is where the plan's two hardest design
problems live (IMPLEMENTATION_PLAN.md sections 4.3-4.5):
  - borderless column-band inference (RegionType.stock_table on doc1/doc4/doc5/doc6)
  - sloped-baseline row assembly (page curvature)
  - hierarchical header reconstruction (OPENING -> {QTY., VALUE})

These schemas exist now (P0) so every later stage can be written against a
stable contract; the inference logic itself is P3, not P0.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from pharma_di.schemas.ocr import BBox, OcrToken


class RegionType(str, Enum):
    """A page is not guaranteed to be a single table (CLAUDE.md) — a region
    typer classifies each detected region before anything is treated as the
    Stock & Sale grid."""

    page_header = "page_header"
    statement_meta = "statement_meta"
    stock_table = "stock_table"
    purchase_detail = "purchase_detail"
    totals = "totals"
    page_footer = "page_footer"
    unknown = "unknown"


class Region(BaseModel):
    region_type: RegionType
    bbox: BBox
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)


class HeaderNode(BaseModel):
    """One leaf (or parent) of a possibly-hierarchical header, e.g.
    path=["OPENING", "QTY."] for a sub-column under a spanning header."""

    path: list[str]
    bbox: BBox
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)

    @property
    def normalized_key(self) -> str:
        return "|".join(p.strip().lower() for p in self.path)


class ColumnBand(BaseModel):
    """An inferred column's x-extent in a borderless table, plus which
    inference signals agreed (section 4.3). `geometry_uncertain=True` routes
    the table to review rather than silently picking a boundary."""

    header: HeaderNode
    x0: float
    x1: float
    geometry_uncertain: bool = False


class Cell(BaseModel):
    row_index: int
    column: HeaderNode
    tokens: list[OcrToken] = Field(default_factory=list)
    row_assignment_uncertain: bool = False

    @property
    def text(self) -> str:
        return " ".join(t.text for t in self.tokens).strip()

    @property
    def min_confidence(self) -> float | None:
        if not self.tokens:
            return None
        return min(t.confidence for t in self.tokens)


class TableGrid(BaseModel):
    """A fully-assembled table: reconciled column bands, hierarchical headers,
    and row-assigned cells. This is the direct input to semantic mapping (P5)."""

    region: Region
    columns: list[ColumnBand] = Field(default_factory=list)
    row_count: int = 0
    cells: list[Cell] = Field(default_factory=list)
    header_column_count_mismatch: bool = False  # hard invariant, section 4.3
    # A row whose only tokens fall in the leftmost column (a company/section
    # name spanning the row, e.g. "ZORVIA HEALTHCARE LTD." inside a MARG
    # table body — plan finding #10) — keyed by row_index, value is the
    # label text. P6 uses this to update company_name instead of emitting
    # an empty product row for it.
    section_label_rows: dict[int, str] = Field(default_factory=dict)

    def cells_for_row(self, row_index: int) -> list[Cell]:
        return [c for c in self.cells if c.row_index == row_index]


class LayoutResult(BaseModel):
    source_file: str
    page_number: int = Field(ge=1)
    regions: list[Region] = Field(default_factory=list)
    tables: list[TableGrid] = Field(default_factory=list)
