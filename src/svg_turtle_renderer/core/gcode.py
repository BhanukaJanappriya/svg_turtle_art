"""Pen-plotter G-code export.

A pen plotter draws the same thing this renderer animates: outlines, one stroke
at a time, with the pen lifted between them. That makes the parsed drawing a
natural fit for G-code. Every sub-path becomes a run of moves -- lift the pen,
travel to the start, lower the pen, trace the outline, lift again -- and fills
are simply traced as their outline, since a pen cannot fill.

The drawing is fitted to the plotter bed in millimetres with the aspect ratio
kept, and the sub-paths are ordered to shorten the pen's travel between them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from svg_turtle_renderer.core.model import Drawing
from svg_turtle_renderer.geometry.coordinate_system import Point
from svg_turtle_renderer.utils.helpers import douglas_peucker

Polyline = list[Point]


@dataclass(frozen=True, slots=True)
class GCodeOptions:
    """How to lay the drawing onto the plotter bed.

    Attributes:
        bed_width: Bed width in millimetres.
        bed_height: Bed height in millimetres.
        margin: Clear border kept on every side, in millimetres.
        feed: Drawing speed, in millimetres per minute.
        travel: Rapid speed between strokes, in millimetres per minute.
        pen_up: The command that lifts the pen.
        pen_down: The command that lowers it.
        y_up: Emit a bottom-left origin with y increasing upward (the usual
            Cartesian bed). When false, a top-left origin with y downward.
        simplify: Douglas-Peucker tolerance in millimetres; 0 keeps every point.
        optimize: Reorder sub-paths with a nearest-neighbour pass to cut travel.

    """

    bed_width: float = 210.0
    bed_height: float = 297.0
    margin: float = 10.0
    feed: float = 1000.0
    travel: float = 3000.0
    pen_up: str = "G0 Z5"
    pen_down: str = "G1 Z0"
    y_up: bool = True
    simplify: float = 0.0
    optimize: bool = True


def _fit(drawing: Drawing, options: GCodeOptions):
    """Return a function mapping user units to centred bed millimetres."""
    box = drawing.viewbox
    available_w = options.bed_width - 2 * options.margin
    available_h = options.bed_height - 2 * options.margin
    if box.width <= 0 or box.height <= 0 or available_w <= 0 or available_h <= 0:
        scale = 1.0
    else:
        scale = min(available_w / box.width, available_h / box.height)

    drawn_w = box.width * scale
    drawn_h = box.height * scale
    offset_x = (options.bed_width - drawn_w) / 2.0
    offset_y = (options.bed_height - drawn_h) / 2.0

    def to_bed(point: Point) -> Point:
        x = offset_x + (point[0] - box.min_x) * scale
        up = (point[1] - box.min_y) * scale
        # SVG y points down; a Cartesian bed points up, so it is flipped there.
        y = (offset_y + drawn_h - up) if options.y_up else (offset_y + up)
        return (x, y)

    return to_bed


def _collect(drawing: Drawing, options: GCodeOptions) -> list[Polyline]:
    """Turn every drawable sub-path into a bed-space polyline."""
    to_bed = _fit(drawing, options)
    polylines: list[Polyline] = []
    for shape in drawing.shapes:
        for subpath in shape.subpaths:
            if not subpath.is_drawable:
                continue
            points = [to_bed(p) for p in subpath.points]
            if subpath.closed:
                points.append(points[0])
            if options.simplify > 0.0:
                points = douglas_peucker(points, options.simplify)
            if len(points) >= 2:
                polylines.append(points)
    return polylines


def _order(polylines: list[Polyline]) -> list[Polyline]:
    """Reorder polylines nearest-neighbour to shorten the travel between them.

    Unlike reordering filled shapes on screen, this is always safe: a pen plotter
    has no paint order to disturb, only ink on paper, so the strokes may be drawn
    in whatever sequence covers the least empty travel.
    """
    if len(polylines) < 3:
        return polylines
    remaining = list(polylines)
    ordered = [remaining.pop(0)]
    cursor = ordered[0][-1]
    while remaining:
        best = min(
            range(len(remaining)),
            key=lambda i: _distance_squared(cursor, remaining[i][0]),
        )
        chosen = remaining.pop(best)
        ordered.append(chosen)
        cursor = chosen[-1]
    return ordered


def _distance_squared(a: Point, b: Point) -> float:
    """Return the squared distance between two points."""
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def travel_distance(polylines: list[Polyline]) -> float:
    """Return the empty (pen-up) travel between a list of strokes, in order."""
    total = 0.0
    cursor: Point | None = None
    for poly in polylines:
        if cursor is not None:
            total += math.dist(cursor, poly[0])
        cursor = poly[-1]
    return total


def to_gcode(drawing: Drawing, options: GCodeOptions | None = None) -> str:
    """Convert a parsed drawing to pen-plotter G-code.

    Args:
        drawing: The parsed document, in SVG user units.
        options: How to place it on the bed; the defaults suit an A4 plotter.

    Returns:
        The G-code as text, ready to write to a ``.gcode`` file.

    """
    options = options or GCodeOptions()
    polylines = _collect(drawing, options)
    if options.optimize:
        polylines = _order(polylines)

    out: list[str] = [
        "; Generated by SVG Turtle Renderer",
        f"; bed {options.bed_width:g} x {options.bed_height:g} mm, {len(polylines)} strokes",
        "G21 ; millimetres",
        "G90 ; absolute positioning",
        options.pen_up,
    ]

    feed = f"F{options.feed:g}"
    travel = f"F{options.travel:g}"
    for poly in polylines:
        start = poly[0]
        out.append(f"G0 X{start[0]:.3f} Y{start[1]:.3f} {travel}")
        out.append(options.pen_down)
        first = poly[1]
        out.append(f"G1 X{first[0]:.3f} Y{first[1]:.3f} {feed}")
        for x, y in poly[2:]:
            out.append(f"G1 X{x:.3f} Y{y:.3f}")
        out.append(options.pen_up)

    out.append("M2 ; end")
    return "\n".join(out) + "\n"
