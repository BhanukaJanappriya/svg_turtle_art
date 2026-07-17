"""Tests for paint value resolution."""

from __future__ import annotations

import pytest

from svg_turtle_renderer.core.exceptions import ColorError
from svg_turtle_renderer.parser.color_parser import (
    BLACK,
    WHITE,
    Color,
    hsl_to_rgb,
    parse_color,
    parse_opacity,
)


class TestHexColors:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("#000", (0, 0, 0)),
            ("#fff", (255, 255, 255)),
            ("#f80", (255, 136, 0)),
            ("#FF0000", (255, 0, 0)),
            ("#1a2b3c", (26, 43, 60)),
        ],
    )
    def test_parses_hex(self, text, expected):
        color = parse_color(text)
        assert (color.r, color.g, color.b) == expected

    def test_short_hex_expands_by_doubling_not_padding(self):
        # #f80 is #ff8800, not #f08000: each digit doubles.
        assert parse_color("#f80").as_hex() == "#ff8800"

    def test_four_digit_hex_carries_alpha(self):
        color = parse_color("#ff008080")
        assert (color.r, color.g, color.b) == (255, 0, 128)
        assert color.a == pytest.approx(128 / 255)

    def test_eight_digit_hex_carries_alpha(self):
        assert parse_color("#00ff00ff").a == 1.0

    @pytest.mark.parametrize("text", ["#12345", "#gg0000", "#"])
    def test_malformed_hex_raises_in_strict_mode(self, text):
        with pytest.raises(ColorError):
            parse_color(text, strict=True)

    def test_malformed_hex_is_ignored_when_not_strict(self):
        assert parse_color("#12345") is None


class TestFunctionalColors:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("rgb(255, 0, 0)", (255, 0, 0)),
            ("rgb(0,128,255)", (0, 128, 255)),
            ("rgb(100%, 0%, 50%)", (255, 0, 128)),
            ("RGB( 10 , 20 , 30 )", (10, 20, 30)),
        ],
    )
    def test_parses_rgb(self, text, expected):
        color = parse_color(text)
        assert (color.r, color.g, color.b) == expected

    def test_rgba_carries_alpha(self):
        color = parse_color("rgba(255, 0, 0, 0.5)")
        assert (color.r, color.g, color.b) == (255, 0, 0)
        assert color.a == pytest.approx(0.5)

    def test_modern_space_separated_syntax(self):
        color = parse_color("rgb(255 0 0 / 50%)")
        assert (color.r, color.g, color.b) == (255, 0, 0)
        assert color.a == pytest.approx(0.5)

    def test_channels_clamp_rather_than_wrap(self):
        color = parse_color("rgb(300, -20, 0)")
        assert (color.r, color.g, color.b) == (255, 0, 0)

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("hsl(0, 100%, 50%)", (255, 0, 0)),
            ("hsl(120, 100%, 50%)", (0, 255, 0)),
            ("hsl(240, 100%, 50%)", (0, 0, 255)),
            ("hsl(0, 0%, 50%)", (128, 128, 128)),
        ],
    )
    def test_parses_hsl(self, text, expected):
        color = parse_color(text)
        assert (color.r, color.g, color.b) == expected

    def test_hsla_carries_alpha(self):
        assert parse_color("hsla(0, 100%, 50%, 0.25)").a == pytest.approx(0.25)

    def test_hue_wraps(self):
        assert parse_color("hsl(360, 100%, 50%)") == parse_color("hsl(0, 100%, 50%)")
        assert parse_color("hsl(-120, 100%, 50%)") == parse_color("hsl(240, 100%, 50%)")

    def test_hue_accepts_angle_units(self):
        assert parse_color("hsl(0.5turn, 100%, 50%)") == parse_color("hsl(180, 100%, 50%)")

    def test_wrong_arity_raises_in_strict_mode(self):
        with pytest.raises(ColorError):
            parse_color("rgb(1, 2)", strict=True)


class TestNamedAndKeywordColors:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [("red", (255, 0, 0)), ("tomato", (255, 99, 71)), ("rebeccapurple", (102, 51, 153))],
    )
    def test_parses_named_colors(self, text, expected):
        color = parse_color(text)
        assert (color.r, color.g, color.b) == expected

    def test_names_are_case_insensitive(self):
        assert parse_color("RED") == parse_color("red")

    @pytest.mark.parametrize("text", ["none", "None", "transparent", "  "])
    def test_none_means_do_not_paint(self, text):
        assert parse_color(text) is None

    def test_current_color_resolves_to_the_inherited_color(self):
        teal = Color(0, 128, 128)
        assert parse_color("currentColor", current_color=teal) == teal

    def test_paint_servers_are_refused_rather_than_guessed(self):
        with pytest.raises(ColorError):
            parse_color("url(#gradient)", strict=True)
        assert parse_color("url(#gradient)") is None

    def test_unknown_name_is_ignored_when_not_strict(self):
        assert parse_color("burntsienna") is None


class TestColorConversions:
    def test_as_turtle_normalises_to_unit_floats(self):
        assert Color(255, 128, 0).as_turtle() == pytest.approx((1.0, 128 / 255, 0.0))

    def test_with_alpha_multiplies_rather_than_replaces(self):
        color = Color(1, 2, 3, 0.5).with_alpha(0.5)
        assert color.a == pytest.approx(0.25)

    def test_opaque_color_composites_to_itself(self):
        assert Color(10, 20, 30).composite_over(WHITE) == Color(10, 20, 30)

    def test_half_alpha_black_over_white_is_grey(self):
        result = Color(0, 0, 0, 0.5).composite_over(WHITE)
        assert (result.r, result.g, result.b) == (128, 128, 128)
        assert result.a == 1.0

    def test_zero_alpha_composites_to_the_background(self):
        assert Color(255, 0, 0, 0.0).composite_over(BLACK) == BLACK

    def test_hsl_to_rgb_matches_css_reference(self):
        assert hsl_to_rgb(210, 0.5, 0.4) == (51, 102, 153)


class TestOpacity:
    @pytest.mark.parametrize(
        ("text", "expected"), [("1", 1.0), ("0.5", 0.5), ("50%", 0.5), ("0", 0.0)]
    )
    def test_parses_opacity(self, text, expected):
        assert parse_opacity(text) == pytest.approx(expected)

    def test_clamps_out_of_range_values(self):
        assert parse_opacity("1.5") == 1.0
        assert parse_opacity("-1") == 0.0

    def test_falls_back_to_the_default(self):
        assert parse_opacity(None, 0.3) == 0.3
        assert parse_opacity("nonsense", 0.3) == 0.3
