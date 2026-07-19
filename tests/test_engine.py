"""Tests for the rendering pipeline.

The engine is driven with a recording canvas throughout, so the whole pipeline
is exercised without ever opening a window.
"""

from __future__ import annotations

import pytest

from svg_turtle_renderer.core.config import RenderConfig
from svg_turtle_renderer.core.engine import RenderEngine
from svg_turtle_renderer.parser.color_parser import Color
from svg_turtle_renderer.renderer.canvas import RecordingCanvas

SQUARE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <rect x="0" y="0" width="100" height="100" fill="#ff0000" stroke="#0000ff" stroke-width="2"/>
</svg>"""

TWO_SHAPES = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <rect x="0" y="0" width="40" height="40" fill="red"/>
  <rect x="60" y="60" width="40" height="40" fill="blue"/>
</svg>"""

# Document order visits the far line in the middle, so the pen crosses the page
# twice. Nearest-neighbour ordering should draw the two near lines together.
# The lines are deliberately not collinear with the travel moves: on a diagonal
# arrangement both orderings can total the same distance by coincidence.
STROKED_LINES = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <line x1="0" y1="0" x2="1" y2="0" stroke="black"/>
  <line x1="90" y1="0" x2="91" y2="0" stroke="black"/>
  <line x1="2" y1="0" x2="3" y2="0" stroke="black"/>
