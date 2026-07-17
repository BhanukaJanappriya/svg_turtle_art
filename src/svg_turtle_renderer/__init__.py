"""Universal SVG Turtle Renderer.

A modular engine that converts SVG artwork into Python Turtle Graphics output.

The public surface is intentionally small::

    from svg_turtle_renderer import RenderConfig, RenderEngine

    engine = RenderEngine(RenderConfig(input_path="artwork.svg"))
    engine.run()
"""

from svg_turtle_renderer.core.config import RenderConfig
from svg_turtle_renderer.core.engine import RenderEngine
from svg_turtle_renderer.core.exceptions import (
    ColorError,
    InvalidSVGError,
    PathSyntaxError,
    RenderError,
    SVGTurtleError,
    TransformError,
)

__version__ = "0.1.0"

__all__ = [
    "ColorError",
    "InvalidSVGError",
    "PathSyntaxError",
    "RenderConfig",
    "RenderEngine",
    "RenderError",
    "SVGTurtleError",
    "TransformError",
    "__version__",
]
