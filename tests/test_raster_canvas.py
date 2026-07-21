"""Tests for the headless raster backend."""

from __future__ import annotations

import pytest

from svg_turtle_renderer.core.exceptions import RenderError
from svg_turtle_renderer.parser.color_parser import BLACK, WHITE, Color

pytest.importorskip("PIL")

from svg_turtle_renderer.renderer.raster_canvas import RasterCanvas  # noqa: E402


def pixel(canvas, cx, cy):
    """Return the RGB of a canvas-space point on the downscaled image."""
    image = canvas._downscaled()
    width, height = canvas.size
    return image.getpixel((round(cx + width / 2), round(height / 2 - cy)))


class TestFilling:
    def test_a_filled_square_paints_its_interior(self):
        canvas = RasterCanvas(200, 200, WHITE, supersample=1)
        canvas.fill_polygons([[(-50, -50), (50, -50), (50, 50), (-50, 50)]], Color(255, 0, 0))
        assert pixel(canvas, 0, 0) == (255, 0, 0)

    def test_the_background_shows_outside_the_shape(self):
        canvas = RasterCanvas(200, 200, WHITE, supersample=1)
        canvas.fill_polygons([[(-20, -20), (20, -20), (20, 20), (-20, 20)]], Color(255, 0, 0))
        assert pixel(canvas, 80, 80) == (255, 255, 255)

    def test_a_hole_is_left_unpainted(self):
        # Outer ring clockwise, inner counter-clockwise: even-odd cuts the hole.
        canvas = RasterCanvas(200, 200, WHITE, supersample=1)
        outer = [(-60, -60), (60, -60), (60, 60), (-60, 60)]
        hole = [(-20, 20), (20, 20), (20, -20), (-20, -20)]
        canvas.fill_polygons([outer, hole], BLACK)
        assert pixel(canvas, 0, 0) == (255, 255, 255)  # inside the hole
        assert pixel(canvas, 40, 40) == (0, 0, 0)  # in the ring

    def test_an_empty_ring_set_paints_nothing(self):
        canvas = RasterCanvas(100, 100, WHITE, supersample=1)
        canvas.fill_polygons([[(0, 0), (1, 1)]], BLACK)  # too few points
        assert pixel(canvas, 0, 0) == (255, 255, 255)


class TestStroking:
    def test_a_stroke_paints_along_its_line(self):
        canvas = RasterCanvas(200, 200, WHITE, supersample=1)
        canvas.stroke_polyline([(-80, 0), (80, 0)], BLACK, 4.0, closed=False)
        assert pixel(canvas, 0, 0) == (0, 0, 0)

    def test_a_thin_stroke_is_still_drawn(self):
        canvas = RasterCanvas(100, 100, WHITE, supersample=1)
        canvas.stroke_polyline([(-40, 0), (40, 0)], BLACK, 0.1, closed=False)
        assert pixel(canvas, 0, 0) == (0, 0, 0)

    def test_a_degenerate_stroke_is_ignored(self):
        canvas = RasterCanvas(100, 100, WHITE, supersample=1)
        canvas.stroke_polyline([(0, 0)], BLACK, 2.0, closed=False)
        assert pixel(canvas, 0, 0) == (255, 255, 255)


class TestFrameCapture:
    def test_frames_are_captured_only_when_asked(self):
        quiet = RasterCanvas(80, 80, WHITE, capture_frames=False)
        quiet.frame()
        assert quiet.frame_count == 0

        recording = RasterCanvas(80, 80, WHITE, capture_frames=True)
        recording.frame()
        recording.frame()
        assert recording.frame_count == 2

    def test_captured_frames_reflect_the_drawing_at_that_moment(self):
        # The point of capture: each frame is a snapshot, not a shared reference.
        canvas = RasterCanvas(120, 120, WHITE, supersample=1, capture_frames=True)
        canvas.frame()  # blank
        canvas.fill_polygons([[(-40, -40), (40, -40), (40, 40), (-40, 40)]], BLACK)
        canvas.frame()  # painted

        def blackness(image):
            return sum(count for count, colour in image.getcolors(1 << 20) if colour == (0, 0, 0))

        assert blackness(canvas._frames[0]) == 0
        assert blackness(canvas._frames[1]) > 0


class TestOutput:
    def test_save_png_writes_a_file(self, tmp_path):
        canvas = RasterCanvas(100, 100, WHITE)
        canvas.stroke_polyline([(-30, 0), (30, 0)], BLACK, 3.0, closed=False)
        written = canvas.save_png(tmp_path / "out.png")
        assert written.exists()

    def test_save_png_creates_missing_directories(self, tmp_path):
        canvas = RasterCanvas(80, 80, WHITE)
        written = canvas.save_png(tmp_path / "a" / "b" / "out.png")
        assert written.exists()

    def test_save_gif_writes_an_animation(self, tmp_path):
        from PIL import Image

        canvas = RasterCanvas(80, 80, WHITE, supersample=1, capture_frames=True)
        for i in range(6):
            canvas.stroke_polyline([(-30, -30 + i * 10), (30, -30 + i * 10)], BLACK, 2.0, False)
            canvas.frame()
        written = canvas.save_gif(tmp_path / "anim.gif", fps=10)
        assert written.exists()

        gif = Image.open(written)
        assert getattr(gif, "n_frames", 1) > 1

    def test_a_gif_grows_darker_as_it_is_drawn(self, tmp_path):
        # Each captured frame adds a line, so later frames have more ink.
        import numpy as np
        from PIL import Image

        canvas = RasterCanvas(100, 100, WHITE, supersample=1, capture_frames=True)
        for i in range(8):
            canvas.stroke_polyline([(-40, -40 + i * 10), (40, -40 + i * 10)], BLACK, 2.0, False)
            canvas.frame()
        written = canvas.save_gif(tmp_path / "grow.gif", fps=10)

        gif = Image.open(written)

        def black(index):
            gif.seek(index)
            return int((np.asarray(gif.copy().convert("L")) < 128).sum())

        assert black(gif.n_frames - 1) > black(0)

    def test_saving_a_gif_with_no_frames_is_an_error(self, tmp_path):
        canvas = RasterCanvas(80, 80, WHITE, capture_frames=True)
        with pytest.raises(RenderError, match="No frames"):
            canvas.save_gif(tmp_path / "empty.gif", fps=10)


class TestSupersampling:
    def test_the_reported_size_is_logical_not_supersampled(self):
        canvas = RasterCanvas(200, 150, WHITE, supersample=3)
        assert canvas.size == (200, 150)

    def test_the_saved_image_is_the_logical_size(self, tmp_path):
        from PIL import Image

        canvas = RasterCanvas(160, 120, WHITE, supersample=2)
        written = canvas.save_png(tmp_path / "s.png")
        assert Image.open(written).size == (160, 120)
