"""Tests for the transform attribute."""

from __future__ import annotations

import math

import pytest

from svg_turtle_renderer.core.exceptions import TransformError
from svg_turtle_renderer.geometry.coordinate_system import Matrix
from svg_turtle_renderer.parser.transform_parser import parse_transform


class TestSingleFunctions:
    def test_empty_gives_identity(self):
        assert parse_transform(None).is_identity()
        assert parse_transform("").is_identity()
        assert parse_transform("   ").is_identity()

    def test_translate_with_two_arguments(self):
        assert parse_transform("translate(10, 20)").apply((0, 0)) == pytest.approx((10, 20))

    def test_translate_with_one_argument_defaults_y_to_zero(self):
        assert parse_transform("translate(10)").apply((0, 0)) == pytest.approx((10, 0))

    def test_uniform_scale(self):
        assert parse_transform("scale(2)").apply((3, 4)) == pytest.approx((6, 8))

    def test_non_uniform_scale(self):
        assert parse_transform("scale(2, 3)").apply((3, 4)) == pytest.approx((6, 12))

    def test_rotate_about_the_origin(self):
        # 90 degrees in SVG's y-down space sends +x to +y.
        assert parse_transform("rotate(90)").apply((1, 0)) == pytest.approx((0, 1), abs=1e-9)

    def test_rotate_about_a_centre_leaves_that_point_fixed(self):
        assert parse_transform("rotate(45, 10, 10)").apply((10, 10)) == pytest.approx((10, 10))

    def test_matrix(self):
        assert parse_transform("matrix(1 0 0 1 5 5)").apply((0, 0)) == pytest.approx((5, 5))

    def test_skew_x(self):
        # skewX shifts x by y*tan(angle).
        assert parse_transform("skewX(45)").apply((0, 1)) == pytest.approx((1, 1))

    def test_skew_y(self):
        assert parse_transform("skewY(45)").apply((1, 0)) == pytest.approx((1, 1))


class TestComposition:
    def test_functions_compose_left_to_right(self):
        # scale runs first, then translate: (1,1) -> (2,2) -> (12,2).
        result = parse_transform("translate(10, 0) scale(2)").apply((1, 1))
        assert result == pytest.approx((12, 2))

    def test_order_matters(self):
        first = parse_transform("translate(10, 0) scale(2)").apply((1, 1))
        second = parse_transform("scale(2) translate(10, 0)").apply((1, 1))
        assert first != pytest.approx(second)

    def test_separators_are_flexible(self):
        expected = parse_transform("translate(10, 20) scale(2)")
        for text in (
            "translate(10 20) scale(2)",
            "translate(10,20)scale(2)",
            "  translate( 10 , 20 )   scale( 2 )  ",
        ):
            assert parse_transform(text).apply((5, 5)) == pytest.approx(expected.apply((5, 5)))

    def test_a_long_chain(self):
        matrix = parse_transform("translate(100 100) rotate(90) scale(2) translate(-10 -10)")
        assert matrix.apply((10, 10)) == pytest.approx((100, 100))


class TestErrorHandling:
    def test_unknown_function_is_skipped_when_not_strict(self):
        # The valid translate still applies.
        assert parse_transform("wobble(5) translate(10, 0)").apply((0, 0)) == pytest.approx((10, 0))

    def test_unknown_function_raises_in_strict_mode(self):
        with pytest.raises(TransformError, match="Unknown transform"):
            parse_transform("wobble(5)", strict=True)

    def test_wrong_arity_is_skipped_when_not_strict(self):
        assert parse_transform("translate(1,2,3)").is_identity()

    def test_wrong_arity_raises_in_strict_mode(self):
        with pytest.raises(TransformError, match="arguments"):
            parse_transform("rotate(1, 2)", strict=True)

    def test_garbage_raises_in_strict_mode(self):
        with pytest.raises(TransformError, match="No transform functions"):
            parse_transform("not a transform", strict=True)


class TestMatrixAlgebra:
    def test_identity_leaves_points_alone(self):
        assert Matrix.identity().apply((3, 7)) == (3, 7)

    def test_matmul_applies_the_right_operand_first(self):
        combined = Matrix.translate(10, 0) @ Matrix.scale(2)
        assert combined.apply((1, 1)) == pytest.approx((12, 2))

    def test_apply_all_matches_apply(self):
        matrix = Matrix.rotate(30) @ Matrix.translate(5, 5)
        points = [(0, 0), (1, 2), (-3, 4)]
        assert matrix.apply_all(points) == pytest.approx([matrix.apply(p) for p in points])

    def test_mean_scale_of_a_uniform_scale_is_that_scale(self):
        assert Matrix.scale(3).mean_scale == pytest.approx(3.0)

    def test_mean_scale_of_a_rotation_is_one(self):
        assert Matrix.rotate(37).mean_scale == pytest.approx(1.0)

    def test_mean_scale_of_a_non_uniform_scale_is_the_geometric_mean(self):
        # sqrt(|det|) = sqrt(2*8) = 4, the SVG fallback for stroke widths.
        assert Matrix.scale(2, 8).mean_scale == pytest.approx(4.0)

    def test_rotation_direction_is_clockwise_on_screen(self):
        # SVG's y-axis points down, so a positive angle turns +x towards +y.
        rotated = Matrix.rotate(90).apply((1, 0))
        assert rotated == pytest.approx((0, 1), abs=1e-9)

    def test_determinant_detects_a_mirror(self):
        assert Matrix.scale(-1, 1).determinant < 0

    def test_composition_is_associative(self):
        a, b, c = Matrix.rotate(20), Matrix.scale(2, 3), Matrix.translate(4, 5)
        left = (a @ b) @ c
        right = a @ (b @ c)
        assert left.apply((7, 9)) == pytest.approx(right.apply((7, 9)))

    def test_rotate_about_a_centre_matches_the_manual_composition(self):
        manual = Matrix.translate(10, 20) @ Matrix.rotate(35) @ Matrix.translate(-10, -20)
        assert Matrix.rotate(35, 10, 20).apply((3, 4)) == pytest.approx(manual.apply((3, 4)))

    def test_skew_matches_tangent(self):
        assert Matrix.skew_x(30).apply((0, 1)) == pytest.approx((math.tan(math.radians(30)), 1))
