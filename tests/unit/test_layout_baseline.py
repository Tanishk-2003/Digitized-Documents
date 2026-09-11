"""P3 unit tests for layout/baseline.py's shared line-clustering machinery."""
from __future__ import annotations

from pharma_di.layout.baseline import cluster_into_lines, theil_sen_slope
from pharma_di.schemas.ocr import BBox, OcrToken


def _tok(text, x0, y0, w=40, h=20, conf=0.95):
    return OcrToken(text=text, bbox=BBox(x0=x0, y0=y0, x1=x0 + w, y1=y0 + h), confidence=conf)


def test_theil_sen_recovers_a_known_slope():
    # y = 0.05x, sampled at several x
    points = [(x, 0.05 * x) for x in range(0, 500, 50)]
    assert abs(theil_sen_slope(points) - 0.05) < 1e-6


def test_theil_sen_max_abs_slope_excludes_steep_pairs():
    # one point pair implies a very steep "slope" (small dx, large dy) —
    # should be excluded when max_abs_slope is tight, changing the result.
    points = [(0, 0), (500, 25), (505, 100)]  # last pair: dy=75 over dx=5 -> slope=15
    unfiltered = theil_sen_slope(points)
    filtered = theil_sen_slope(points, max_abs_slope=0.5)
    assert filtered != unfiltered
    assert abs(filtered) <= 0.5


def test_cluster_into_lines_separates_distinct_rows():
    tokens = [_tok("A", 0, 0), _tok("B", 100, 2), _tok("C", 0, 40), _tok("D", 100, 42)]
    lines, slope = cluster_into_lines(tokens)
    assert len(lines) == 2
    assert {t.text for t in lines[0]} == {"A", "B"}
    assert {t.text for t in lines[1]} == {"C", "D"}


def test_cluster_into_lines_respects_explicit_slope_override():
    # Without an override, tokens spread across a slope would be
    # (mis)clustered per the auto-fit; passing slope=0.0 explicitly forces
    # a flat assumption regardless of what the data implies — this is what
    # layout/regions.py relies on (see its module docstring).
    tokens = [_tok("A", 0, 0), _tok("B", 500, 60)]  # implied slope 0.12
    lines_flat, slope_used = cluster_into_lines(tokens, slope=0.0)
    assert slope_used == 0.0
    # at slope=0 these are far apart in raw y (60px) -> 2 lines
    assert len(lines_flat) == 2


def test_lines_are_ordered_top_to_bottom():
    tokens = [_tok("bottom", 0, 100), _tok("top", 0, 0), _tok("middle", 0, 50)]
    lines, _slope = cluster_into_lines(tokens)
    first_texts = [line[0].text for line in lines]
    assert first_texts == ["top", "middle", "bottom"]


def test_tokens_within_a_line_are_ordered_left_to_right():
    tokens = [_tok("right", 200, 0), _tok("left", 0, 2), _tok("mid", 100, 1)]
    lines, _slope = cluster_into_lines(tokens)
    assert len(lines) == 1
    assert [t.text for t in lines[0]] == ["left", "mid", "right"]
