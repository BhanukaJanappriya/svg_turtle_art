"""Exception hierarchy for the renderer.

Every error raised deliberately by this package derives from :class:`SVGTurtleError`,
so an embedding application can catch the whole family with a single ``except``.
"""

from __future__ import annotations


class SVGTurtleError(Exception):
    """Base class for every error raised by this package."""


class InvalidSVGError(SVGTurtleError):
    """The input file is missing, unreadable, not XML, or not an SVG document."""


class PathSyntaxError(SVGTurtleError):
    """A ``d`` attribute could not be tokenised into valid path commands."""


class TransformError(SVGTurtleError):
    """A ``transform`` attribute could not be parsed into a matrix."""


class ColorError(SVGTurtleError):
    """A paint value could not be resolved to an RGB triple."""


class ConfigError(SVGTurtleError):
    """The supplied configuration is internally inconsistent."""


class RenderError(SVGTurtleError):
    """The rendering backend failed, typically because no display is available."""


class RenderInterrupted(SVGTurtleError):
    """The user asked to stop a render in progress.

    Not an error: it is how the dashboard's Stop button unwinds a drawing that is
    partway through, leaving whatever was drawn on the canvas.
    """
