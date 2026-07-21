"""Tests for headless still and animation export."""

from __future__ import annotations

import pytest

from svg_turtle_renderer.core.config import RenderConfig

pytest.importorskip("PIL")

from svg_turtle_renderer.core.export import export, is_animation  # noqa: E402

SQUARE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <rect x="10" y="10" width="80" height="80" fill="red" stroke="blue" stroke-width="3"/>
</svg>"""


class TestIsAnimation:
    def test_gif_is_an_animation(self):
        assert is_animation("out.gif")
        assert is_animation("OUT.GIF")

    def test_a_still_is_not(self):
        assert not is_animation("out.png")
        assert not is_animation("out.jpg")


class TestStillExport:
    def test_it_writes_a_png_with_no_window(self, svg_file, tmp_path):
        from PIL import Image

        path = svg_file(SQUARE)
        out = tmp_path / "still.png"
        config = RenderConfig(
            input_path=path,
            show_progress=False,
            keep_open=False,
            canvas_width=200,
            canvas_height=200,
        )
        export(config, str(out))
        assert Image.open(out).size == (200, 200)

    def test_the_still_contains_the_fill_colour(self, svg_file, tmp_path):
        from PIL import Image

        path = svg_file(SQUARE)
        out = tmp_path / "still.png"
        config = RenderConfig(
            input_path=path,
            show_progress=False,
            keep_open=False,
            canvas_width=200,
            canvas_height=200,
        )
        export(config, str(out))
        colours = {c for _n, c in Image.open(out).convert("RGB").getcolors(maxcolors=100000)}
        assert (255, 0, 0) in colours  # the red fill made it onto the canvas


class TestAnimationExport:
    def test_a_gif_has_many_progressive_frames(self, svg_file, tmp_path):
        import numpy as np
        from PIL import Image

        path = svg_file(SQUARE)
        out = tmp_path / "anim.gif"
        config = RenderConfig(
            input_path=path,
            sketch=True,
            duration=1.0,
            fps=20,
            show_progress=False,
            keep_open=False,
            canvas_width=160,
            canvas_height=160,
        )
        export(config, str(out))

        gif = Image.open(out)
        assert gif.n_frames > 2

        def ink(index):
            gif.seek(index)
            return int((np.asarray(gif.copy().convert("L")) < 128).sum())

        # The finished drawing has more ink than the first frame.
        assert ink(gif.n_frames - 1) > ink(0)

    def test_a_gif_forces_a_sketch_even_without_the_flag(self, svg_file, tmp_path):
        # Exporting to .gif should animate, so the drawing is progressive even
        # when the caller did not ask for a sketch.
        from PIL import Image

        path = svg_file(SQUARE)
        out = tmp_path / "auto.gif"
        config = RenderConfig(
            input_path=path,
            sketch=False,
            duration=1.0,
            fps=20,
            show_progress=False,
            keep_open=False,
            canvas_width=160,
            canvas_height=160,
        )
        export(config, str(out))
        assert Image.open(out).n_frames > 2

    def test_the_brush_records_too(self, svg_file, tmp_path):
        from PIL import Image

        path = svg_file(SQUARE)
        out = tmp_path / "brush.gif"
        config = RenderConfig(
            input_path=path,
            sketch=True,
            sketch_tool="brush",
            duration=1.0,
            fps=20,
            show_progress=False,
            keep_open=False,
            canvas_width=160,
            canvas_height=160,
        )
        export(config, str(out))
        assert Image.open(out).n_frames > 2

    def test_export_reports_a_frame_count(self, svg_file, tmp_path):
        path = svg_file(SQUARE)
        config = RenderConfig(
            input_path=path,
            sketch=True,
            duration=1.0,
            fps=20,
            show_progress=False,
            keep_open=False,
            canvas_width=160,
            canvas_height=160,
        )
        stats = export(config, str(tmp_path / "f.gif"))
        assert stats.frames > 0
