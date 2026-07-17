"""The domain model shared by the parser and the renderer.

The parser's job is to reduce an SVG document to a flat list of :class:`Shape`
objects, each already resolved to polylines and concrete colours. The renderer
then knows nothing about XML, and the geometry layer knows nothing about either.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from svg_turtle_renderer.geometry.coordinate_system import BoundingBox, Point
from svg_turtle_renderer.geometry.polyline import polyline_length
from svg_turtle_renderer.parser.color_parser import Color


@dataclass(frozen=True, slots=True)
class Style:
    """The resolved paint of a shape.

    A ``None`` colour means "do not paint", which is how SVG's ``fill="none"``
    and an absent stroke are both represented.

    ``even_odd`` records the fill rule. SVG's default is nonzero, so this
    defaults to ``False``; see :mod:`svg_turtle_renderer.geometry.fill_rule` for
    why the distinction matters to a backend that only fills even-odd.
    """

    fill: Color | None = None
    stroke: Color | None = None
    stroke_width: float = 1.0
    even_odd: bool = False


@dataclass(slots=True)
class SubPath:
    """A single continuous run of points.

    A compound path -- a letter ``O``, say -- is one :class:`Shape` holding two
    sub-paths, which is what lets the renderer treat them as one fill operation.
    """

    points: list[Point] = field(default_factory=list)
    closed: bool = False

    def __len__(self) -> int:
        """Return the number of points in this sub-path."""
        return len(self.points)

    @property
    def is_drawable(self) -> bool:
        """Report whether this sub-path has enough points to draw."""
        return len(self.points) >= 2

    @property
    def closed_points(self) -> list[Point]:
        """Return the points with the closing segment made explicit.

        ``closed`` is a flag, so the segment from the last point back to the
        first is implied. Anything that walks the outline -- measuring it, or
        tracing it with a pencil -- needs that segment spelled out.
        """
        if self.closed and len(self.points) >= 3:
            return [*self.points, self.points[0]]
        return list(self.points)

    @property
    def trace_length(self) -> float:
        """Return the distance along this sub-path, including any closing edge."""
        return polyline_length(self.closed_points)


@dataclass(slots=True)
class Shape:
    """One painted element: its geometry in user units, plus its style."""

    subpaths: list[SubPath]
    style: Style
    element_id: str | None = None
    source_tag: str = "path"

    @property
    def vertex_count(self) -> int:
        """Return the total number of vertices across all sub-paths."""
        return sum(len(sp.points) for sp in self.subpaths)

    @property
    def trace_length(self) -> float:
        """Return the distance a pen covers drawing every outline of this shape."""
        return sum(sp.trace_length for sp in self.subpaths if sp.is_drawable)

    def bounds(self) -> BoundingBox | None:
        """Return the shape's bounding box, or ``None`` if it has no points."""
        return BoundingBox.from_points(p for sp in self.subpaths for p in sp.points)


@dataclass(slots=True)
class Drawing:
    """A parsed document: every shape, in paint order, plus its viewport."""

    shapes: list[Shape]
    viewbox: BoundingBox
    width: float
    height: float

    @property
    def vertex_count(self) -> int:
        """Return the total number of vertices in the drawing."""
        return sum(shape.vertex_count for shape in self.shapes)

    def content_bounds(self) -> BoundingBox | None:
        """Return the union of every shape's bounds, ignoring the viewBox."""
        result: BoundingBox | None = None
        for shape in self.shapes:
            box = shape.bounds()
            if box is None:
                continue
            result = box if result is None else result.union(box)
        return result
