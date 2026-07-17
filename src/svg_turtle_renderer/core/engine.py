"""The rendering pipeline.

:class:`RenderEngine` owns the sequence -- parse, fit, transform, simplify,
order, draw -- and nothing else. Each stage lives in its own module; the engine
just decides what runs and in what order, and collects the statistics.

The stages before drawing are exposed through :meth:`RenderEngine.prepare`, which
needs no window. That is what makes the whole pipeline testable on a machine with
no display.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import TypeVar

from svg_turtle_renderer.core.config import RenderConfig
from svg_turtle_renderer.core.exceptions import RenderError, SVGTurtleError
from svg_turtle_renderer.core.model import Drawing, Shape, SubPath
from svg_turtle_renderer.geometry.coordinate_system import CoordinateSystem, Point
from svg_turtle_renderer.geometry.scaler import FitOptions, build_coordinate_system
from svg_turtle_renderer.parser.color_parser import WHITE, Color, parse_color
from svg_turtle_renderer.parser.svg_parser import SVGParser
from svg_turtle_renderer.renderer.animation import Clock, FrameClock, SketchClock
from svg_turtle_renderer.renderer.canvas import Canvas
from svg_turtle_renderer.renderer.path_renderer import PathRenderer
from svg_turtle_renderer.renderer.turtle_renderer import TurtleCanvas
from svg_turtle_renderer.utils.helpers import douglas_peucker, format_duration
from svg_turtle_renderer.utils.logger import get_logger
from svg_turtle_renderer.utils.progress import Progress, make_progress

logger = get_logger(__name__)

T = TypeVar("T")


@dataclass(slots=True)
class RenderStats:
    """What a render did, and how long each stage took."""

    shape_count: int = 0
    vertex_count: int = 0
    vertices_before_simplify: int = 0
    color_count: int = 0
    shapes_painted: int = 0
    frames: int = 0
    canvas_size: tuple[int, int] = (0, 0)
    scale_factor: float = 1.0
    pen_travel: float = 0.0
    parse_seconds: float = 0.0
    prepare_seconds: float = 0.0
    render_seconds: float = 0.0
    total_seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def format_report(self) -> str:
        """Return a human-readable multi-line summary."""
        reduction = ""
        if self.vertices_before_simplify > self.vertex_count:
            saved = self.vertices_before_simplify - self.vertex_count
            percent = 100.0 * saved / self.vertices_before_simplify
            reduction = f"  (simplified away {saved:,}, {percent:.1f}%)"

        lines = [
            "Render statistics",
            f"  shapes         {self.shape_count:,} ({self.shapes_painted:,} painted)",
            f"  vertices       {self.vertex_count:,}{reduction}",
            f"  distinct colors{self.color_count:>6,}",
            f"  canvas         {self.canvas_size[0]}x{self.canvas_size[1]} px",
            f"  scale          {self.scale_factor:.4g}x",
            f"  pen travel     {self.pen_travel:,.0f} px",
            f"  frames         {self.frames:,}",
            f"  parse          {format_duration(self.parse_seconds)}",
            f"  prepare        {format_duration(self.prepare_seconds)}",
            f"  render         {format_duration(self.render_seconds)}",
            f"  total          {format_duration(self.total_seconds)}",
        ]
        return "\n".join(lines)


class RenderEngine:
    """Runs a configured render from an SVG file to a turtle window.

    The canvas is injected rather than constructed inline, so a caller -- or a
    test -- can supply a recording backend and drive the whole pipeline without a
    display.

    Args:
        config: The run's settings.
        canvas_factory: Builds the canvas given a background colour. Defaults to
            a real turtle window.

    """

    def __init__(
        self,
        config: RenderConfig,
        canvas_factory: Callable[[Color], Canvas] | None = None,
    ) -> None:
        """Store the configuration and resolve the background colour."""
        self._config = config
        self._canvas_factory = canvas_factory
        self._background = parse_color(config.background) or WHITE
        if self._background.a < 1.0:
            # A translucent page has nothing behind it to blend with.
            self._background = replace(self._background, a=1.0)
        self._stats = RenderStats()

    @property
    def background(self) -> Color:
        """Return the resolved page colour."""
        return self._background

    @property
    def stats(self) -> RenderStats:
        """Return the statistics gathered by the most recent run."""
        return self._stats

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------

    def parse(self) -> Drawing:
        """Parse the input file into a drawing in SVG user units."""
        started = time.perf_counter()
        parser = SVGParser(resolution=self._config.resolution, strict=self._config.strict)
        drawing = parser.parse_file(self._config.input_path)
        self._stats.parse_seconds = time.perf_counter() - started

        if not drawing.shapes:
            logger.warning(
                "%s contains no drawable shapes. Text, gradients and embedded "
                "images are not supported; the window will be blank.",
                self._config.input_path,
            )
        return drawing

    def fit(self, drawing: Drawing, canvas_size: tuple[int, int]) -> CoordinateSystem:
        """Build the mapping from the drawing's user space onto the canvas."""
        source = drawing.viewbox
        if self._config.fit == "content":
            content = drawing.content_bounds()
            if content is not None and not content.is_empty:
                source = content
            else:
                logger.warning("--fit content: no content bounds found, using the viewBox")

        options = FitOptions(
            canvas_width=canvas_size[0],
            canvas_height=canvas_size[1],
            margin=self._config.margin,
            scale=self._config.scale,
            offset_x=self._config.offset_x,
            offset_y=self._config.offset_y,
            rotate=self._config.rotate,
            mirror=self._config.mirror,
            flip=self._config.flip,
        )
        return build_coordinate_system(source, options)

    def prepare(self, drawing: Drawing, canvas_size: tuple[int, int]) -> list[Shape]:
        """Turn a parsed drawing into canvas-space shapes ready to draw.

        Runs the fit, the coordinate transform, optional simplification and
        optional path ordering. No window is required.

        Args:
            drawing: The parsed document.
            canvas_size: The canvas width and height in pixels.

        Returns:
            The shapes, in paint order, with every point in canvas pixels.

        """
        started = time.perf_counter()
        system = self.fit(drawing, canvas_size)
        self._stats.scale_factor = system.scale_factor
        self._stats.canvas_size = canvas_size

        shapes = self._transform(drawing.shapes, system)
        self._stats.vertices_before_simplify = sum(s.vertex_count for s in shapes)

        if self._config.simplify > 0.0:
            shapes = self._simplify(shapes)
        if self._config.optimize_order:
            shapes = self._optimize_order(shapes)

        self._stats.shape_count = len(shapes)
        self._stats.vertex_count = sum(s.vertex_count for s in shapes)
        self._stats.color_count = self._count_colors(shapes)
        self._stats.pen_travel = self._pen_travel(shapes)
        self._stats.prepare_seconds = time.perf_counter() - started
        return shapes

    def _transform(self, shapes: Sequence[Shape], system: CoordinateSystem) -> list[Shape]:
        """Map every shape from user space into canvas pixels."""
        result: list[Shape] = []
        for shape in shapes:
            subpaths = [
                SubPath(points=system.all_to_canvas(sp.points), closed=sp.closed)
                for sp in shape.subpaths
            ]
            style = replace(shape.style, stroke_width=system.scale_length(shape.style.stroke_width))
            result.append(replace(shape, subpaths=subpaths, style=style))
        return result

    def _simplify(self, shapes: Sequence[Shape]) -> list[Shape]:
        """Drop vertices that do not change the silhouette.

        The tolerance is in canvas pixels, so it means the same thing whatever
        the source document's scale, and a sub-pixel tolerance genuinely cannot
        change what is displayed.
        """
        tolerance = self._config.simplify
        result: list[Shape] = []
        for shape in shapes:
            subpaths = []
            for subpath in shape.subpaths:
                points = douglas_peucker(subpath.points, tolerance)
                # Simplification must not destroy a fillable ring.
                minimum = 3 if subpath.closed else 2
                if len(points) >= minimum:
                    subpaths.append(SubPath(points=points, closed=subpath.closed))
                elif subpath.is_drawable:
                    subpaths.append(subpath)
            if subpaths:
                result.append(replace(shape, subpaths=subpaths))
        return result

    def _optimize_order(self, shapes: Sequence[Shape]) -> list[Shape]:
        """Reorder shapes with a nearest-neighbour pass to shorten pen travel.

        This is only safe when nothing overlaps, because reordering changes which
        shape is painted on top. It is therefore opt-in, and it is refused
        outright when the drawing has fills -- for a stroke-only plot it can cut
        travel substantially, but on filled artwork it would silently rearrange
        the picture.
        """
        if any(shape.style.fill is not None for shape in shapes):
            message = (
                "--optimize-order was ignored: the drawing has filled shapes, and "
                "reordering them would change which shape is painted on top"
            )
            logger.warning(message)
            self._stats.warnings.append(message)
            return list(shapes)

        remaining = list(shapes)
        if len(remaining) < 3:
            return remaining

        ordered: list[Shape] = [remaining.pop(0)]
        cursor = self._end_point(ordered[0])
        while remaining:
            best_index = min(
                range(len(remaining)),
                key=lambda i: _distance_squared(cursor, self._start_point(remaining[i])),
            )
            chosen = remaining.pop(best_index)
            ordered.append(chosen)
            cursor = self._end_point(chosen)
        return ordered

    @staticmethod
    def _start_point(shape: Shape) -> Point:
        """Return where the pen first lands for a shape."""
        for subpath in shape.subpaths:
            if subpath.points:
                return subpath.points[0]
        return (0.0, 0.0)

    @staticmethod
    def _end_point(shape: Shape) -> Point:
        """Return where the pen finishes for a shape."""
        for subpath in reversed(shape.subpaths):
            if subpath.points:
                return subpath.points[0] if subpath.closed else subpath.points[-1]
        return (0.0, 0.0)

    @staticmethod
    def _count_colors(shapes: Sequence[Shape]) -> int:
        """Count the distinct colours the drawing uses."""
        colors: set[tuple[int, int, int]] = set()
        for shape in shapes:
            for color in (shape.style.fill, shape.style.stroke):
                if color is not None:
                    colors.add((color.r, color.g, color.b))
        return len(colors)

    def _pen_travel(self, shapes: Sequence[Shape]) -> float:
        """Estimate total pen travel in pixels, including moves between shapes."""
        total = 0.0
        cursor: Point | None = None
        for shape in shapes:
            for subpath in shape.subpaths:
                if not subpath.points:
                    continue
                if cursor is not None:
                    total += math.dist(cursor, subpath.points[0])
                for a, b in zip(subpath.points, subpath.points[1:], strict=False):
                    total += math.dist(a, b)
                cursor = subpath.points[0] if subpath.closed else subpath.points[-1]
        return total

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def run(self) -> RenderStats:
        """Execute the full pipeline and return its statistics.

        Raises:
            SVGTurtleError: If parsing, configuration or rendering fails.

        """
        started = time.perf_counter()
        drawing = self.parse()

        canvas = self._build_canvas()
        try:
            canvas_size = self._canvas_size(canvas)
            shapes = self.prepare(drawing, canvas_size)
            self._draw(canvas, shapes)
            self._finish(canvas)
        finally:
            self._stats.total_seconds = time.perf_counter() - started
        return self._stats

    def _build_canvas(self) -> Canvas:
        """Create the drawing surface, honouring an injected factory."""
        if self._canvas_factory is not None:
            return self._canvas_factory(self._background)
        return TurtleCanvas(
            width=self._config.canvas_width,
            height=self._config.canvas_height,
            background=self._background,
            fullscreen=self._config.fullscreen,
            speed=self._config.turtle_speed,
            title=f"SVG Turtle Renderer - {self._config.input_path}",
        )

    def _canvas_size(self, canvas: Canvas) -> tuple[int, int]:
        """Open a real window if needed, and report the size it granted."""
        if isinstance(canvas, TurtleCanvas):
            return canvas.open()
        return (self._config.canvas_width, self._config.canvas_height)

    def _draw(self, canvas: Canvas, shapes: Sequence[Shape]) -> None:
        """Run the drawing stage, translating interruption into a clean stop."""
        clock: Clock
        if self._config.sketch:
            # A sketch is paced by distance and must wait between frames; an
            # animation is paced by shapes and drops frames to keep up.
            clock = SketchClock(fps=self._config.fps, present=canvas.frame)
        else:
            clock = FrameClock(
                fps=self._config.fps,
                present=canvas.frame,
                enabled=self._config.animate,
            )
        progress = self._build_progress(shapes)
        renderer = PathRenderer(canvas, self._config, self._background, clock, progress)

        started = time.perf_counter()
        try:
            self._stats.shapes_painted = renderer.render(shapes)
        except KeyboardInterrupt:
            # A half-finished drawing is a perfectly good thing to keep, so the
            # partial image is presented rather than discarded.
            logger.warning("Interrupted; showing the partial drawing")
            canvas.frame()
        finally:
            progress.close()
            self._stats.render_seconds = time.perf_counter() - started
            self._stats.frames = clock.frames_presented

    def _build_progress(self, shapes: Sequence[Shape]) -> Progress:
        """Create a progress bar that counts the work the user is watching.

        Painting counts shapes, because that is what happens one after another.
        Sketching counts pixels of pencil travel: a sketch may be a single path
        drawn over a minute, and a bar reading "0/1 shapes" for that whole minute
        reports nothing at all.
        """
        if self._config.sketch:
            return make_progress(
                enabled=self._config.show_progress,
                total=sum(shape.trace_length for shape in shapes),
                description="Sketching",
                unit="px",
                unit_scale=True,
            )
        return make_progress(
            enabled=self._config.show_progress,
            total=len(shapes),
            description="Rendering",
            unit="shape",
        )

    def _finish(self, canvas: Canvas) -> None:
        """Export, reveal the cursor and wait, as configured."""
        if not isinstance(canvas, TurtleCanvas):
            return

        if self._config.output_path:
            try:
                canvas.export(self._config.output_path)
            except SVGTurtleError as exc:
                # An export failure must not throw away a drawing that rendered
                # perfectly well, so it is reported and the window stays up.
                logger.error("Export failed: %s", exc)
                self._stats.warnings.append(f"Export failed: {exc}")

        if not self._config.hide_turtle:
            canvas.show_turtle()

        if self._config.keep_open:
            logger.info("Click the window to close it")
            canvas.wait_for_click()
        else:
            canvas.close()


def _distance_squared(a: Point, b: Point) -> float:
    """Return the squared distance between two points."""
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def render_file(config: RenderConfig) -> RenderStats:
    """Render one file with a throwaway engine.

    Raises:
        RenderError: If no drawing surface can be opened.
        SVGTurtleError: On any other failure in the pipeline.

    """
    return RenderEngine(config).run()


__all__ = ["RenderEngine", "RenderStats", "RenderError", "render_file"]
