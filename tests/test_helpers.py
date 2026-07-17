"""Tests for the shared helpers."""

from __future__ import annotations

import math

import pytest

from svg_turtle_renderer.utils.helpers import (
    douglas_peucker,
    format_duration,
    parse_length,
    parse_points,
    parse_style_attribute,
    strip_namespace,
    unique_preserving_order,
)


class TestParseLength:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [("10", 10.0), ("10px", 10.0), ("-5", -5.0), ("2.5", 2.5), ("1e2", 100.0)],
    )
    def test_plain_numbers(self, text, expected):
        assert parse_length(text) == pytest.approx(expected)

    @pytest.mark.parametrize(
        ("text", "expected"),
        [("1in", 96.0), ("1cm", 96 / 2.54), ("1mm", 96 / 25.4), ("12pt", 16.0), ("1pc", 16.0)],
    )
    def test_absolute_units_convert_to_css_pixels(self, text, expected):
        assert parse_length(text) == pytest.approx(expected)

    def test_units_are_case_insensitive(self):
        assert parse_length("1IN") == pytest.approx(96.0)

    def test_whitespace_is_tolerated(self):
        assert parse_length("  10  ") == 10.0

    def test_percentage_needs_a_reference(self):
        assert parse_length("50%", percent_of=200) == 100.0

    def test_a_percentage_without_a_reference_falls_back(self):
        # Guessing a viewport would silently misplace geometry.
        assert parse_length("50%", default=7.0) == 7.0

    def test_font_relative_units_degrade_to_user_units(self):
        assert parse_length("2em") == 2.0

    def test_missing_and_malformed_values_use_the_default(self):
        assert parse_length(None, 3.0) == 3.0
        assert parse_length("wide", 3.0) == 3.0
        assert parse_length("", 3.0) == 3.0


class TestParsePoints:
    def test_comma_separated(self):
        assert parse_points("0,0 10,10") == [(0, 0), (10, 10)]

    def test_space_separated(self):
        assert parse_points("0 0 10 10") == [(0, 0), (10, 10)]

    def test_mixed_separators(self):
        assert parse_points("0,0, 10 10,20,20") == [(0, 0), (10, 10), (20, 20)]

    def test_negative_and_decimal_values(self):
        assert parse_points("-1.5,-2.5 3,4") == [(-1.5, -2.5), (3, 4)]

    def test_an_unpaired_trailing_value_is_dropped(self):
        assert parse_points("0,0 10,10 20") == [(0, 0), (10, 10)]

    def test_empty_input(self):
        assert parse_points(None) == []
        assert parse_points("") == []


class TestParseStyleAttribute:
    def test_single_declaration(self):
        assert parse_style_attribute("fill: red") == {"fill": "red"}

    def test_multiple_declarations(self):
        assert parse_style_attribute("fill:red;stroke:blue") == {"fill": "red", "stroke": "blue"}

    def test_whitespace_and_trailing_semicolons(self):
        assert parse_style_attribute("  fill : red ;  ") == {"fill": "red"}

    def test_property_names_are_lowercased(self):
        assert parse_style_attribute("FILL: red") == {"fill": "red"}

    def test_malformed_declarations_are_skipped(self):
        assert parse_style_attribute("fill red; stroke: blue") == {"stroke": "blue"}

    def test_empty_input(self):
        assert parse_style_attribute(None) == {}
        assert parse_style_attribute("") == {}


class TestDouglasPeucker:
    def test_collinear_points_collapse_to_the_endpoints(self):
        points = [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)]
        assert douglas_peucker(points, 0.1) == [(0, 0), (4, 0)]

    def test_a_significant_deviation_is_kept(self):
        points = [(0, 0), (2, 5), (4, 0)]
        assert douglas_peucker(points, 0.1) == points

    def test_a_deviation_below_tolerance_is_dropped(self):
        points = [(0, 0), (2, 0.05), (4, 0)]
        assert douglas_peucker(points, 0.1) == [(0, 0), (4, 0)]

    def test_endpoints_always_survive(self):
        points = [(0, 0), (1, 0.01), (2, 0.01), (3, 0)]
        result = douglas_peucker(points, 100.0)
        assert result[0] == (0, 0)
        assert result[-1] == (3, 0)

    def test_zero_tolerance_changes_nothing(self):
        points = [(0, 0), (1, 0), (2, 0)]
        assert douglas_peucker(points, 0.0) == points

    def test_short_inputs_pass_through(self):
        assert douglas_peucker([], 1.0) == []
        assert douglas_peucker([(0, 0)], 1.0) == [(0, 0)]
        assert douglas_peucker([(0, 0), (1, 1)], 1.0) == [(0, 0), (1, 1)]

    def test_every_dropped_point_stays_within_tolerance(self):
        points = [(i, math.sin(i / 5) * 10) for i in range(200)]
        tolerance = 0.5
        simplified = douglas_peucker(points, tolerance)
        assert len(simplified) < len(points)

        def distance_to_polyline(p):
            best = float("inf")
            for a, b in zip(simplified, simplified[1:], strict=False):
                dx, dy = b[0] - a[0], b[1] - a[1]
                length_squared = dx * dx + dy * dy
                t = 0.0
                if length_squared:
                    t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length_squared))
                best = min(best, math.dist(p, (a[0] + t * dx, a[1] + t * dy)))
            return best

        for point in points:
            assert distance_to_polyline(point) <= tolerance

    def test_a_deeply_splitting_polyline_does_not_exhaust_the_stack(self):
        # A convex, monotonically decaying curve is the worst case for recursion
        # depth: the farthest point is always next to the start, so each split
        # peels off a single vertex and the depth grows with the input rather
        # than with its logarithm. At 2000 points a recursive implementation
        # would blow Python's default 1000-frame limit; the iterative one copes.
        points = [(float(i), 1.0 / (i + 1)) for i in range(2000)]
        result = douglas_peucker(points, 1e-9)
        assert len(result) > 1000
        assert result[0] == points[0]
        assert result[-1] == points[-1]


class TestMiscellaneous:
    def test_strip_namespace(self):
        assert strip_namespace("{http://www.w3.org/2000/svg}rect") == "rect"

    def test_strip_namespace_leaves_bare_tags_alone(self):
        assert strip_namespace("rect") == "rect"

    @pytest.mark.parametrize(
        ("seconds", "expected"), [(0.5, "500 ms"), (1.5, "1.50 s"), (90.0, "1m 30.0s")]
    )
    def test_format_duration(self, seconds, expected):
        assert format_duration(seconds) == expected

    def test_unique_preserving_order(self):
        assert unique_preserving_order([3, 1, 3, 2, 1]) == [3, 1, 2]
