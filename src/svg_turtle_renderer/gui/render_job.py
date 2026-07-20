"""Driving one render inside the dashboard.

The engine's own ``run`` opens a window and blocks on a click, which a dashboard
cannot allow. This runs the same pipeline stages against the embedded canvas and
the GUI clock, so the drawing appears in the panel and the event loop keeps
turning.
"""

from __future__ import annotations

from collections.abc import Callable

from svg_turtle_renderer.core.config import RenderConfig
from svg_turtle_renderer.core.engine import RenderEngine, RenderStats
from svg_turtle_renderer.core.exceptions import RenderInterrupted
from svg_turtle_renderer.gui.tk_canvas import EmbeddedTurtleCanvas, GuiClock
from svg_turtle_renderer.renderer.path_renderer import PathRenderer, sketch_distance
from svg_turtle_renderer.utils.logger import get_logger

logger = get_logger(__name__)


class GuiProgress:
    """Reports render progress to a Tk progress bar and a status line.

    Updates are throttled: the bar and label are refreshed at most a few dozen
    times a second, because repainting them on every one of thousands of tiny
    advances would itself slow the drawing down.
    """

    def __init__(
        self,
        total: float,
        unit: str,
        report: Callable[[float, float, str], None],
    ) -> None:
        """Store the total work and the callback that paints the bar."""
        self._total = max(total, 1e-9)
        self._unit = unit
        self._report = report
        self._done = 0.0
        self._last_reported = -1.0

    def advance(self, amount: float = 1.0) -> None:
        """Record work done, refreshing the display when it moves enough."""
        self._done += amount
        fraction = self._done / self._total
        # Refresh only on a visible change, so the bar never becomes the
        # bottleneck on a drawing with tens of thousands of advances.
        if fraction - self._last_reported >= 0.004:
            self._last_reported = fraction
            self._report(self._done, self._total, self._unit)

    def close(self) -> None:
        """Snap the bar to full."""
        self._report(self._total, self._total, self._unit)


def run_render(
    config: RenderConfig,
    canvas: EmbeddedTurtleCanvas,
    present: Callable[[], None],
    pump: Callable[[], None],
    should_stop: Callable[[], bool],
    report: Callable[[float, float, str], None],
) -> tuple[RenderStats, bool]:
    """Render one file onto the embedded canvas, pacing it in the event loop.

    Args:
        config: The run's settings.
        canvas: The already-open embedded canvas.
        present: Redraws the canvas.
        pump: Processes pending Tk events.
        should_stop: Returns true when the user has asked to stop.
        report: Paints the progress bar, given done, total and unit.

    Returns:
        The render statistics and whether the user stopped it early.

    """
    engine = RenderEngine(config)
    drawing = engine.parse()
    canvas.set_background(engine.background)
    size = canvas.refit()
    shapes = engine.prepare(drawing, size)

    if config.sketch:
        total = sketch_distance(shapes, config)
        unit = "px"
    else:
        total = float(len(shapes))
        unit = "shape"
    progress = GuiProgress(total, unit, report)

    clock = GuiClock(
        fps=config.fps,
        present=present,
        pump=pump,
        should_stop=should_stop,
        paced=config.sketch or config.animate,
    )
    renderer = PathRenderer(canvas, config, engine.background, clock, progress)

    stopped = False
    try:
        renderer.render(shapes)
    except RenderInterrupted:
        stopped = True
        logger.info("Render stopped by the user")
    finally:
        canvas.show_cursor(False, config.sketch_tool)
        progress.close()
        present()

    return engine.stats, stopped
