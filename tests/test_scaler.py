"""Tests for fitting artwork to the canvas."""

from __future__ import annotations

import pytest

from svg_turtle_renderer.geometry.coordinate_system import BoundingBox
from svg_turtle_renderer.geometry.scaler import FitOptions, build_coordinate_system


def corners(box: BoundingBox):
    """Return a box's four corners."""
    return [
        (box.min_x, box.min_y),
        (box.max_x, box.min_y),
        (box.max_x, box.max_y),
        (box.min_x, box.max_y),
    ]


def mapped_bounds(box: BoundingBox, options: FitOptions) -> BoundingBox:
    """Return the canvas-space bounds of a source box under a fit."""
    system = build_coordinate_system(box, options)
    return BoundingBox.from_points(system.all_to_canvas(corners(box)))


class TestAutoFit:
    def test_artwork_is_centred_on_the_origin(self):
        box = BoundingBox(0, 0, 400, 300)
        result = mapped_bounds(box, FitOptions(1000, 800))
        assert result.center == pytest.approx((0, 0))

    def test_artwork_fills_the_canvas_minus_the_margin(self):
        box = BoundingBox(0, 0, 400, 300)
        result = mapped_bounds(box, FitOptions(1000, 800, margin=20))
        # 400x300 has ratio 4:3; the canvas minus margins is 960x760, so width
        # is the binding constraint: scale 2.4, giving 960x720.
        assert result.width == pytest.approx(960)
        assert result.height == pytest.approx(720)

    def test_aspect_ratio_is_preserved(self):
        box = BoundingBox(0, 0, 400, 100)
        result = mapped_bounds(box, FitOptions(1000, 800))
        assert result.width / result.height == pytest.approx(4.0)

    def test_height_can_be_the_binding_constraint(self):
        box = BoundingBox(0, 0, 100, 400)
        result = mapped_bounds(box, FitOptions(1000, 800, margin=0))
        assert result.height == pytest.approx(800)
        assert result.width == pytest.approx(200)

    def test_a_source_box_not_at_the_origin_still_centres(self):
        box = BoundingBox(1000, 2000, 1400, 2300)
        result = mapped_bounds(box, FitOptions(1000, 800))
        assert result.center == pytest.approx((0, 0))

    def test_scale_factor_is_reported(self):
        box = BoundingBox(0, 0, 400, 300)
        system = build_coordinate_system(box, FitOptions(1000, 800, margin=20))
        assert system.scale_factor == pytest.approx(2.4)

    def test_bigger_margin_means_smaller_artwork(self):
        box = BoundingBox(0, 0, 400, 300)
        wide = mapped_bounds(box, FitOptions(1000, 800, margin=100))
        narrow = mapped_bounds(box, FitOptions(1000, 800, margin=10))
        assert wide.width < narrow.width


class TestYAxis:
    def test_the_y_axis_is_inverted_for_turtle(self):
        # SVG's y grows downward; turtle's grows upward. The top of the source
        # box must therefore land at positive y.
        box = BoundingBox(0, 0, 100, 100)
        system = build_coordinate_system(box, FitOptions(1000, 800, scale=1.0))
        top_left = system.to_canvas((0, 0))
        bottom_left = system.to_canvas((0, 100))
        assert top_left[1] > bottom_left[1]

    def test_x_is_not_inverted(self):
        box = BoundingBox(0, 0, 100, 100)
        system = build_coordinate_system(box, FitOptions(1000, 800, scale=1.0))
        assert system.to_canvas((0, 50))[0] < system.to_canvas((100, 50))[0]