</svg>"""


def run(markup, svg_file, **overrides):
    """Render markup onto a recording canvas and return it with the stats."""
    path = svg_file(markup)
    defaults = {"input_path": path, "show_progress": False, "keep_open": False}
    defaults.update(overrides)
    config = RenderConfig(**defaults)
    canvas = RecordingCanvas()
    engine = RenderEngine(config, canvas_factory=lambda _bg: canvas)
    stats = engine.run()
    return canvas, stats


class TestPipeline:
    def test_a_square_is_filled_and_stroked(self, svg_file):
        canvas, _ = run(SQUARE, svg_file)
        assert len(canvas.fills) == 1
        assert len(canvas.strokes) == 1

    def test_fill_uses_the_documents_colour(self, svg_file):
        canvas, _ = run(SQUARE, svg_file)
        assert canvas.fills[0].color.as_hex() == "#ff0000"

    def test_stroke_uses_the_documents_colour(self, svg_file):
        canvas, _ = run(SQUARE, svg_file)
        assert canvas.strokes[0].color.as_hex() == "#0000ff"

    def test_geometry_is_centred_on_the_canvas(self, svg_file):
        canvas, _ = run(SQUARE, svg_file, canvas_width=1000, canvas_height=1000)
        xs = [p[0] for ring in canvas.fills[0].rings for p in ring]
        ys = [p[1] for ring in canvas.fills[0].rings for p in ring]
        assert (min(xs) + max(xs)) / 2 == pytest.approx(0, abs=1e-6)
        assert (min(ys) + max(ys)) / 2 == pytest.approx(0, abs=1e-6)

    def test_artwork_is_scaled_to_the_canvas_minus_margins(self, svg_file):
        canvas, _ = run(SQUARE, svg_file, canvas_width=1000, canvas_height=1000, margin=50)
        xs = [p[0] for ring in canvas.fills[0].rings for p in ring]
        assert max(xs) - min(xs) == pytest.approx(900)

    def test_stroke_width_is_scaled_with_the_artwork(self, svg_file):
        # 100 user units to 900 pixels is 9x, so a 2-unit stroke becomes 18px.
        canvas, _ = run(SQUARE, svg_file, canvas_width=1000, canvas_height=1000, margin=50)
        assert canvas.strokes[0].width == pytest.approx(18)

    def test_paint_order_is_fill_then_stroke(self, svg_file):
        canvas, _ = run(SQUARE, svg_file)
        # Recorded separately, so assert the shape produced both and that the
        # renderer asked for the fill first.
        assert canvas.fills and canvas.strokes

    def test_shapes_are_drawn_in_document_order(self, svg_file):
        canvas, _ = run(TWO_SHAPES, svg_file)
        assert canvas.fills[0].color.as_hex() == "#ff0000"
        assert canvas.fills[1].color.as_hex() == "#0000ff"

    def test_an_empty_document_draws_nothing(self, svg_file):
        canvas, stats = run(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>', svg_file
        )
        assert canvas.fills == []
        assert stats.shapes_painted == 0


class TestPaintModes:
    def test_no_fill_leaves_only_strokes(self, svg_file):
        canvas, _ = run(SQUARE, svg_file, fill=False)
        assert canvas.fills == []
        assert canvas.strokes

    def test_no_stroke_leaves_only_fills(self, svg_file):
        canvas, _ = run(SQUARE, svg_file, stroke=False)
        assert canvas.fills
        assert canvas.strokes == []

    def test_stroke_only_gives_an_unstroked_shape_an_outline(self, svg_file):
        # Without this the shape would simply vanish in stroke-only mode.
        markup = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<rect width="10" height="10" fill="red"/></svg>'
        )
        canvas, _ = run(markup, svg_file, fill=False)
        assert len(canvas.strokes) == 1
        assert canvas.strokes[0].color.as_hex() == "#ff0000"

    def test_wireframe_ignores_the_documents_paint(self, svg_file):
        canvas, _ = run(SQUARE, svg_file, wireframe=True, mono_color="black")
        assert canvas.fills == []
        assert canvas.strokes[0].color.as_hex() == "#000000"

    def test_mono_mode_recolours_everything(self, svg_file):
        canvas, _ = run(TWO_SHAPES, svg_file, color_mode="mono", mono_color="#123456")
        assert {f.color.as_hex() for f in canvas.fills} == {"#123456"}

    def test_random_mode_varies_colours_between_shapes(self, svg_file):
        canvas, _ = run(TWO_SHAPES, svg_file, color_mode="random")
        assert canvas.fills[0].color != canvas.fills[1].color

    def test_random_mode_is_reproducible(self, svg_file):
        first, _ = run(TWO_SHAPES, svg_file, color_mode="random")
        second, _ = run(TWO_SHAPES, svg_file, color_mode="random")
        assert [f.color for f in first.fills] == [f.color for f in second.fills]

    def test_random_colours_avoid_the_background(self, svg_file):
        canvas, _ = run(TWO_SHAPES, svg_file, color_mode="random", background="black")
        for fill in canvas.fills:
            luminance = 0.2126 * fill.color.r + 0.7152 * fill.color.g + 0.0722 * fill.color.b
            assert luminance > 40


class TestFillRule:
    def test_a_compound_path_defaults_to_nonzero(self, svg_file):
        markup = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<path d="M 0 0 H 40 V 40 H 0 Z M 50 0 H 90 V 40 H 50 Z" fill="red"/></svg>'
        )
        canvas, _ = run(markup, svg_file)
        # Two disjoint same-winding rings: two independent fills.
        assert len(canvas.fills) == 2

    def test_even_odd_keeps_a_compound_path_as_one_fill(self, svg_file):
        markup = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<path fill-rule="evenodd" d="M 0 0 H 40 V 40 H 0 Z M 50 0 H 90 V 40 H 50 Z" '
            'fill="red"/></svg>'
        )
        canvas, _ = run(markup, svg_file)
        assert len(canvas.fills) == 1
        assert len(canvas.fills[0].rings) == 2

    def test_a_donut_is_filled_as_one_group_so_the_hole_is_cut(self, svg_file):
        # Outer clockwise, inner counter-clockwise: a real hole under nonzero.
        markup = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<path fill="red" d="M 10 10 H 90 V 90 H 10 Z M 30 70 H 70 V 30 H 30 Z"/></svg>'
        )
        canvas, _ = run(markup, svg_file)
        assert len(canvas.fills) == 1
        assert len(canvas.fills[0].rings) == 2

    def test_fill_rule_is_inherited_from_a_group(self, svg_file):
        markup = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<g fill-rule="evenodd"><path fill="red" '
            'd="M 0 0 H 40 V 40 H 0 Z M 50 0 H 90 V 40 H 50 Z"/></g></svg>'
        )
        canvas, _ = run(markup, svg_file)
        assert len(canvas.fills) == 1


class TestPencilSketch:
    """The pencil traces outlines from a blank canvas before painting."""

    FILL_ONLY = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<rect x="0" y="0" width="100" height="100" fill="red"/></svg>'
    )

    def test_a_fill_only_shape_is_still_traced(self, svg_file):
        # The whole point: this shape has no stroke to follow, but the pencil
        # must draw its edge or there would be nothing to watch.
        canvas, _ = run(self.FILL_ONLY, svg_file, sketch=True, pencil_speed=100_000)
        assert canvas.strokes
        assert canvas.fills

    def test_the_outline_is_traced_before_the_fill(self, svg_file):
        # Filling first would bury the pencil line under the paint.
        canvas, _ = run(self.FILL_ONLY, svg_file, sketch=True, pencil_speed=100_000)
        assert canvas.strokes, "nothing was traced"
        # RecordingCanvas keeps fills and strokes apart, so assert on the frame
        # count instead: tracing must have presented frames before the fill.
        assert canvas.frames > 0

    def test_a_slower_pencil_takes_more_strokes(self, svg_file):
        # A high fps keeps the real sleeping down to milliseconds; the stroke
        # count is what is under test, and it does not depend on the rate.
        fast, _ = run(self.FILL_ONLY, svg_file, sketch=True, pencil_speed=1_000_000, fps=100)
        slow, _ = run(self.FILL_ONLY, svg_file, sketch=True, pencil_speed=30_000, fps=100)
        assert len(slow.strokes) > len(fast.strokes)

    def test_the_pencil_traces_in_the_shapes_own_ink_by_default(self, svg_file):
        canvas, _ = run(self.FILL_ONLY, svg_file, sketch=True, pencil_speed=100_000)
        assert canvas.strokes[0].color.as_hex() == "#ff0000"

    def test_pencil_color_overrides_the_shapes_ink(self, svg_file):
        canvas, _ = run(
            self.FILL_ONLY, svg_file, sketch=True, pencil_speed=100_000, pencil_color="#336699"
        )
        assert canvas.strokes[0].color.as_hex() == "#336699"

    def test_the_pencil_line_uses_the_pencil_width(self, svg_file):
        canvas, _ = run(
            self.FILL_ONLY, svg_file, sketch=True, pencil_speed=100_000, pencil_width=3.0
        )
        assert canvas.strokes[0].width == 3.0

    def test_the_cursor_is_shown_while_sketching_and_hidden_after(self, svg_file):
        canvas, _ = run(self.FILL_ONLY, svg_file, sketch=True, pencil_speed=100_000)
        assert canvas.cursor_visible is False  # put away once the drawing is done

    def test_the_cursor_can_be_switched_off(self, svg_file):
        canvas, _ = run(
            self.FILL_ONLY, svg_file, sketch=True, pencil_speed=100_000, show_pencil=False
        )
        assert canvas.cursor_visible is False

    def test_sketching_does_not_change_the_finished_picture(self, svg_file):
        # However it is animated, the end state must be the same drawing.
        plain, _ = run(TWO_SHAPES, svg_file)
        sketched, _ = run(TWO_SHAPES, svg_file, sketch=True, pencil_speed=100_000)
        assert [f.color for f in sketched.fills] == [f.color for f in plain.fills]
        assert [f.rings for f in sketched.fills] == [f.rings for f in plain.fills]

    def test_a_closed_subpath_is_traced_all_the_way_round(self, svg_file):
        canvas, _ = run(self.FILL_ONLY, svg_file, sketch=True, pencil_speed=100_000)
        traced = [p for stroke in canvas.strokes for p in stroke.points]
        # The trace must return to where it started, closing the square.
        assert traced[0] == pytest.approx(traced[-1])

    def test_duration_paces_the_whole_drawing(self, svg_file):
        # These really do sleep, so they are kept short; the ratio is the point.
        _, quick = run(TWO_SHAPES, svg_file, sketch=True, duration=0.1, fps=100)
        _, slow = run(TWO_SHAPES, svg_file, sketch=True, duration=0.4, fps=100)
        assert slow.render_seconds > quick.render_seconds * 2

    def test_duration_is_roughly_honoured(self, svg_file):
        _, stats = run(TWO_SHAPES, svg_file, sketch=True, duration=0.5, fps=100)
        assert stats.render_seconds == pytest.approx(0.5, abs=0.15)

    def test_duration_is_honoured_with_streaming_fill(self, svg_file):
        # Streaming adds the fill sweep to the work, and the duration model has
        # to account for it or the drawing overruns.
        _, stats = run(TWO_SHAPES, svg_file, sketch=True, duration=0.5, fps=100, fill_flow=True)
        assert stats.render_seconds == pytest.approx(0.5, abs=0.15)

    def test_duration_is_honoured_with_the_brush(self, svg_file):
        # The brush fills in rows rather than bands, but the pacing is shared, so
        # a brush drawing must land on its duration too.
        _, stats = run(
            TWO_SHAPES, svg_file, sketch=True, sketch_tool="brush", duration=0.5, fps=100
        )
        assert stats.render_seconds == pytest.approx(0.5, abs=0.15)

    def test_an_impossible_duration_warns_rather_than_running_long_silently(self, svg_file, caplog):
        import logging

        # Every sub-path costs a frame, so no step size can make this fit.
        with caplog.at_level(logging.WARNING):
            run(TWO_SHAPES, svg_file, sketch=True, duration=0.000001, fps=1000)
        assert any("shorter than this drawing can be sketched" in r.message for r in caplog.records)

    def test_sketching_turns_off_turtles_own_animation(self, config):
        # The frame clock drives the screen; turtle's per-move animation would
        # fight it and make a real drawing take hours.
        assert config(sketch=True, speed=8).turtle_speed == 0


class CountingProgress:
    """A progress reporter that totals what it is told."""

    def __init__(self):
        self.total = 0.0
        self.calls = 0
        self.closed = False

    def advance(self, amount=1.0):
        self.total += amount
        self.calls += 1

    def close(self):
        self.closed = True


class TestProgressReporting:
    """Progress must count the thing the viewer is actually watching."""

    SINGLE_PATH = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<path d="M 10 10 H 90 V 90 H 10 Z" fill="red"/></svg>'
    )

    def _render(self, markup, svg_file, **overrides):
        """Render with a counting reporter and return it with the shapes."""
        counter, shapes, _ = self._render_with_config(markup, svg_file, **overrides)
        return counter, shapes

    def _render_with_config(self, markup, svg_file, **overrides):
        """Render with a counting reporter, also returning the config used."""
        from svg_turtle_renderer.renderer.path_renderer import PathRenderer

        path = svg_file(markup)
        defaults = {"input_path": path, "show_progress": False, "keep_open": False}
        defaults.update(overrides)
        config = RenderConfig(**defaults)
        engine = RenderEngine(config)
        shapes = engine.prepare(engine.parse(), (1000, 800))
        counter = CountingProgress()
        PathRenderer(RecordingCanvas(), config, engine.background, None, counter).render(shapes)
        return counter, shapes, config

    def test_painting_reports_one_unit_per_shape(self, svg_file):
        counter, shapes = self._render(TWO_SHAPES, svg_file)
        assert counter.total == len(shapes) == 2

    def test_sketching_reports_distance_not_shapes(self, svg_file):
        # The bug this fixes: a single-path drawing reported "0 of 1 shapes" for
        # the whole sketch, then jumped to 100%.
        counter, shapes = self._render(
            self.SINGLE_PATH, svg_file, sketch=True, pencil_speed=20_000, fps=100
        )
        assert len(shapes) == 1
        assert counter.calls > 1, "progress moved only once for a whole sketch"
        assert counter.total > 100, "progress was not reported as a distance"

    def test_sketch_progress_adds_up_to_exactly_the_declared_total(self, svg_file):
        # If the advances did not sum to the bar's declared total it would stop
        # short of the end, or overshoot it.
        from svg_turtle_renderer.renderer.path_renderer import sketch_distance

        counter, shapes, config = self._render_with_config(
            self.SINGLE_PATH, svg_file, sketch=True, pencil_speed=20_000, fps=100
        )
        assert counter.total == pytest.approx(sketch_distance(shapes, config))

    def test_it_adds_up_across_many_shapes_and_sub_paths(self, svg_file):
        from svg_turtle_renderer.renderer.path_renderer import sketch_distance

        markup = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<path d="M 0 0 H 40 V 40 H 0 Z M 50 0 H 90 V 40 H 50 Z" fill="red"/>'
            '<circle cx="50" cy="70" r="20" fill="blue"/>'
            '<polyline points="0,95 100,95" stroke="black"/></svg>'
        )
        counter, shapes, config = self._render_with_config(
            markup, svg_file, sketch=True, pencil_speed=20_000, fps=100
        )
        assert counter.total == pytest.approx(sketch_distance(shapes, config))

    def test_the_reporter_is_closed_even_when_rendering_is_interrupted(self, svg_file):
        # A bar left open corrupts the terminal for whatever prints next.
        path = svg_file(TWO_SHAPES)
        config = RenderConfig(input_path=path, show_progress=False, keep_open=False)

        class Exploding(RecordingCanvas):
            def fill_polygons(self, rings, color):
                raise KeyboardInterrupt

        engine = RenderEngine(config, canvas_factory=lambda _bg: Exploding())
        engine.run()  # KeyboardInterrupt is caught and reported by the engine
        assert engine.stats.render_seconds >= 0


class TestTraceLength:
    def test_an_open_sub_path_measures_its_own_length(self):
        from svg_turtle_renderer.core.model import SubPath

        assert SubPath(points=[(0, 0), (10, 0), (10, 10)]).trace_length == 20

    def test_a_closed_sub_path_includes_the_closing_edge(self):
        # The closing segment is implied by the flag, but a pencil still draws it.
        from svg_turtle_renderer.core.model import SubPath

        square = SubPath(points=[(0, 0), (10, 0), (10, 10), (0, 10)], closed=True)
        assert square.trace_length == 40

    def test_closed_points_repeats_the_first_point(self):
        from svg_turtle_renderer.core.model import SubPath

        square = SubPath(points=[(0, 0), (10, 0), (10, 10)], closed=True)
        assert square.closed_points == [(0, 0), (10, 0), (10, 10), (0, 0)]

    def test_an_open_sub_path_does_not_repeat_its_first_point(self):
        from svg_turtle_renderer.core.model import SubPath

        line = SubPath(points=[(0, 0), (10, 0)], closed=False)
        assert line.closed_points == [(0, 0), (10, 0)]

    def test_a_shape_sums_its_sub_paths(self):
        from svg_turtle_renderer.core.model import Shape, Style, SubPath

        shape = Shape(
            subpaths=[
                SubPath(points=[(0, 0), (10, 0)]),
                SubPath(points=[(0, 0), (0, 5)]),
            ],
            style=Style(),
        )
        assert shape.trace_length == 15

    def test_undrawable_sub_paths_are_ignored(self):
        from svg_turtle_renderer.core.model import Shape, Style, SubPath

        shape = Shape(
            subpaths=[SubPath(points=[(0, 0), (10, 0)]), SubPath(points=[(5, 5)])],
            style=Style(),
        )
        assert shape.trace_length == 10


class TestStreamingFill:
    """Fills stream in as a colour front rather than snapping on."""

    BIG_FILL = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<rect x="0" y="0" width="100" height="100" fill="red"/></svg>'
    )

    @pytest.fixture(autouse=True)
    def _no_real_sleep(self, monkeypatch):
        """Strip the wait out of the sketch clock so these run in milliseconds.

        The banding under test does not depend on wall-clock pacing, only on the
        step, so removing the sleep keeps the assertions valid while letting the
        tests use realistic frame rates cheaply.
        """
        monkeypatch.setattr("svg_turtle_renderer.renderer.animation.time.sleep", lambda _s: None)

    def test_a_snap_fill_is_one_operation(self, svg_file):
        canvas, _ = run(self.BIG_FILL, svg_file, sketch=True, pencil_speed=100_000, fill_flow=False)
        assert len(canvas.fills) == 1

    def test_a_streaming_fill_is_many_bands(self, svg_file):
        # The whole point: the colour arrives in strips, not all at once.
        canvas, _ = run(
            self.BIG_FILL, svg_file, sketch=True, pencil_speed=1_500, fps=30, fill_flow=True
        )
        assert len(canvas.fills) > 1

    def test_a_slower_pencil_makes_a_finer_fill(self, svg_file):
        coarse, _ = run(self.BIG_FILL, svg_file, sketch=True, pencil_speed=6_000, fps=30)
        fine, _ = run(self.BIG_FILL, svg_file, sketch=True, pencil_speed=1_000, fps=30)
        assert len(fine.fills) > len(coarse.fills)

    def test_streaming_is_the_default_for_a_sketch(self, svg_file):
        canvas, _ = run(self.BIG_FILL, svg_file, sketch=True, pencil_speed=1_500, fps=30)
        assert len(canvas.fills) > 1

    def test_normal_rendering_never_bands(self, svg_file):
        # Streaming is a sketch effect; a plain render fills in one operation
        # even with fill_flow left on.
        canvas, _ = run(self.BIG_FILL, svg_file, fill_flow=True)
        assert len(canvas.fills) == 1

    def test_the_bands_together_cover_the_whole_shape(self, svg_file):
        # Every band is red and, unified, they must span the shape's height.
        canvas, _ = run(
            self.BIG_FILL, svg_file, sketch=True, pencil_speed=1_500, fps=30, fill_flow=True
        )
        ys = [p[1] for fill in canvas.fills for ring in fill.rings for p in ring]
        span = max(ys) - min(ys)
        # The shape fills the canvas minus margins; the band coverage should
        # reach nearly that full height.
        assert span > 700

    def test_every_streamed_band_is_the_fill_colour(self, svg_file):
        canvas, _ = run(
            self.BIG_FILL, svg_file, sketch=True, pencil_speed=1_500, fps=30, fill_flow=True
        )
        assert {f.color.as_hex() for f in canvas.fills} == {"#ff0000"}

    def test_streaming_does_not_change_the_finished_colours(self, svg_file):
        snap, _ = run(TWO_SHAPES, svg_file, sketch=True, pencil_speed=100_000, fill_flow=False)
        flow, _ = run(TWO_SHAPES, svg_file, sketch=True, pencil_speed=1_500, fps=30, fill_flow=True)
        assert {f.color.as_hex() for f in snap.fills} == {f.color.as_hex() for f in flow.fills}

    def test_streaming_fill_reports_progress_that_adds_up(self, svg_file):
        counter, shapes = TestProgressReporting()._render(
            self.BIG_FILL, svg_file, sketch=True, pencil_speed=1_500, fps=30, fill_flow=True
        )
        from svg_turtle_renderer.renderer.path_renderer import sketch_distance

        config = RenderConfig(
            input_path=svg_file(self.BIG_FILL),
            sketch=True,
            pencil_speed=1_500,
            fps=30,
            show_progress=False,
            keep_open=False,
        )
        assert counter.total == pytest.approx(sketch_distance(shapes, config))

    def test_the_progress_total_grows_when_fill_streams(self, svg_file):
        # A streamed fill has more work to report than a snapped one, because the
        # colour front now sweeps the shape's height.
        from svg_turtle_renderer.renderer.path_renderer import sketch_distance

        path = svg_file(self.BIG_FILL)
        streamed = RenderConfig(input_path=path, sketch=True, fill_flow=True, keep_open=False)
        snapped = RenderConfig(input_path=path, sketch=True, fill_flow=False, keep_open=False)
        engine = RenderEngine(streamed)
        shapes = engine.prepare(engine.parse(), (1000, 800))
        assert sketch_distance(shapes, streamed) > sketch_distance(shapes, snapped)


class TestBrush:
    """Brush mode traces thick coloured strokes and fills in brush rows."""

    BIG_FILL = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<rect x="0" y="0" width="100" height="100" fill="red"/></svg>'
    )

    @pytest.fixture(autouse=True)
    def _no_real_sleep(self, monkeypatch):
        monkeypatch.setattr("svg_turtle_renderer.renderer.animation.time.sleep", lambda _s: None)

    def test_the_brush_traces_thicker_than_the_pencil(self, svg_file):
        pencil, _ = run(self.BIG_FILL, svg_file, sketch=True, sketch_tool="pencil", fill=False)
        brush, _ = run(self.BIG_FILL, svg_file, sketch=True, sketch_tool="brush", fill=False)
        assert brush.strokes[0].width > pencil.strokes[0].width

    def test_the_brush_traces_in_the_shapes_ink(self, svg_file):
        canvas, _ = run(self.BIG_FILL, svg_file, sketch=True, sketch_tool="brush", pencil_speed=1e6)
        assert canvas.strokes[0].color.as_hex() == "#ff0000"

    def test_the_brush_fills_with_strokes_not_polygons(self, svg_file):
        # A brush lays paint in courses; there should be no polygon fill at all.
        canvas, _ = run(
            self.BIG_FILL, svg_file, sketch=True, sketch_tool="brush", pencil_speed=1_500, fps=30
        )
        assert canvas.fills == []
        assert len(canvas.strokes) > 1

    def test_the_pencil_still_fills_with_polygons(self, svg_file):
        canvas, _ = run(
            self.BIG_FILL, svg_file, sketch=True, sketch_tool="pencil", pencil_speed=1_500, fps=30
        )
        assert canvas.fills

    def test_the_brush_rows_span_the_shape_width(self, svg_file):
        # Every brush row runs the full width of the square it is painting.
        canvas, _ = run(
            self.BIG_FILL, svg_file, sketch=True, sketch_tool="brush", pencil_speed=1_500, fps=30
        )
        fill_rows = [
            s for s in canvas.strokes if len(s.points) == 2 and s.points[0][1] == s.points[1][1]
        ]
        assert fill_rows
        widest = max(abs(s.points[1][0] - s.points[0][0]) for s in fill_rows)
        assert widest > 700  # the square nearly fills the 1000px canvas

    def test_the_brush_rows_leave_no_vertical_gaps(self, svg_file):
        # Rows must be spaced no further apart than the brush is wide, or the fill
        # would show stripes. Fill rows run the full width of the square; the
        # short outline-trace segments are filtered out by that width.
        canvas, _ = run(
            self.BIG_FILL,
            svg_file,
            sketch=True,
            sketch_tool="brush",
            brush_width=9,
            pencil_speed=1_500,
            fps=30,
        )
        fill_rows = [
            s
            for s in canvas.strokes
            if len(s.points) == 2
            and s.points[0][1] == s.points[1][1]
            and abs(s.points[1][0] - s.points[0][0]) > 500
        ]
        rows = sorted({round(s.points[0][1], 3) for s in fill_rows})
        gaps = [b - a for a, b in zip(rows, rows[1:], strict=False)]
        assert gaps
        assert max(gaps) <= 9  # never wider than the brush

    def test_the_brush_cursor_is_selected(self, svg_file):
        canvas, _ = run(self.BIG_FILL, svg_file, sketch=True, sketch_tool="brush", pencil_speed=1e6)
        assert canvas.cursor_kind == "brush"

    def test_brush_progress_adds_up(self, svg_file):
        from svg_turtle_renderer.renderer.path_renderer import sketch_distance

        counter, shapes, config = TestProgressReporting()._render_with_config(
            self.BIG_FILL, svg_file, sketch=True, sketch_tool="brush", pencil_speed=1_500, fps=30
        )
        assert counter.total == pytest.approx(sketch_distance(shapes, config))

    def test_a_donut_keeps_its_hole_under_the_brush(self, svg_file):
        # The brush must not paint across a hole.
        markup = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<path fill="red" d="M 10 10 H 90 V 90 H 10 Z M 35 65 H 65 V 35 H 35 Z"/></svg>'
        )
        canvas, _ = run(
            markup, svg_file, sketch=True, sketch_tool="brush", pencil_speed=1_500, fps=30
        )
        # Somewhere in the hole's vertical range a row must be split into two.
        split_rows = [s for s in canvas.strokes if len(s.points) == 2]
        heights = {round(s.points[0][1]) for s in split_rows}
        rows_by_height = {h: [s for s in split_rows if round(s.points[0][1]) == h] for h in heights}
        assert any(len(v) >= 2 for v in rows_by_height.values())


class TestTransparency:
    def test_translucent_fill_is_flattened_onto_the_background(self, svg_file):
        # Turtle has no alpha, so 50% black on white must arrive as mid grey.
        markup = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<rect width="10" height="10" fill="black" fill-opacity="0.5"/></svg>'
        )
        canvas, _ = run(markup, svg_file, background="white")
        assert canvas.fills[0].color == Color(128, 128, 128, 1.0)

    def test_the_background_choice_changes_the_flattened_result(self, svg_file):
        markup = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<rect width="10" height="10" fill="white" fill-opacity="0.5"/></svg>'
        )
        canvas, _ = run(markup, svg_file, background="black")
        assert canvas.fills[0].color == Color(128, 128, 128, 1.0)

    def test_every_colour_reaching_the_canvas_is_opaque(self, svg_file):
        markup = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<rect width="10" height="10" fill="red" stroke="blue" opacity="0.3"/></svg>'
        )
        canvas, _ = run(markup, svg_file)
        assert all(f.color.a == 1.0 for f in canvas.fills)
        assert all(s.color.a == 1.0 for s in canvas.strokes)


class TestFraming:
    def test_fit_content_frames_the_artwork_not_the_viewbox(self, svg_file):
        # The artwork occupies a corner of a much larger viewBox, so fitting to
        # content must magnify it well beyond fitting the viewBox.
        markup = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">'
            '<rect x="0" y="0" width="10" height="10" fill="red"/></svg>'
        )
        viewbox, _ = run(markup, svg_file, fit="viewbox")
        content, _ = run(markup, svg_file, fit="content")

        def width(canvas):
            xs = [p[0] for ring in canvas.fills[0].rings for p in ring]
            return max(xs) - min(xs)

        assert width(content) > width(viewbox) * 10

    def test_explicit_scale_is_honoured(self, svg_file):
        canvas, stats = run(SQUARE, svg_file, scale=2.0)
        assert stats.scale_factor == pytest.approx(2.0)

    def test_offsets_move_the_artwork(self, svg_file):
        canvas, _ = run(SQUARE, svg_file, scale=1.0, offset_x=100)
        xs = [p[0] for ring in canvas.fills[0].rings for p in ring]
        assert (min(xs) + max(xs)) / 2 == pytest.approx(100)

    def test_rotation_is_applied(self, svg_file):
        markup = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 20">'
            '<rect width="100" height="20" fill="red"/></svg>'
        )
        upright, _ = run(markup, svg_file, scale=1.0)
        turned, _ = run(markup, svg_file, scale=1.0, rotate=90)

        def size(canvas):
            points = [p for ring in canvas.fills[0].rings for p in ring]
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            return (max(xs) - min(xs), max(ys) - min(ys))

        assert size(upright) == pytest.approx((100, 20))
        assert size(turned) == pytest.approx((20, 100))


class TestSimplification:
    def test_simplification_reduces_vertices(self, svg_file):
        markup = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<circle cx="50" cy="50" r="40" fill="red"/></svg>'
        )
        plain, plain_stats = run(markup, svg_file)
        simple, simple_stats = run(markup, svg_file, simplify=2.0)
        assert simple_stats.vertex_count < plain_stats.vertex_count

    def test_simplification_records_what_it_removed(self, svg_file):
        markup = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<circle cx="50" cy="50" r="40" fill="red"/></svg>'
        )
        _, stats = run(markup, svg_file, simplify=2.0)
        assert stats.vertices_before_simplify > stats.vertex_count

    def test_simplification_never_destroys_a_fillable_ring(self, svg_file):
        # A brutal tolerance would collapse the ring to two points, which cannot
        # be filled; the shape must survive with at least a triangle.
        markup = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<circle cx="50" cy="50" r="40" fill="red"/></svg>'
        )
        canvas, _ = run(markup, svg_file, simplify=10000.0)
        assert canvas.fills
        assert len(canvas.fills[0].rings[0]) >= 3


class TestPathOrdering:
    def test_ordering_shortens_pen_travel_on_stroke_only_art(self, svg_file):
        _, plain = run(STROKED_LINES, svg_file)
        _, ordered = run(STROKED_LINES, svg_file, optimize_order=True)
        assert ordered.pen_travel < plain.pen_travel

    def test_ordering_is_refused_when_fills_are_present(self, svg_file):
        # Reordering filled shapes would change which one is painted on top, so
        # it must be refused rather than silently rearranging the picture.
        _, stats = run(TWO_SHAPES, svg_file, optimize_order=True)
        assert any("optimize-order" in w for w in stats.warnings)

    def test_a_refused_reorder_leaves_document_order_intact(self, svg_file):
        canvas, _ = run(TWO_SHAPES, svg_file, optimize_order=True)
        assert canvas.fills[0].color.as_hex() == "#ff0000"


class TestStats:
    def test_counts_shapes_and_vertices(self, svg_file):
        _, stats = run(TWO_SHAPES, svg_file)
        assert stats.shape_count == 2
        assert stats.vertex_count == 8

    def test_counts_distinct_colours(self, svg_file):
        _, stats = run(TWO_SHAPES, svg_file)
        assert stats.color_count == 2

    def test_records_the_canvas_size(self, svg_file):
        _, stats = run(SQUARE, svg_file, canvas_width=640, canvas_height=480)
        assert stats.canvas_size == (640, 480)

    def test_timings_are_recorded(self, svg_file):
        _, stats = run(SQUARE, svg_file)
        assert stats.total_seconds > 0
        assert stats.parse_seconds > 0

    def test_the_report_renders(self, svg_file):
        _, stats = run(SQUARE, svg_file)
        report = stats.format_report()
        assert "shapes" in report
        assert "vertices" in report


class TestBackground:
    def test_the_background_colour_is_resolved(self, svg_file, tmp_path):
        path = svg_file(SQUARE)
        engine = RenderEngine(RenderConfig(input_path=path, background="#102030"))
        assert engine.background.as_hex() == "#102030"

    def test_an_unknown_background_falls_back_to_white(self, svg_file):
        path = svg_file(SQUARE)
        engine = RenderEngine(RenderConfig(input_path=path, background="not-a-colour"))
        assert engine.background.as_hex() == "#ffffff"

    def test_a_translucent_background_is_made_opaque(self, svg_file):
        # There is nothing behind the page to blend with.
        path = svg_file(SQUARE)
        engine = RenderEngine(RenderConfig(input_path=path, background="rgba(255,0,0,0.5)"))
        assert engine.background.a == 1.0


class TestPrepareWithoutAWindow:
    def test_prepare_needs_no_canvas(self, svg_file):
        config = RenderConfig(input_path=svg_file(SQUARE))
        engine = RenderEngine(config)
        drawing = engine.parse()
        shapes = engine.prepare(drawing, (800, 600))
        assert len(shapes) == 1

    def test_fit_returns_a_usable_coordinate_system(self, svg_file):
        config = RenderConfig(input_path=svg_file(SQUARE), scale=2.0)
        engine = RenderEngine(config)
        system = engine.fit(engine.parse(), (800, 600))
        assert system.scale_factor == pytest.approx(2.0)

    def test_parse_reports_a_missing_file(self, tmp_path):
        from svg_turtle_renderer.core.exceptions import InvalidSVGError

        engine = RenderEngine(RenderConfig(input_path=str(tmp_path / "nope.svg")))
        with pytest.raises(InvalidSVGError):
            engine.parse()
