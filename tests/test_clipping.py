"""Tests for rectangular clipping."""

from __future__ import annotations

import pytest

from svg_turtle_renderer.geometry.clipping import clip_polygon, clip_polyline
from svg_turtle_renderer.geometry.coordinate_system import BoundingBox

BOX = BoundingBox(0, 0, 10, 10)


def bounds(points):
    """Return the bounding box of a point list."""
    return BoundingBox.from_points(points)


class TestClipPolygon:
    def test_a_polygon_inside_the_box_is_unchanged(self):
        square = [(2, 2), (8, 2), (8, 8), (2, 8)]
        assert set(clip_polygon(square, BOX)) == set(square)

    def test_a_polygon_outside_the_box_disappears(self):
        assert clip_polygon([(20, 20), (30, 20), (30, 30)], BOX) == []

    def test_a_straddling_polygon_is_cropped_to_the_box(self):
        result = clip_polygon([(-5, -5), (5, -5), (5, 5), (-5, 5)], BOX)
        box = bounds(result)
        assert box.min_x >= -1e-9
        assert box.min_y >= -1e-9

    def test_a_polygon_covering_the_box_becomes_the_box(self):
        result = clip_polygon([(-100, -100), (100, -100), (100, 100), (-100, 100)], BOX)
        assert bounds(result) == BOX

    def test_the_clipped_area_never_escapes_the_box(self):
        result = clip_polygon([(-20, 5), (20, 5), (0, 20)], BOX)
        for x, y in result:
            assert -1e-9 <= x <= 10 + 1e-9
            assert -1e-9 <= y <= 10 + 1e-9

    def test_degenerate_input(self):
        assert clip_polygon([(0, 0), (1, 1)], BOX) == []
        assert clip_polygon([], BOX) == []

    def test_an_empty_clip_box_removes_everything(self):
        assert clip_polygon([(0, 0), (5, 0), (5, 5)], BoundingBox(0, 0, 0, 0)) == []


class TestClipPolyline:
    def test_a_polyline_inside_the_box_is_unchanged(self):
        line = [(1, 1), (5, 5), (9, 9)]
        assert clip_polyline(line, BOX) == [line]

    def test_a_polyline_outside_the_box_disappears(self):
        assert clip_polyline([(20, 20), (30, 30)], BOX) == []

    def test_a_crossing_polyline_is_cropped(self):
        result = clip_polyline([(-5, 5), (15, 5)], BOX)
        assert len(result) == 1
        assert result[0][0] == pytest.approx((0, 5))
        assert result[0][-1] == pytest.approx((10, 5))

    def test_a_polyline_that_re_enters_produces_several_runs(self):
        # Out of the box in the middle, so this must not be joined into one run
        # with a false segment bridging the gap.
        result = clip_polyline([(1, 5), (1, 20), (9, 20), (9, 5)], BOX)
        assert len(result) == 2

    def test_a_run_never_escapes_the_box(self):
        for run in clip_polyline([(-5, -5), (15, 15), (-5, 15)], BOX):
            for x, y in run:
                assert -1e-9 <= x <= 10 + 1e-9
                assert -1e-9 <= y <= 10 + 1e-9

    def test_a_segment_along_the_boundary_survives(self):
        result = clip_polyline([(0, 0), (10, 0)], BOX)
        assert len(result) == 1

    def test_degenerate_input(self):
        assert clip_polyline([(1, 1)], BOX) == []
        assert clip_polyline([], BOX) == []