class TestExplicitScaleAndOffset:
    def test_explicit_scale_overrides_the_fit(self):
        box = BoundingBox(0, 0, 100, 100)
        system = build_coordinate_system(box, FitOptions(1000, 800, scale=3.0))
        assert system.scale_factor == pytest.approx(3.0)

    def test_explicit_scale_may_overflow_the_canvas(self):
        # Zooming in is a legitimate request, not something to clamp away.
        box = BoundingBox(0, 0, 100, 100)
        result = mapped_bounds(box, FitOptions(200, 200, scale=10.0))
        assert result.width == pytest.approx(1000)

    def test_offset_moves_the_artwork(self):
        box = BoundingBox(0, 0, 100, 100)
        result = mapped_bounds(box, FitOptions(1000, 800, scale=1.0, offset_x=50, offset_y=25))
        assert result.center == pytest.approx((50, 25))

    def test_positive_offset_y_moves_up_in_canvas_space(self):
        box = BoundingBox(0, 0, 100, 100)
        base = mapped_bounds(box, FitOptions(1000, 800, scale=1.0))
        moved = mapped_bounds(box, FitOptions(1000, 800, scale=1.0, offset_y=100))
        assert moved.center[1] > base.center[1]


class TestOrientation:
    def test_mirror_flips_horizontally(self):
        box = BoundingBox(0, 0, 100, 50)
        system = build_coordinate_system(box, FitOptions(1000, 800, scale=1.0, mirror=True))
        # The source's left edge must land on the canvas's right.
        assert system.to_canvas((0, 25))[0] > system.to_canvas((100, 25))[0]

    def test_flip_inverts_vertically(self):
        box = BoundingBox(0, 0, 100, 50)
        plain = build_coordinate_system(box, FitOptions(1000, 800, scale=1.0))
        flipped = build_coordinate_system(box, FitOptions(1000, 800, scale=1.0, flip=True))
        assert plain.to_canvas((50, 0))[1] == pytest.approx(-flipped.to_canvas((50, 0))[1])

    def test_mirror_does_not_change_the_bounding_size(self):
        box = BoundingBox(0, 0, 400, 300)
        plain = mapped_bounds(box, FitOptions(1000, 800))
        mirrored = mapped_bounds(box, FitOptions(1000, 800, mirror=True))
        assert mirrored.width == pytest.approx(plain.width)

    def test_rotation_is_clockwise_on_screen(self):
        box = BoundingBox(0, 0, 100, 100)
        system = build_coordinate_system(box, FitOptions(1000, 800, scale=1.0, rotate=90))
        # The source's top-centre, once rotated 90 degrees clockwise on screen,
        # should sit on the right-hand side of the canvas.
        assert system.to_canvas((50, 0))[0] == pytest.approx(50)

    def test_rotated_artwork_is_refitted_to_stay_inside_the_canvas(self):
        # A wide box rotated 90 degrees is tall, so it must be scaled down more.
        box = BoundingBox(0, 0, 400, 100)
        upright = build_coordinate_system(box, FitOptions(1000, 400, margin=0))
        turned = build_coordinate_system(box, FitOptions(1000, 400, margin=0, rotate=90))
        assert turned.scale_factor < upright.scale_factor

    def test_a_rotated_fit_still_fits(self):
        box = BoundingBox(0, 0, 400, 100)
        result = mapped_bounds(box, FitOptions(1000, 400, margin=10, rotate=90))
        assert result.width <= 980 + 1e-6
        assert result.height <= 380 + 1e-6


class TestDegenerateInput:
    def test_an_empty_box_does_not_divide_by_zero(self):
        system = build_coordinate_system(BoundingBox(5, 5, 5, 5), FitOptions(1000, 800))
        assert system.scale_factor == pytest.approx(1.0)

    def test_a_zero_height_box_falls_back_to_unit_scale(self):
        system = build_coordinate_system(BoundingBox(0, 5, 100, 5), FitOptions(1000, 800))
        assert system.scale_factor == pytest.approx(1.0)

    def test_a_canvas_smaller_than_its_margins_does_not_invert(self):
        system = build_coordinate_system(
            BoundingBox(0, 0, 100, 100), FitOptions(100, 100, margin=80)
        )
        assert system.scale_factor > 0
