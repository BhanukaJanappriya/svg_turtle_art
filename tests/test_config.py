"""Tests for configuration and validation."""

from __future__ import annotations

import json

import pytest

from svg_turtle_renderer.core.config import THEMES, RenderConfig
from svg_turtle_renderer.core.exceptions import ConfigError


class TestValidation:
    def test_a_minimal_config_is_valid(self, config):
        assert config().input_path

    def test_an_empty_input_path_is_rejected(self):
        with pytest.raises(ConfigError, match="input SVG path is required"):
            RenderConfig(input_path="")

    @pytest.mark.parametrize(("width", "height"), [(50, 800), (800, 50), (0, 0)])
    def test_a_tiny_canvas_is_rejected(self, config, width, height):
        with pytest.raises(ConfigError, match="at least 100x100"):
            config(canvas_width=width, canvas_height=height)

    def test_a_non_positive_scale_is_rejected(self, config):
        with pytest.raises(ConfigError, match="scale must be positive"):
            config(scale=0)
        with pytest.raises(ConfigError, match="scale must be positive"):
            config(scale=-2)

    def test_scale_none_means_auto_and_is_valid(self, config):
        assert config(scale=None).scale is None

    def test_a_negative_margin_is_rejected(self, config):
        with pytest.raises(ConfigError, match="margin"):
            config(margin=-1)

    def test_speed_is_bounded(self, config):
        with pytest.raises(ConfigError, match="speed"):
            config(speed=11)
        with pytest.raises(ConfigError, match="speed"):
            config(speed=-1)

    def test_fps_must_be_positive(self, config):
        with pytest.raises(ConfigError, match="fps"):
            config(fps=0)

    def test_resolution_must_be_positive(self, config):
        with pytest.raises(ConfigError, match="resolution"):
            config(resolution=0)

    def test_an_unknown_fit_mode_is_rejected(self, config):
        with pytest.raises(ConfigError, match="fit"):
            config(fit="sideways")

    def test_an_unknown_color_mode_is_rejected(self, config):
        with pytest.raises(ConfigError, match="color-mode"):
            config(color_mode="rainbow")

    def test_drawing_nothing_is_rejected_with_a_helpful_message(self):
        # This combination would open a window and paint an empty canvas, which
        # looks like a bug to the user; better to say so up front.
        with pytest.raises(ConfigError, match="Nothing would be drawn"):
            RenderConfig(input_path="a.svg", fill=False, stroke=False)

    def test_wireframe_rescues_the_no_paint_combination(self, config):
        assert config(fill=False, stroke=False, wireframe=True).wireframe


class TestSpeed:
    def test_turtle_speed_passes_through_when_not_animating(self, config):
        assert config(speed=5).turtle_speed == 5

    def test_animating_disables_turtle_native_animation(self, config):
        # The frame clock drives the screen instead; leaving turtle's per-move
        # animation on as well would make a real drawing take hours.
        assert config(speed=5, animate=True).turtle_speed == 0


class TestThemes:
    def test_a_theme_sets_the_background(self, config):
        assert config(theme="dark").background == THEMES["dark"]["background"]

    def test_an_explicit_flag_beats_the_theme(self):
        # This is the reason _explicit exists: the user typed --background, so
        # the theme must not overwrite it.
        cfg = RenderConfig(
            input_path="a.svg", theme="dark", background="red", _explicit=frozenset({"background"})
        )
        assert cfg.background == "red"

    def test_a_theme_still_fills_in_fields_the_user_did_not_set(self):
        cfg = RenderConfig(
            input_path="a.svg", theme="dark", background="red", _explicit=frozenset({"background"})
        )
        assert cfg.mono_color == THEMES["dark"]["mono_color"]

    def test_a_theme_can_set_the_color_mode(self, config):
        assert config(theme="blueprint").color_mode == "mono"

    def test_an_unknown_theme_lists_the_valid_ones(self, config):
        with pytest.raises(ConfigError, match="Available:"):
            config(theme="chartreuse")

    @pytest.mark.parametrize("name", sorted(THEMES))
    def test_every_theme_produces_a_valid_config(self, config, name):
        assert config(theme=name).theme == name


class TestConfigFile:
    def test_loads_from_json(self, tmp_path, svg_file):
        svg = svg_file('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>')
        path = tmp_path / "cfg.json"
        path.write_text(json.dumps({"input_path": svg, "canvas_width": 640, "background": "black"}))
        cfg = RenderConfig.from_file(path)
        assert cfg.canvas_width == 640
        assert cfg.background == "black"

    def test_command_line_overrides_beat_the_file(self, tmp_path, svg_file):
        svg = svg_file('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>')
        path = tmp_path / "cfg.json"
        path.write_text(json.dumps({"input_path": svg, "canvas_width": 640}))
        assert RenderConfig.from_file(path, canvas_width=1280).canvas_width == 1280

    def test_a_missing_file_is_reported(self):
        with pytest.raises(ConfigError, match="not found"):
            RenderConfig.from_file("nope.json")

    def test_invalid_json_is_reported(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json")
        with pytest.raises(ConfigError, match="not valid JSON"):
            RenderConfig.from_file(path)

    def test_a_json_array_is_rejected(self, tmp_path):
        path = tmp_path / "arr.json"
        path.write_text("[1, 2]")
        with pytest.raises(ConfigError, match="must contain a JSON object"):
            RenderConfig.from_file(path)

    def test_unknown_keys_are_reported_rather_than_ignored(self, tmp_path):
        # A typo in a config file should not silently do nothing.
        path = tmp_path / "cfg.json"
        path.write_text(json.dumps({"input_path": "a.svg", "colour": "red"}))
        with pytest.raises(ConfigError, match="unknown keys: colour"):
            RenderConfig.from_file(path)

    def test_a_file_setting_is_marked_explicit_so_a_theme_cannot_clobber_it(
        self, tmp_path, svg_file
    ):
        svg = svg_file('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>')
        path = tmp_path / "cfg.json"
        path.write_text(json.dumps({"input_path": svg, "theme": "dark", "background": "pink"}))
        assert RenderConfig.from_file(path).background == "pink"


class TestSerialisation:
    def test_to_dict_round_trips(self, config):
        data = config(canvas_width=640).to_dict()
        assert data["canvas_width"] == 640
        assert "_explicit" not in data

    def test_to_dict_is_json_serialisable(self, config):
        json.dumps(config().to_dict())

    def test_with_overrides_returns_a_new_validated_config(self, config):
        original = config(canvas_width=640)
        assert original.with_overrides(canvas_width=800).canvas_width == 800
        assert original.canvas_width == 640

    def test_with_overrides_still_validates(self, config):
        with pytest.raises(ConfigError):
            config().with_overrides(speed=99)

    def test_field_names_excludes_private_fields(self):
        assert "_explicit" not in RenderConfig.field_names()
        assert "input_path" in RenderConfig.field_names()
