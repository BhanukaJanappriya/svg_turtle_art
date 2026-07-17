"""Tests for path data parsing."""

from __future__ import annotations

import math

import pytest

from svg_turtle_renderer.core.exceptions import PathSyntaxError
from svg_turtle_renderer.parser.path_parser import PathParser, parse_path


class TestMoveAndLine:
    def test_empty_data_yields_nothing(self):
        assert parse_path("") == []
        assert parse_path("   ") == []

    def test_absolute_moveto_and_lineto(self):
        subpaths = parse_path("M 10 20 L 30 40")
        assert len(subpaths) == 1
        assert subpaths[0].points == [(10, 20), (30, 40)]
        assert not subpaths[0].closed

    def test_relative_commands_accumulate_from_the_cursor(self):
        subpaths = parse_path("m 10 10 l 5 5 l 5 5")
        assert subpaths[0].points == [(10, 10), (15, 15), (20, 20)]

    def test_horizontal_and_vertical_linetos(self):
        subpaths = parse_path("M 0 0 H 50 V 50 h -20 v -20")
        assert subpaths[0].points == [(0, 0), (50, 0), (50, 50), (30, 50), (30, 30)]

    def test_closepath_marks_the_subpath_closed(self):
        subpaths = parse_path("M 0 0 L 10 0 L 10 10 Z")
        assert subpaths[0].closed

    def test_a_command_after_closepath_starts_a_new_subpath_at_the_initial_point(self):
        # "If a closepath is followed immediately by any other command, then the
        # next subpath starts at the same initial point as the current subpath."
        # So the L begins a second subpath at (0,0), not a continuation of the
        # closed one, and not a line from (10,10).
        subpaths = parse_path("M 0 0 L 10 0 L 10 10 Z L 5 5")
        assert len(subpaths) == 2
        assert subpaths[0].closed
        assert subpaths[0].points == [(0, 0), (10, 0), (10, 10)]
        assert subpaths[1].points == [(0, 0), (5, 5)]
        assert not subpaths[1].closed

    def test_multiple_subpaths(self):
        subpaths = parse_path("M 0 0 L 10 10 M 20 20 L 30 30")
        assert len(subpaths) == 2
        assert subpaths[1].points == [(20, 20), (30, 30)]

    def test_single_point_subpaths_are_dropped(self):
        # A lone moveto draws nothing at all.
        assert parse_path("M 10 10") == []

    def test_data_must_start_with_a_moveto(self):
        with pytest.raises(PathSyntaxError, match="before any moveto"):
            parse_path("L 10 10", strict=True)

    def test_data_starting_with_a_number_is_refused(self):
        with pytest.raises(PathSyntaxError, match="must begin with a moveto"):
            parse_path("10 10 20 20", strict=True)


class TestImplicitRepeats:
    def test_repeated_lineto_arguments(self):
        subpaths = parse_path("M 0 0 L 10 10 20 20 30 30")
        assert subpaths[0].points == [(0, 0), (10, 10), (20, 20), (30, 30)]

    def test_repeated_moveto_becomes_a_lineto(self):
        # This is the rule that catches naive parsers: only the first pair is a
        # move, the rest draw lines within the same subpath.
        subpaths = parse_path("M 0 0 10 10 20 20")
        assert len(subpaths) == 1
        assert subpaths[0].points == [(0, 0), (10, 10), (20, 20)]

    def test_repeated_relative_moveto_becomes_a_relative_lineto(self):
        subpaths = parse_path("m 5 5 10 10")
        assert subpaths[0].points == [(5, 5), (15, 15)]

    def test_closepath_does_not_repeat(self):
        # Z takes no arguments, so bare numbers after it are an error. The valid
        # prefix still renders.
        subpaths = parse_path("M 0 0 L 5 0 L 5 5 Z 10 10")
        assert len(subpaths) == 1
        assert subpaths[0].closed


class TestNumberFormats:
    def test_comma_and_whitespace_are_interchangeable(self):
        assert parse_path("M0,0L10,10")[0].points == [(0, 0), (10, 10)]
        assert parse_path("M 0 0 L 10 10")[0].points == [(0, 0), (10, 10)]

    def test_negative_numbers_need_no_separator(self):
        assert parse_path("M0 0L-10-10")[0].points == [(0, 0), (-10, -10)]

    def test_decimals_without_a_leading_zero(self):
        assert parse_path("M .5 .5 L 1.5 1.5")[0].points == [(0.5, 0.5), (1.5, 1.5)]

    def test_scientific_notation(self):
        assert parse_path("M 1e2 1e2 L 2e2 2e2")[0].points == [(100, 100), (200, 200)]

    def test_explicit_plus_sign(self):
        assert parse_path("M +10 +10 L +20 +20")[0].points == [(10, 10), (20, 20)]


