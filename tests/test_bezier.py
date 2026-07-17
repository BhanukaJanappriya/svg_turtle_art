"""Tests for curve flattening."""

from __future__ import annotations

import math

import pytest

from svg_turtle_renderer.geometry.bezier import flatten_arc, flatten_cubic, flatten_quadratic


def max_deviation_from_circle(points, cx, cy, radius):
    """Return the largest radial error of ``points`` against a circle."""
    return max(abs(math.dist((x, y), (cx, cy)) - radius) for x, y in points)


def distance_to_segment(point, start, end):
    """Return the distance from ``point`` to the segment ``start``-``end``."""
    px, py = point
    ax, ay = start
    bx, by = end
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    if length_squared == 0.0:
        return math.dist(point, start)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
    return math.dist(point, (ax + t * dx, ay + t * dy))


def distance_to_polyline(point, points):
    """Return the distance from ``point`` to the nearest segment of a polyline.

    Measuring against the segments, not the vertices, is the whole point: a
    flattened curve is the line *through* its vertices, and a well-placed vertex
    can be far from a given sample while the polyline passes right through it.
    """
    return min(distance_to_segment(point, a, b) for a, b in zip(points, points[1:], strict=False))


class TestCubic:
    def test_excludes_the_start_point(self):
        points = flatten_cubic((0, 0), (0, 10), (10, 10), (10, 0))
        assert (0, 0) not in points

    def test_ends_exactly_on_the_end_point(self):
        points = flatten_cubic((0, 0), (0, 10), (10, 10), (10, 0))
        assert points[-1] == (10, 0)

    def test_a_straight_cubic_needs_no_subdivision(self):
        # Control points on the chord: the curve is already a line.
        points = flatten_cubic((0, 0), (3, 0), (7, 0), (10, 0))
        assert points == [(10, 0)]

    def test_tighter_tolerance_produces_more_points(self):
        loose = flatten_cubic((0, 0), (0, 50), (50, 50), (50, 0), tolerance=5.0)
        tight = flatten_cubic((0, 0), (0, 50), (50, 50), (50, 0), tolerance=0.01)
        assert len(tight) > len(loose)

    def test_stays_within_tolerance_of_the_true_curve(self):
        p0, p1, p2, p3 = (0, 0), (0, 100), (100, 100), (100, 0)
        tolerance = 0.5
        points = [p0] + flatten_cubic(p0, p1, p2, p3, tolerance)

        # Sample the analytic curve and check each sample is near the polyline.
        def evaluate(t):
            u = 1 - t
            return (
                u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0],
                u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1],
            )

        for i in range(101):
            assert distance_to_polyline(evaluate(i / 100), points) <= tolerance

    def test_degenerate_curve_terminates(self):
        assert flatten_cubic((5, 5), (5, 5), (5, 5), (5, 5)) == [(5, 5)]


class TestQuadratic:
    def test_ends_on_the_end_point(self):
        assert flatten_quadratic((0, 0), (5, 10), (10, 0))[-1] == (10, 0)

    def test_matches_the_equivalent_elevated_cubic(self):
        p0, p1, p2 = (0.0, 0.0), (50.0, 100.0), (100.0, 0.0)
        c1 = (p0[0] + 2 / 3 * (p1[0] - p0[0]), p0[1] + 2 / 3 * (p1[1] - p0[1]))
        c2 = (p2[0] + 2 / 3 * (p1[0] - p2[0]), p2[1] + 2 / 3 * (p1[1] - p2[1]))
        assert flatten_quadratic(p0, p1, p2, 0.1) == flatten_cubic(p0, c1, c2, p2, 0.1)

    def test_midpoint_lies_on_the_true_curve(self):
        p0, p1, p2 = (0, 0), (50, 100), (100, 0)
        points = [p0] + flatten_quadratic(p0, p1, p2, 0.05)
        # The quadratic's t=0.5 point is (p0 + 2*p1 + p2) / 4 = (50, 50).
        assert distance_to_polyline((50, 50), points) < 0.05


class TestArc:
    def test_zero_length_arc_draws_nothing(self):
        assert flatten_arc((10, 10), 5, 5, 0, False, True, (10, 10)) == []

    def test_zero_radius_degrades_to_a_line(self):
        assert flatten_arc((0, 0), 0, 0, 0, False, True, (10, 10)) == [(10, 10)]

    def test_ends_exactly_on_the_commanded_endpoint(self):
        points = flatten_arc((0, 0), 50, 50, 0, False, True, (100, 0))
        assert points[-1] == (100, 0)

    def test_semicircle_lies_on_the_circle(self):
        # A half circle from (0,0) to (100,0) has centre (50,0), radius 50.
        points = flatten_arc((0, 0), 50, 50, 0, False, True, (100, 0), tolerance=0.01)
        assert max_deviation_from_circle(points, 50, 0, 50) < 0.05

    def test_sweep_flag_chooses_the_side(self):
        # Sweep 1 is the "positive-angle" direction, which in SVG's y-down space
        # is clockwise on screen. Going clockwise from a left endpoint to a right
        # one arcs over the top, i.e. towards negative y.
        clockwise = flatten_arc((0, 0), 50, 50, 0, False, True, (100, 0), tolerance=0.5)
        anticlockwise = flatten_arc((0, 0), 50, 50, 0, False, False, (100, 0), tolerance=0.5)
        assert min(y for _, y in clockwise) == pytest.approx(-50, abs=0.5)
        assert max(y for _, y in clockwise) <= 0
        assert max(y for _, y in anticlockwise) == pytest.approx(50, abs=0.5)
        assert min(y for _, y in anticlockwise) >= 0

    def test_large_arc_flag_chooses_the_longer_path(self):
        small = flatten_arc((0, 0), 50, 50, 0, False, True, (50, 50), tolerance=0.5)
        large = flatten_arc((0, 0), 50, 50, 0, True, True, (50, 50), tolerance=0.5)

        def length(points):
            path = [(0, 0)] + points
            return sum(math.dist(a, b) for a, b in zip(path, path[1:], strict=False))

        assert length(large) > length(small)

    def test_out_of_range_radii_are_scaled_up_to_span_the_endpoints(self):
        # Radius 10 cannot span 100 units; the spec says to scale it up, which
        # yields a semicircle of radius 50 rather than an error.
        points = flatten_arc((0, 0), 10, 10, 0, False, True, (100, 0), tolerance=0.01)
        assert max_deviation_from_circle(points, 50, 0, 50) < 0.5

    def test_rotated_ellipse_endpoints_are_honoured(self):
        points = flatten_arc((0, 0), 60, 30, 45, True, False, (40, 40), tolerance=0.1)
        assert points[-1] == (40, 40)

    def test_tighter_tolerance_produces_more_points(self):
        loose = flatten_arc((0, 0), 50, 50, 0, False, True, (100, 0), tolerance=5.0)
        tight = flatten_arc((0, 0), 50, 50, 0, False, True, (100, 0), tolerance=0.05)
        assert len(tight) > len(loose)

    def test_segment_count_is_bounded(self):
        # A pathological tolerance must not try to allocate unbounded points.
        points = flatten_arc((0, 0), 1e6, 1e6, 0, True, True, (1, 1), tolerance=1e-9)
        assert len(points) <= 2048
