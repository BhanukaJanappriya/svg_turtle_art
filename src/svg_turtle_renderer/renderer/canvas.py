"""The drawing surface abstraction.

:class:`PathRenderer` talks to a :class:`Canvas`, never to turtle directly. That
keeps the drawing logic -- fill rules, stroke order, colour modes -- testable
without a display, and leaves room for another backend later.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from svg_turtle_renderer.geometry.coordinate_system import Point
from svg_turtle_renderer.parser.color_parser import Color


@runtime_checkable
class Canvas(Protocol):
    """A surface that can fill polygons and stroke polylines in canvas pixels."""

    def fill_polygons(self, rings: Sequence[Sequence[Point]], color: Color) -> None:
        """Fill one shape, which may be made of several rings.

        All rings belong to a single fill operation so that a compound path --
        a ring, a letter ``O`` -- can render its holes.

        Args:
            rings: The closed rings, each without a repeated closing point.
            color: The opaque fill colour.

        """
        ...

    def stroke_polyline(
        self, points: Sequence[Point], color: Color, width: float, closed: bool
    ) -> None:
        """Stroke a single polyline.

        Args:
            points: The vertices to trace.
            color: The opaque stroke colour.
            width: The stroke width in pixels.
            closed: Whether to return to the first point.

        """
        ...

    def frame(self) -> None:
        """Mark a point where a partially drawn image may be presented."""
        ...

    def show_cursor(self, visible: bool) -> None:
        """Show or hide the drawing cursor at the pen's position.

        Only meaningful while a drawing is being watched: the cursor is what
        makes the pencil sketch effect look like a hand rather than an image
        appearing.
        """
        ...


@dataclass
class FillRecord:
    """One recorded call to :meth:`Canvas.fill_polygons`."""

    rings: list[list[Point]]
    color: Color


@dataclass
class StrokeRecord:
    """One recorded call to :meth:`Canvas.stroke_polyline`."""

    points: list[Point]
    color: Color
    width: float
    closed: bool


@dataclass
class RecordingCanvas:
    """A canvas that records drawing calls instead of painting them.

    Used by the test suite to assert on what the pipeline *would* draw, and
    usable as a dry-run backend.
    """

    fills: list[FillRecord] = field(default_factory=list)
    strokes: list[StrokeRecord] = field(default_factory=list)
    frames: int = 0
    cursor_visible: bool = False

    def fill_polygons(self, rings: Sequence[Sequence[Point]], color: Color) -> None:
        """Record a fill."""
        self.fills.append(FillRecord([list(ring) for ring in rings], color))

    def stroke_polyline(
        self, points: Sequence[Point], color: Color, width: float, closed: bool
    ) -> None:
        """Record a stroke."""
        self.strokes.append(StrokeRecord(list(points), color, width, closed))

    def frame(self) -> None:
        """Record a frame boundary."""
        self.frames += 1

    def show_cursor(self, visible: bool) -> None:
        """Record the cursor's visibility."""
        self.cursor_visible = visible