class TestCurves:
    def test_cubic_starts_and_ends_correctly(self):
        points = parse_path("M 0 0 C 0 50 100 50 100 0")[0].points
        assert points[0] == (0, 0)
        assert points[-1] == (100, 0)

    def test_smooth_cubic_reflects_the_previous_control_point(self):
        # After C ... with second control (0,-50) at cursor (0,0), the S command
        # reflects it to (0,50), so the curve leaves downward and is symmetric.
        points = parse_path("M -100 0 C -100 -50 0 -50 0 0 S 100 50 100 0")[0].points
        assert points[-1] == (100, 0)
        assert max(y for _, y in points) > 20

    def test_smooth_cubic_after_a_non_cubic_uses_the_current_point(self):
        # With no cubic before it, S has nothing to reflect, so the segment must
        # start out straight rather than inventing a control point.
        points = parse_path("M 0 0 L 10 0 S 20 10 30 10")[0].points
        assert points[-1] == (30, 10)

    def test_quadratic(self):
        points = parse_path("M 0 0 Q 50 100 100 0")[0].points
        assert points[-1] == (100, 0)

    def test_smooth_quadratic_chains(self):
        points = parse_path("M 0 0 Q 25 50 50 0 T 100 0")[0].points
        assert points[-1] == (100, 0)

    def test_relative_curves(self):
        absolute = parse_path("M 10 10 C 10 60 110 60 110 10")[0].points
        relative = parse_path("m 10 10 c 0 50 100 50 100 0")[0].points
        assert relative == pytest.approx(absolute)


class TestArcs:
    def test_arc_endpoint(self):
        assert parse_path("M 0 0 A 50 50 0 0 1 100 0")[0].points[-1] == (100, 0)

    def test_arc_flags_without_separators(self):
        # "a25 25 0 011 1" packs large-arc=0, sweep=1, then x=1: this is the
        # form optimisers emit, and it is three values, not one.
        points = parse_path("M 0 0 a25 25 0 011 1")[0].points
        assert points[-1] == pytest.approx((1, 1))

    def test_arc_flags_with_separators_parse_identically(self):
        packed = parse_path("M 0 0 a25 25 0 011 1")[0].points
        spaced = parse_path("M 0 0 a 25 25 0 0 1 1 1")[0].points
        assert packed == pytest.approx(spaced)

    def test_arc_traces_a_real_circle(self):
        points = parse_path("M 0 0 A 50 50 0 0 1 100 0", tolerance=0.01)[0].points
        for x, y in points:
            assert math.dist((x, y), (50, 0)) == pytest.approx(50, abs=0.05)

    def test_a_bad_arc_flag_is_reported(self):
        with pytest.raises(PathSyntaxError, match="arc flag"):
            parse_path("M 0 0 A 25 25 0 5 1 10 10", strict=True)


class TestErrorHandling:
    def test_missing_number_is_reported_with_context(self):
        with pytest.raises(PathSyntaxError, match="Expected a number"):
            parse_path("M 0 0 L 10", strict=True)

    def test_unknown_command_letter_is_rejected(self):
        # X is not a path command, so it cannot be tokenised at all.
        with pytest.raises(PathSyntaxError):
            parse_path("M 0 0 X 10 10", strict=True)

    def test_renders_up_to_the_command_containing_the_error(self):
        # The specification's own example: "M 10,10 L 20,20,30" has an odd
        # parameter count, and should draw (10,10)->(20,20) and stop.
        subpaths = parse_path("M 10,10 L 20,20,30")
        assert len(subpaths) == 1
        assert subpaths[0].points == [(10, 10), (20, 20)]

    def test_truncation_keeps_earlier_subpaths(self):
        subpaths = parse_path("M 0 0 L 10 0 Z M 20 20 L 30 30 L 40")
        assert len(subpaths) == 2
        assert subpaths[0].closed
        assert subpaths[1].points == [(20, 20), (30, 30)]

    def test_an_unparseable_prefix_yields_nothing_rather_than_raising(self):
        assert parse_path("L 10 10") == []

    def test_a_valid_path_never_warns(self, caplog):
        parse_path("M 0 0 L 10 10 Z")
        assert not caplog.records


class TestTolerance:
    def test_tolerance_controls_vertex_count(self):
        loose = PathParser(tolerance=10.0).parse("M 0 0 C 0 100 100 100 100 0")
        tight = PathParser(tolerance=0.01).parse("M 0 0 C 0 100 100 100 100 0")
        assert len(tight[0].points) > len(loose[0].points)

    def test_real_world_compound_path(self):
        # A donut: two rings in one path, which must stay two subpaths.
        subpaths = parse_path(
            "M 50 10 A 40 40 0 1 0 50 90 A 40 40 0 1 0 50 10 Z "
            "M 50 30 A 20 20 0 1 1 50 70 A 20 20 0 1 1 50 30 Z"
        )
        assert len(subpaths) == 2
        assert all(sp.closed for sp in subpaths)
