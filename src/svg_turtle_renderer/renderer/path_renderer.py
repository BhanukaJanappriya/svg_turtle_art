"""Drawing shapes onto a canvas.

This is where paint decisions live: which colour a shape ends up, whether it is
filled, stroked or both, and in what order. It works entirely in canvas pixels
against the :class:`~svg_turtle_renderer.renderer.canvas.Canvas` protocol, so it
never touches turtle and can be exercised headless.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from svg_turtle_renderer.core.config import RenderConfig
from svg_turtle_renderer.core.model import Shape
from svg_turtle_renderer.geometry.fill_rule import group_rings
from svg_turtle_renderer.geometry.polyline import chunks_by_length, polyline_length
from svg_turtle_renderer.parser.color_parser import BLACK, Color, hsl_to_rgb, parse_color
from svg_turtle_renderer.renderer.animation import Clock
from svg_turtle_renderer.renderer.canvas import Canvas
from svg_turtle_renderer.utils.logger import get_logger
from svg_turtle_renderer.utils.progress import NullProgress, Progress

logger = get_logger(__name__)

# Below this width a stroke is invisible on screen anyway, and turtle would
# still round it up to one pixel, so it is worth culling early.
_MIN_STROKE_WIDTH = 0.05


class PathRenderer:
    """Paints shapes onto a canvas according to a configuration.

    Args:
        canvas: The surface to draw on.
        config: The run's settings.
        background: The page colour, used to flatten partial transparency.
        clock: The frame clock; a disabled clock renders instantly.
        progress: Where to report work done. The renderer reports its own
            progress rather than being wrapped in a bar, so the unit can match
            what is happening -- shapes when painting, pixels when sketching.

    """

    def __init__(
        self,
        canvas: Canvas,
        config: RenderConfig,
        background: Color,
        clock: Clock | None = None,
        progress: Progress | None = None,
    ) -> None:
        """Store collaborators and pre-resolve the mono/wireframe colour."""
        self._canvas = canvas
        self._config = config
        self._background = background
        self._clock = clock
        self._progress = progress if progress is not None else NullProgress()
        self._mono = parse_color(config.mono_color) or BLACK
        # None means "trace each shape in its own ink"; see _pencil_color.
        self._pencil = parse_color(config.pencil_color) if config.pencil_color else None
        if self._pencil is not None:
            self._pencil = self._pencil.composite_over(background)
        # Pixels of pencil travel per frame, set when a sketch starts.
        self._step = 1.0
        # Seeded rather than global, so a random-colour render is reproducible
        # within a run and does not disturb the caller's random state.
        self._random = random.Random(0xC0FFEE)

    def render(self, shapes: Sequence[Shape]) -> int:
        """Draw every shape and return how many were painted.

        Args:
            shapes: The shapes to draw, in paint order, in canvas pixels.

        Returns:
            The number of shapes that produced at least one drawing operation.

        """
        sketching = self._config.sketch
        if sketching:
            self._step = self._sketch_step(shapes)
            self._canvas.show_cursor(self._config.show_pencil)

        if self._clock is not None:
            self._clock.start()

        painted = 0
        for shape in shapes:
            drew = self._sketch_shape(shape) if sketching else self._draw_shape(shape)
            if drew:
                painted += 1
            if not sketching:
                # Painting a shape is one unit of work; a sketch reports its own
                # progress as the pencil moves, since a single shape can take a
                # minute to draw.
                self._progress.advance()
                if self._clock is not None:
                    self._clock.tick()

        if sketching:
            self._canvas.show_cursor(False)
        if self._clock is not None:
            self._clock.final()
        return painted

    # ------------------------------------------------------------------
    # Pencil sketching
    # ------------------------------------------------------------------

    def _sketch_step(self, shapes: Sequence[Shape]) -> float:
        """Return how far the pencil advances per frame, in pixels.

        Without ``--duration`` the configured speed is used directly. With it, the
        step is solved from the distance the pencil must cover -- but distance
        alone under-predicts the time, because every sub-path ends in a partial
        chunk (half a frame wasted, on average) and every fill costs a frame of
        its own. A drawing of many small sub-paths is dominated by that overhead:
        ignoring it made a two-second request take three.
        """
        fps = max(self._config.fps, 1)
        if self._config.duration is None:
            return max(self._config.pencil_speed / fps, 0.01)

        total = 0.0
        subpaths = 0
        fills = 0
        for shape in shapes:
            for subpath in shape.subpaths:
                if subpath.is_drawable:
                    total += subpath.trace_length
                    subpaths += 1
            if shape.style.fill is not None and self._config.fill:
                fills += 1

        if total <= 0.0:
            return 1.0

        budget = self._config.duration * fps
        overhead = 0.5 * subpaths + fills

        # Each sub-path costs at least one frame however fast the pencil moves,
        # and each fill one more, so this is the floor no step size can beat.
        minimum_frames = subpaths + fills
        if budget < minimum_frames:
            logger.warning(
                "--duration %.3gs is shorter than this drawing can be sketched. "
                "It needs at least %.1fs at %d fps, because each of its %d "
                "sub-paths costs a frame. Raise --fps, or ask for longer.",
                self._config.duration,
                minimum_frames / fps,
                fps,
                subpaths,
            )
            return total

        drawing_frames = max(budget - overhead, 1.0)

        step = total / drawing_frames
        logger.debug(
            "Sketching %.0f px over %.3gs: %.2f px/frame at %d fps "
            "(%.0f frames drawing, %.0f overhead)",
            total,
            self._config.duration,
            step,
            fps,
            drawing_frames,
            overhead,
        )
        return max(step, 0.01)

    def _sketch_shape(self, shape: Shape) -> bool:
        """Trace a shape's outline with the pencil, then paint it.

        The outline is traced whatever the document says, which is the whole
        point: a fill-only shape has no stroke to follow, but the pencil still
        has to draw its edge or there would be nothing to watch.
        """
        fill_color, stroke_color, stroke_width = self._resolve(shape)
        pencil = self._pencil_color(shape, fill_color, stroke_color)
        drew = False

        for subpath in shape.subpaths:
            points = subpath.closed_points
            if len(points) < 2:
                continue
            for chunk in chunks_by_length(points, self._step):
                self._canvas.stroke_polyline(chunk, pencil, self._config.pencil_width, False)
                # Progress is the distance actually drawn, which is what the
                # viewer is watching. Counting shapes would leave the bar at 0%
                # for the whole sketch of a single-path drawing.
                self._progress.advance(polyline_length(chunk))
                if self._clock is not None:
                    self._clock.tick()
            drew = True

        # Paint the shape properly once its outline exists, so the sketch fills
        # in behind the pencil line rather than replacing it.
        if fill_color is not None:
            rings = [sp.points for sp in shape.subpaths if len(sp.points) >= 3]
            for group in group_rings(rings, even_odd=shape.style.even_odd):
                self._canvas.fill_polygons(group, fill_color)
                drew = True
            if self._clock is not None:
                self._clock.tick()

        if stroke_color is not None:
            for subpath in shape.subpaths:
                if subpath.is_drawable:
                    self._canvas.stroke_polyline(
                        subpath.points, stroke_color, stroke_width, subpath.closed
                    )
                    drew = True
        return drew

    def _pencil_color(
        self, shape: Shape, fill_color: Color | None, stroke_color: Color | None
    ) -> Color:
        """Choose the colour the pencil traces with.

        Defaulting to the shape's own ink keeps a coloured drawing coherent while
        it is being sketched; ``--pencil-color`` forces a single graphite line
        over the whole picture instead.
        """
        if self._pencil is not None:
            return self._pencil
        ink = stroke_color or fill_color
        if ink is None:
            return self._mono.composite_over(self._background)
        return ink

    def _draw_shape(self, shape: Shape) -> bool:
        """Draw one shape, returning whether anything was painted."""
        fill_color, stroke_color, stroke_width = self._resolve(shape)
        drew = False

        # Fill first, then stroke, so a stroke sits on top of its own fill --
        # the paint order SVG specifies.
        if fill_color is not None:
            rings = [sp.points for sp in shape.subpaths if len(sp.points) >= 3]
            # The backend only fills even-odd, so a nonzero shape is split into
            # groups that produce the same result under even-odd.
            for group in group_rings(rings, even_odd=shape.style.even_odd):
                self._canvas.fill_polygons(group, fill_color)
                drew = True

        if stroke_color is not None:
            for subpath in shape.subpaths:
                if subpath.is_drawable:
                    self._canvas.stroke_polyline(
                        subpath.points, stroke_color, stroke_width, subpath.closed
                    )
                    drew = True
        return drew

    def _resolve(self, shape: Shape) -> tuple[Color | None, Color | None, float]:
        """Decide the final fill, stroke and stroke width for a shape.

        Returns:
            The opaque fill colour or ``None``, the opaque stroke colour or
            ``None``, and the stroke width in pixels.

        """
        config = self._config

        if config.wireframe:
            # Wireframe ignores the document's paint entirely: every shape
            # becomes a hairline outline in one colour.
            return None, self._wireframe_color(shape), 1.0

        style = shape.style
        fill = style.fill if config.fill else None
        stroke = style.stroke if config.stroke else None
        width = style.stroke_width

        # A filled shape with no stroke of its own would vanish entirely in
        # stroke-only mode, so it gets a hairline outline in its fill colour
        # rather than being dropped. This tests the *document's* fill, not the
        # local `fill`, which --no-fill has already cleared.
        if config.stroke and not config.fill and stroke is None and style.fill is not None:
            stroke = style.fill
            width = 1.0

        if config.color_mode == "mono":
            fill = self._mono if fill is not None else None
            stroke = self._mono if stroke is not None else None
        elif config.color_mode == "random":
            random_color = self._random_color()
            fill = random_color if fill is not None else None
            stroke = random_color if stroke is not None else None

        if stroke is not None and width < _MIN_STROKE_WIDTH:
            stroke = None

        # Turtle has no alpha, so anything translucent is flattened onto the page
        # colour here, at the last possible moment.
        flat_fill = fill.composite_over(self._background) if fill is not None else None
        flat_stroke = stroke.composite_over(self._background) if stroke is not None else None
        return flat_fill, flat_stroke, width

    def _wireframe_color(self, shape: Shape) -> Color:
        """Return the outline colour for a shape in wireframe mode."""
        if self._config.color_mode == "random":
            return self._random_color()
        return self._mono

    def _random_color(self) -> Color:
        """Return a random colour that stays legible against the background.

        Fully random RGB drifts towards muddy mid-greys and can land on the page
        colour. Sampling a saturated hue and steering the lightness away from the
        background keeps every shape distinct and visible.
        """
        hue = self._random.uniform(0.0, 360.0)
        saturation = self._random.uniform(0.55, 0.95)
        luminance = (
            0.2126 * self._background.r + 0.7152 * self._background.g + 0.0722 * self._background.b
        ) / 255.0
        lightness = (
            self._random.uniform(0.25, 0.45)
            if luminance > 0.5
            else self._random.uniform(0.55, 0.75)
        )
        r, g, b = hsl_to_rgb(hue, saturation, lightness)
        return Color(r, g, b)
