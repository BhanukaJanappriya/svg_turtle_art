"""Fitting artwork to the canvas.

:func:`build_coordinate_system` turns a source box plus the user's framing
options into the single matrix that
:class:`~svg_turtle_renderer.geometry.coordinate_system.CoordinateSystem` applies
to every vertex.
"""

from __future__ import annotations

from dataclasses import dataclass

from svg_turtle_renderer.geometry.coordinate_system import BoundingBox, CoordinateSystem, Matrix


@dataclass(frozen=True, slots=True)
class FitOptions:
    """Framing options that decide how artwork lands on the canvas.

    Attributes:
        canvas_width: Canvas width in pixels.
        canvas_height: Canvas height in pixels.
        margin: Padding kept clear on every side, in pixels.
        scale: An explicit scale factor, or ``None`` to fit automatically.
        offset_x: Horizontal nudge in pixels, applied after fitting.
        offset_y: Vertical nudge in pixels, positive being up.
        rotate: Clockwise rotation in degrees, applied about the artwork centre.
        mirror: Whether to mirror horizontally.
        flip: Whether to flip vertically.

    """

    canvas_width: int
    canvas_height: int
    margin: float = 20.0
    scale: float | None = None
    offset_x: float = 0.0
    offset_y: float = 0.0
    rotate: float = 0.0
    mirror: bool = False
    flip: bool = False


def _orientation(options: FitOptions, scale: float) -> Matrix:
    """Compose the mirror, flip, scale and rotation part of the mapping.

    The y-axis inversion that turtle needs is folded in here, after rotation, so
    that a positive ``rotate`` reads as clockwise on screen rather than being
    reversed by the flip.
    """
    sx = -scale if options.mirror else scale
    sy = -scale if options.flip else scale
    y_down_to_y_up = Matrix.scale(1.0, -1.0)
    return y_down_to_y_up @ Matrix.rotate(options.rotate) @ Matrix.scale(sx, sy)


def _fitted_scale(source: BoundingBox, options: FitOptions) -> float:
    """Return the largest scale that keeps the artwork inside the margins.

    The extent is measured *after* rotation, since a rotated box needs more
    room than its unrotated footprint, and the same aspect ratio is used on both
    axes so nothing is stretched.
    """
    available_width = options.canvas_width - 2.0 * options.margin
    available_height = options.canvas_height - 2.0 * options.margin
    if available_width <= 0.0 or available_height <= 0.0:
        return 1.0

    unit = _orientation(options, 1.0)
    corners = [
        (source.min_x, source.min_y),
        (source.max_x, source.min_y),
        (source.max_x, source.max_y),
        (source.min_x, source.max_y),
    ]
    rotated = BoundingBox.from_points(unit.apply_all(corners))
    if rotated is None or rotated.is_empty:
        return 1.0

    return min(available_width / rotated.width, available_height / rotated.height)


def build_coordinate_system(source: BoundingBox, options: FitOptions) -> CoordinateSystem:
    """Build the SVG-to-canvas mapping for a source box and framing options.

    The composed transform centres ``source`` on the origin, applies scale,
    mirror, flip and rotation, converts to turtle's y-up axes, and finally
    applies the user's pixel offset.

    Args:
        source: The region of SVG user space to frame -- normally the viewBox,
            or the artwork's own bounds when fitting to content.
        options: How the caller wants that region framed.

    Returns:
        A coordinate system ready to map vertices and stroke widths.

    """
    if source.is_empty:
        # A degenerate source (a single point, or an empty document) has no
        # meaningful scale; fall back to 1:1 about the origin rather than
        # dividing by zero.
        scale = options.scale if options.scale is not None else 1.0
    elif options.scale is not None:
        scale = options.scale
    else:
        scale = _fitted_scale(source, options)

    cx, cy = source.center
    transform = (
        Matrix.translate(options.offset_x, options.offset_y)
        @ _orientation(options, scale)
        @ Matrix.translate(-cx, -cy)
    )
    return CoordinateSystem(transform, abs(scale))
