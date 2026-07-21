"""Headless export to a still image or an animated GIF.

This renders straight into a Pillow image with no window, so it works on a server
and needs no Ghostscript. A ``.gif`` target records the drawing being made frame
by frame; any other target saves the finished image.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from svg_turtle_renderer.core.config import RenderConfig
from svg_turtle_renderer.core.engine import RenderEngine, RenderStats
from svg_turtle_renderer.renderer.animation import CaptureClock
from svg_turtle_renderer.renderer.path_renderer import PathRenderer, sketch_distance
from svg_turtle_renderer.renderer.raster_canvas import RasterCanvas
from svg_turtle_renderer.utils.logger import get_logger
from svg_turtle_renderer.utils.progress import make_progress

logger = get_logger(__name__)


def is_animation(path: str) -> bool:
    """Report whether a path names an animated format."""
    return Path(path).suffix.lower() == ".gif"


def export(config: RenderConfig, path: str) -> RenderStats:
    """Render ``config``'s file to ``path`` without opening a window.

    A ``.gif`` records the drawing as it is made, so it is always drawn in sketch
    mode; every other extension saves the finished still.

    Args:
        config: The run's settings.
        path: The destination file. ``.gif`` records an animation; ``.png`` (or
            any other image extension Pillow knows) saves the final frame.

    Returns:
        The render statistics.

    """
    animate = is_animation(path)
    # A GIF has to show the drawing happening, so force a sketch when the caller
    # did not ask for one; a still just needs the finished image.
    if animate and not config.sketch:
        config = replace(config, sketch=True, _explicit=frozenset(config.field_names()))

    engine = RenderEngine(config)
    drawing = engine.parse()
    size = (config.canvas_width, config.canvas_height)
    shapes = engine.prepare(drawing, size)

    canvas = RasterCanvas(size[0], size[1], engine.background, capture_frames=animate)
    clock = CaptureClock(canvas.frame) if animate else None

    total = sketch_distance(shapes, config) if config.sketch else float(len(shapes))
    progress = make_progress(
        enabled=config.show_progress,
        total=total,
        description="Recording" if animate else "Rendering",
        unit="px" if config.sketch else "shape",
        unit_scale=config.sketch,
    )

    renderer = PathRenderer(canvas, config, engine.background, clock, progress)
    try:
        renderer.render(shapes)
    finally:
        progress.close()

    stats = engine.stats
    if clock is not None:
        stats.frames = clock.frames_presented
    if animate:
        canvas.save_gif(path, config.fps)
    else:
        canvas.save_png(path)
    return stats
