"""Tests for command-line parsing.

These cover argument handling only; ``main`` is exercised for its error paths,
which is where it can be tested without opening a window.
"""

from __future__ import annotations

import json

import pytest

from svg_turtle_renderer.cli import EXIT_ERROR, EXIT_USAGE, build_config, build_parser, main


def config_for(*args):
    """Build a configuration from CLI arguments, with a dummy input path."""
    return build_config(["input.svg", *args])


class TestDefaults:
    def test_the_input_path_is_positional(self):
        assert config_for().input_path == "input.svg"

    def test_the_input_is_required(self, capsys):
        with pytest.raises(SystemExit):
            build_parser().parse_args([])

    def test_sensible_defaults(self):
        cfg = config_for()
        assert cfg.canvas_width == 1000
        assert cfg.canvas_height == 800
        assert cfg.fill is True
        assert cfg.stroke is True
        assert cfg.scale is None
        assert cfg.color_mode == "original"


class TestCanvasFlags:
    def test_width_and_height_map_onto_the_canvas(self):
        cfg = config_for("--width", "1400", "--height", "900")
        assert (cfg.canvas_width, cfg.canvas_height) == (1400, 900)

    def test_background_has_a_short_alias(self):
        assert config_for("--bg", "black").background == "black"

    def test_fullscreen_is_a_flag(self):
        assert config_for("--fullscreen").fullscreen is True

    def test_a_non_positive_width_is_refused(self):
        with pytest.raises(SystemExit):
            config_for("--width", "0")

    def test_a_non_numeric_width_is_refused(self):
        with pytest.raises(SystemExit):
            config_for("--width", "wide")


class TestScale:
    def test_a_numeric_scale(self):
        assert config_for("--scale", "2.5").scale == 2.5

    def test_auto_means_fit_automatically(self):
        assert config_for("--scale", "auto").scale is None

    def test_a_negative_scale_is_refused(self):
        with pytest.raises(SystemExit):
            config_for("--scale", "-1")

    def test_a_bad_scale_mentions_auto(self, capsys):
        with pytest.raises(SystemExit):
            config_for("--scale", "big")
        assert "auto" in capsys.readouterr().err


class TestPaintFlags:
    def test_no_fill(self):
        assert config_for("--no-fill").fill is False

    def test_no_stroke(self):
        assert config_for("--no-stroke").stroke is False

    def test_fill_can_be_asked_for_explicitly(self):
        assert config_for("--fill").fill is True

    def test_wireframe(self):
        assert config_for("--wireframe").wireframe is True

    def test_color_mode(self):
        assert config_for("--color-mode", "random").color_mode == "random"

    def test_an_unknown_color_mode_is_refused(self):
        with pytest.raises(SystemExit):
            config_for("--color-mode", "rainbow")

    def test_the_impossible_paint_combination_exits_with_a_usage_code(self, capsys):
        assert main(["input.svg", "--no-fill", "--no-stroke"]) == EXIT_USAGE
        assert "Nothing would be drawn" in capsys.readouterr().err


class TestFramingFlags:
    def test_offsets_and_rotation(self):
        cfg = config_for("--offset-x", "10", "--offset-y", "-20", "--rotate", "45")
        assert (cfg.offset_x, cfg.offset_y, cfg.rotate) == (10, -20, 45)

    def test_mirror_and_flip(self):
        cfg = config_for("--mirror", "--flip")
        assert cfg.mirror and cfg.flip

    def test_fit_mode(self):
        assert config_for("--fit", "content").fit == "content"


class TestDrawingFlags:
    def test_speed(self):
        assert config_for("--speed", "5").speed == 5

    def test_an_out_of_range_speed_is_refused(self):
        with pytest.raises(SystemExit):
            config_for("--speed", "11")

    def test_animate(self):
        assert config_for("--animate").animate is True

    def test_animation_is_accepted_as_an_alias(self):
        assert config_for("--animation").animate is True

    def test_fps(self):
        assert config_for("--fps", "60").fps == 60

    def test_hide_turtle_can_be_negated(self):
        assert config_for("--no-hide-turtle").hide_turtle is False

    def test_keep_open_can_be_negated(self):
        assert config_for("--no-keep-open").keep_open is False


