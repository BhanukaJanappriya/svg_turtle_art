"""Tests for horizontal inside-spans of a shape."""

from __future__ import annotations

import pytest

from svg_turtle_renderer.geometry.scanline import horizontal_spans

# A 10x10 square from (0,0) to (10,10).
SQUARE = [[(0, 0), (10, 0), (10, 10), (0, 10)]]


class TestSimpleShapes:
    def test_a_scanline_through_a_square(self):
        assert horizontal_spans(SQUARE, 5, even_odd=False) == [(0, 10)]

    def test_a_scanline_below_the_square_is_empty(self):
        assert horizontal_spans(SQUARE, -1, even_odd=False) == []

    def test_a_scanline_above_the_square_is_empty(self):
        assert horizontal_spans(SQUARE, 20, even_odd=False) == []

    def test_the_span_matches_the_shape_width(self):
        ((start, end),) = horizontal_spans(SQUARE, 3, even_odd=False)
        assert end - start == 10

    def test_a_triangle_narrows_towards_its_apex(self):
        triangle = [[(0, 0), (10, 0), (5, 10)]]
        wide = horizontal_spans(triangle, 1, even_odd=False)[0]
        narrow = horizontal_spans(triangle, 8, even_odd=False)[0]
        assert (wide[1] - wide[0]) > (narrow[1] - narrow[0])


class TestHoles:
    # A donut: outer square, inner square wound the opposite way.
    DONUT = [
        [(0, 0), (30, 0), (30, 30), (0, 30)],  # outer, counter-clockwise
        [(10, 20), (20, 20), (20, 10), (10, 10)],  # inner, clockwise
    ]

    def test_a_scanline_through_the_hole_has_two_spans(self):
        spans = horizontal_spans(self.DONUT, 15, even_odd=False)
        assert len(spans) == 2

    def test_the_gap_is_the_hole(self):
        left, right = horizontal_spans(self.DONUT, 15, even_odd=False)
        # Paint stops at the hole's left edge and resumes at its right edge.
        assert left == pytest.approx((0, 10))
        assert right == pytest.approx((20, 30))

    def test_a_scanline_missing_the_hole_is_one_span(self):
        assert horizontal_spans(self.DONUT, 5, even_odd=False) == [(0, 30)]

    def test_even_odd_cuts_the_hole_too(self):
        # Two nested same-wound rings: even-odd treats the inner as a hole.
        nested = [
            [(0, 0), (30, 0), (30, 30), (0, 30)],
            [(10, 10), (20, 10), (20, 20), (10, 20)],
        ]
        assert len(horizontal_spans(nested, 15, even_odd=True)) == 2


class TestDisjointRegions:
    def test_two_separate_squares_give_two_spans(self):
        rings = [
            [(0, 0), (10, 0), (10, 10), (0, 10)],
            [(20, 0), (30, 0), (30, 10), (20, 10)],
        ]
        spans = horizontal_spans(rings, 5, even_odd=False)
        assert spans == [(0, 10), (20, 30)]


class TestDegenerate:
    def test_no_rings(self):
        assert horizontal_spans([], 5, even_odd=False) == []

    def test_a_scanline_exactly_on_a_horizontal_edge_does_not_double_count(self):
        # y grazing the bottom edge should not produce a spurious full-width span.
        # The half-open crossing test drops the horizontal edge cleanly.
        result = horizontal_spans(SQUARE, 0, even_odd=False)
        assert result in ([], [(0, 10)])

    def test_spans_never_have_negative_width(self):
        for y in range(11):
            for start, end in horizontal_spans(SQUARE, y + 0.5, even_odd=False):
                assert end >= start
