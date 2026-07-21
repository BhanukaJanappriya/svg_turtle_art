"""Tests for pen-plotter G-code export."""

from __future__ import annotations

import re

import pytest

from svg_turtle_renderer.core.gcode import GCodeOptions, to_gcode, travel_distance
from svg_turtle_renderer.core.model import Drawing, Shape, Style, SubPath
from svg_turtle_renderer.geometry.coordinate_system import BoundingBox

_UNIT_BOX = BoundingBox(0, 0, 100, 100)


def drawing_from(subpaths, viewbox=_UNIT_BOX):
    """Build a one-shape drawing from lists of points."""
    shapes = [
        Shape(
            subpaths=[SubPath(points=pts, closed=closed) for pts, closed in subpaths], style=Style()
        )
    ]
    return Drawing(shapes=shapes, viewbox=viewbox, width=viewbox.width, height=viewbox.height)


def coordinates(gcode):
    """Return every (x, y) named in the G-code."""
    return [
        (float(m.group(1)), float(m.group(2))) for m in re.finditer(r"X([-\d.]+) Y([-\d.]+)", gcode)
    ]


SQUARE = drawing_from([([(10, 10), (90, 10), (90, 90), (10, 90)], True)])


class TestStructure:
    def test_it_declares_millimetres_and_absolute_mode(self):
        gcode = to_gcode(SQUARE)
        assert "G21" in gcode  # millimetres
        assert "G90" in gcode  # absolute

    def test_it_lifts_the_pen_before_moving_and_ends_cleanly(self):
        gcode = to_gcode(SQUARE, GCodeOptions(pen_up="G0 Z5", pen_down="G1 Z0"))
        lines = gcode.splitlines()
        assert "G0 Z5" in lines  # pen lifts
        assert "G1 Z0" in lines  # pen lowers
        assert lines[-1].startswith("M2")  # program end

    def test_each_stroke_lowers_then_lifts_the_pen(self):
        # A closed square is one stroke: one lower and, with the leading lift, a
        # balanced number of pen movements.
        gcode = to_gcode(SQUARE, GCodeOptions(pen_up="PENUP", pen_down="PENDOWN"))
        assert gcode.count("PENDOWN") == 1
        assert gcode.count("PENUP") == 2  # the initial lift, plus after the stroke

    def test_a_travel_move_precedes_each_stroke(self):
        gcode = to_gcode(SQUARE)
        assert re.search(r"G0 X[\d.]+ Y[\d.]+ F", gcode)  # rapid to the start

    def test_the_closing_segment_is_emitted_for_a_closed_path(self):
        # The square has four corners; closing it makes five points to visit.
        gcode = to_gcode(SQUARE, GCodeOptions(optimize=False))
        draws = [ln for ln in gcode.splitlines() if ln.startswith("G1 X")]
        assert len(draws) == 4  # first corner is the G0 travel; four G1 close the loop


class TestBedFitting:
    def test_the_drawing_stays_within_the_bed(self):
        gcode = to_gcode(SQUARE, GCodeOptions(bed_width=200, bed_height=200, margin=10))
        for x, y in coordinates(gcode):
            assert 0 <= x <= 200
            assert 0 <= y <= 200

    def test_the_margin_is_respected(self):
        gcode = to_gcode(SQUARE, GCodeOptions(bed_width=200, bed_height=200, margin=25))
        coords = coordinates(gcode)
        xs = [x for x, _ in coords]
        assert min(xs) >= 25 - 1e-6

    def test_the_drawing_is_centred(self):
        gcode = to_gcode(SQUARE, GCodeOptions(bed_width=200, bed_height=300, margin=10))
        coords = coordinates(gcode)
        xs = [x for x, _ in coords]
        ys = [y for _, y in coords]
        assert (min(xs) + max(xs)) / 2 == pytest.approx(100, abs=0.5)
        assert (min(ys) + max(ys)) / 2 == pytest.approx(150, abs=0.5)

    def test_the_aspect_ratio_is_preserved(self):
        wide = drawing_from(
            [([(0, 0), (200, 0), (200, 50)], False)], viewbox=BoundingBox(0, 0, 200, 50)
        )
        gcode = to_gcode(wide, GCodeOptions(bed_width=200, bed_height=200, margin=0))
        coords = coordinates(gcode)
        span_x = max(x for x, _ in coords) - min(x for x, _ in coords)
        span_y = max(y for _, y in coords) - min(y for _, y in coords)
        assert span_x / span_y == pytest.approx(4.0, abs=0.1)

    def test_y_up_and_y_down_flip_the_drawing(self):
        up = to_gcode(SQUARE, GCodeOptions(y_up=True, optimize=False))
        down = to_gcode(SQUARE, GCodeOptions(y_up=False, optimize=False))
        # The first travelled point ends up on opposite sides of the bed.
        first_up = coordinates(up)[0]
        first_down = coordinates(down)[0]
        assert first_up[1] != pytest.approx(first_down[1])


class TestSimplifyAndOrder:
    def test_simplify_drops_redundant_points(self):
        dense = drawing_from(
            [([(0, 0), (25, 0), (50, 0), (75, 0), (100, 0)], False)],
            viewbox=BoundingBox(0, 0, 100, 100),
        )
        plain = to_gcode(dense, GCodeOptions(simplify=0.0))
        thinned = to_gcode(dense, GCodeOptions(simplify=1.0))
        assert thinned.count("G1 X") < plain.count("G1 X")

    def test_ordering_shortens_the_travel(self):
        # Three strokes whose document order zig-zags across the bed.
        polylines = [
            [(0.0, 0.0), (1.0, 0.0)],
            [(100.0, 0.0), (101.0, 0.0)],
            [(2.0, 0.0), (3.0, 0.0)],
        ]
        from svg_turtle_renderer.core.gcode import _order

        assert travel_distance(_order(polylines)) < travel_distance(polylines)

    def test_ordering_is_safe_to_skip_for_few_strokes(self):
        from svg_turtle_renderer.core.gcode import _order

        two = [[(0.0, 0.0), (1.0, 0.0)], [(5.0, 5.0), (6.0, 6.0)]]
        assert _order(two) == two


class TestDegenerate:
    def test_an_empty_drawing_still_produces_valid_gcode(self):
        empty = Drawing(shapes=[], viewbox=BoundingBox(0, 0, 100, 100), width=100, height=100)
        gcode = to_gcode(empty)
        assert "G21" in gcode
        assert gcode.strip().endswith("M2 ; end")

    def test_single_point_subpaths_are_dropped(self):
        drawing = drawing_from([([(50, 50)], False), ([(10, 10), (90, 90)], False)])
        gcode = to_gcode(drawing)
        # Only the two-point stroke survives.
        assert gcode.count("G1 X") == 1