class TestPencilFlags:
    def test_sketch(self):
        assert config_for("--sketch").sketch is True

    def test_pencil_speed(self):
        assert config_for("--pencil-speed", "1500").pencil_speed == 1500

    def test_duration(self):
        assert config_for("--duration", "30").duration == 30

    def test_pencil_color(self):
        assert config_for("--pencil-color", "#555").pencil_color == "#555"

    def test_pencil_width(self):
        assert config_for("--pencil-width", "2.5").pencil_width == 2.5

    def test_show_pencil_can_be_negated(self):
        assert config_for("--no-show-pencil").show_pencil is False

    def test_fill_flow_is_on_by_default(self):
        assert config_for("--sketch").fill_flow is True

    def test_fill_flow_can_be_negated(self):
        assert config_for("--sketch", "--no-fill-flow").fill_flow is False

    def test_brush_enables_sketch_and_selects_the_brush(self):
        cfg = config_for("--brush")
        assert cfg.sketch is True
        assert cfg.sketch_tool == "brush"

    def test_sketch_tool_can_be_set_explicitly(self):
        assert config_for("--sketch", "--sketch-tool", "brush").sketch_tool == "brush"

    def test_the_default_tool_is_pencil(self):
        assert config_for("--sketch").sketch_tool == "pencil"

    def test_brush_width(self):
        assert config_for("--brush", "--brush-width", "8").brush_width == 8

    def test_an_unknown_tool_is_refused(self):
        with pytest.raises(SystemExit):
            config_for("--sketch-tool", "crayon")

    def test_a_non_positive_brush_width_is_refused(self):
        with pytest.raises(SystemExit):
            config_for("--brush-width", "0")

    def test_a_non_positive_pencil_speed_is_refused(self):
        with pytest.raises(SystemExit):
            config_for("--pencil-speed", "0")

    def test_a_non_positive_duration_is_refused(self):
        with pytest.raises(SystemExit):
            config_for("--duration", "-5")


class TestOutputFlags:
    def test_export_maps_to_the_output_path(self):
        assert config_for("--export", "out.png").output_path == "out.png"

    def test_output_is_an_alias_for_export(self):
        assert config_for("--output", "out.png").output_path == "out.png"

    def test_dash_o_is_an_alias_for_export(self):
        assert config_for("-o", "out.png").output_path == "out.png"

    def test_progress_can_be_negated(self):
        assert config_for("--no-show-progress").show_progress is False

    def test_stats_verbose_and_quiet(self):
        cfg = config_for("--stats", "--verbose", "--quiet")
        assert cfg.stats and cfg.verbose and cfg.quiet

    def test_short_verbose_flag(self):
        assert config_for("-v").verbose is True


class TestThemeInteraction:
    def test_a_theme_supplies_the_background(self):
        assert config_for("--theme", "dark").background == "#11131a"

    def test_an_explicit_background_beats_the_theme(self):
        # The whole point of the None defaults: --background was typed, so the
        # theme must not overwrite it.
        assert config_for("--theme", "dark", "--background", "red").background == "red"

    def test_an_unknown_theme_is_refused(self):
        with pytest.raises(SystemExit):
            config_for("--theme", "chartreuse")


class TestConfigFile:
    def test_settings_are_read_from_the_file(self, tmp_path):
        path = tmp_path / "cfg.json"
        path.write_text(json.dumps({"canvas_width": 640, "background": "black"}))
        cfg = build_config(["input.svg", "--config", str(path)])
        assert cfg.canvas_width == 640
        assert cfg.background == "black"

    def test_a_flag_overrides_the_file(self, tmp_path):
        path = tmp_path / "cfg.json"
        path.write_text(json.dumps({"canvas_width": 640}))
        cfg = build_config(["input.svg", "--config", str(path), "--width", "1280"])
        assert cfg.canvas_width == 1280

    def test_scale_auto_overrides_a_scale_set_in_the_file(self, tmp_path):
        # 'auto' resolves to None, which is also the "unset" marker, so this is
        # the one flag that needs explicit care to survive.
        path = tmp_path / "cfg.json"
        path.write_text(json.dumps({"scale": 5.0}))
        cfg = build_config(["input.svg", "--config", str(path), "--scale", "auto"])
        assert cfg.scale is None

    def test_a_missing_config_file_exits_with_a_usage_code(self, capsys):
        assert main(["input.svg", "--config", "nope.json"]) == EXIT_USAGE
        assert "not found" in capsys.readouterr().err


class TestMainErrorHandling:
    def test_a_missing_svg_is_reported_without_a_traceback(self, capsys, caplog):
        assert main(["definitely_missing.svg", "--no-keep-open"]) == EXIT_ERROR

    def test_the_help_text_lists_examples(self, capsys):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--help"])
        assert "examples:" in capsys.readouterr().out

    def test_version_is_reported(self, capsys):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--version"])
        assert capsys.readouterr().out.strip()
