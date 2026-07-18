"""Tests for slicing a region into horizontal fill bands."""

from __future__ import annotations

import pytest

from svg_turtle_renderer.geometry.banding import group_bounds, horizontal_bands
from svg_turtle_renderer.geometry.coordinate_system import BoundingBox

BOX = BoundingBox(0, 0, 100, 100)


class TestHorizontalBands:
    def test_a_short_region_is_one_band(self):
        bands = list(horizontal_bands(BoundingBox(0, 0, 100, 20), step=1000))
        assert len(bands) == 1

    def test_a_tall_region_is_sliced(self):
        bands = list(horizontal_bands(BOX, step=10))
        assert len(bands) == 10

    def test_the_advances_sum_to_the_region_height(self):
        # This is what keeps progress reporting exact: the reported distance must
        # add up to the height, whatever the step.
        for step in (7, 10, 13, 33):
            bands = list(horizontal_bands(BOX, step=step))
            assert sum(b.advance for b in bands) == pytest.approx(BOX.height)

    def test_the_bands_span_the_whole_region(self):
        bands = list(horizontal_bands(BOX, step=10))
        # Ignoring the seam overlap, the bands must cover top to bottom.
        low = min(b.box.min_y for b in bands)
        high = max(b.box.max_y for b in bands)
        assert low <= BOX.min_y
        assert high >= BOX.max_y

    def test_bands_are_full_width(self):
        for band in horizontal_bands(BOX, step=25):
            assert band.box.min_x == BOX.min_x
            assert band.box.max_x == BOX.max_x

    def test_neighbouring_bands_overlap_so_there_is_no_seam(self):
        # Abutting opaque strips can leave a hairline gap where the backend
        # antialiases the shared edge; the bands overlap to prevent it.
        bands = list(horizontal_bands(BOX, step=10, top_down=False))
        for lower, upper in zip(bands, bands[1:], strict=False):
            assert upper.box.min_y < lower.box.max_y

    def test_top_down_starts_at_the_top(self):
        bands = list(horizontal_bands(BOX, step=10, top_down=True))
        # Canvas space is y-up, so the top is the high-y end.
        assert bands[0].box.max_y >= BOX.max_y

    def test_bottom_up_starts_at_the_bottom(self):
        bands = list(horizontal_bands(BOX, step=10, top_down=False))
        assert bands[0].box.min_y <= BOX.min_y

    def test_a_step_finer_than_half_a_pixel_is_clamped(self):
        # A finer fill front is invisible and would produce a runaway band count.
        bands = list(horizontal_bands(BOX, step=0.001))
        assert len(bands) <= BOX.height / 0.5 + 1

    def test_a_degenerate_region_yields_nothing(self):
        assert list(horizontal_bands(BoundingBox(0, 0, 0, 0), step=10)) == []
        assert list(horizontal_bands(BoundingBox(0, 5, 100, 5), step=10)) == []


class TestGroupBounds:
    def test_it_unions_every_ring(self):
        rings = [[(0, 0), (10, 0), (10, 10)], [(50, 50), (60, 50), (60, 60)]]
        box = group_bounds(rings)
        assert box == BoundingBox(0, 0, 60, 60)

    def test_a_single_ring(self):
        box = group_bounds([[(5, 5), (15, 5), (15, 25)]])
        assert box == BoundingBox(5, 5, 15, 25)

    def test_no_rings_gives_none(self):
        assert group_bounds([]) is None
