"""P5 unit tests for mapping/breakdown.py — many-to-one column grouping
(IMPLEMENTATION_PLAN.md section 4.6)."""
from __future__ import annotations

from pharma_di.mapping.breakdown import group_combined_fields
from pharma_di.schemas.layout import BBox, HeaderNode
from pharma_di.schemas.mapping import ColumnMapping, MappingDecision, MappingStatus


def _header(path):
    return HeaderNode(path=path, bbox=BBox(x0=0, y0=0, x1=100, y1=20))


def _decision(path, field, combine=None, status=MappingStatus.exact):
    return MappingDecision(source_header=_header(path), canonical_field=field, status=status, combine=combine)


def test_group_combined_fields_groups_multiple_contributors():
    # New Tripura's real case (IMPLEMENTATION_PLAN.md section 4.6): three
    # source columns all feed sales_return_quantity.
    mapping = ColumnMapping(
        decisions=[
            _decision(["Market Return"], "sales_return_quantity", combine="sum"),
            _decision(["Return Outward"], "sales_return_quantity", combine="sum"),
            _decision(["Short Quantity"], "sales_return_quantity", combine="sum"),
            _decision(["Product"], "product_name_raw"),
        ]
    )
    grouped = group_combined_fields(mapping)
    assert set(grouped.keys()) == {"sales_return_quantity"}
    assert len(grouped["sales_return_quantity"]) == 3


def test_group_combined_fields_excludes_single_contributor():
    # A field marked combine=sum in the dictionary but with only ONE
    # matching column on THIS table isn't a real combination — nothing to
    # sum, and flagging it as one would misrepresent a plain 1:1 mapping.
    mapping = ColumnMapping(decisions=[_decision(["Sale Rtn"], "sales_return_quantity", combine="sum")])
    assert group_combined_fields(mapping) == {}


def test_group_combined_fields_ignores_non_combine_decisions():
    mapping = ColumnMapping(
        decisions=[
            _decision(["Opening", "Qty."], "opening_quantity"),
            _decision(["Opening", "Value"], "opening_value"),
        ]
    )
    assert group_combined_fields(mapping) == {}


def test_group_combined_fields_ignores_unresolved_decisions():
    mapping = ColumnMapping(
        decisions=[
            MappingDecision(source_header=_header(["Dump", "Qty"]), canonical_field=None, status=MappingStatus.unresolved),
        ]
    )
    assert group_combined_fields(mapping) == {}


def test_group_combined_fields_empty_mapping_returns_empty_dict():
    assert group_combined_fields(ColumnMapping(decisions=[])) == {}
