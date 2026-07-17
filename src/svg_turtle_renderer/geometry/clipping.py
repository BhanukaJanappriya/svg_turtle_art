"""Rectangular clipping of polylines and polygons.

This backs the renderer's *basic* ``clipPath`` support. A full implementation
would need general polygon boolean operations against arbitrary clip geometry;
instead a clip path is reduced to its bounding rectangle, and shapes are clipped
to that. The common real-world case -- a rectangular clip that crops artwork to
a frame -- comes out exactly right, and a non-rectangular clip crops to its
bounds rather than being ignored outright. Callers are expected to say so in
their documentation, which :mod:`svg_turtle_renderer.parser.svg_parser` does.
"""

from __future__ import annotations

from svg_turtle_renderer.geometry.coordinate_system import BoundingBox, Point


def _is_inside(point: Point, edge: int, box: BoundingBox) -> bool:
    """Report whether ``point`` is on the interior side of one clip edge."""
    x, y = point
    if edge == 0:
        return x >= box.min_x
    if edge == 1:
        return x <= box.max_x
    if edge == 2:
        return y >= box.min_y
    return y <= box.max_y


def _intersect(start: Point, end: Point, edge: int, box: BoundingBox) -> Point:
    """Return where the segment ``start``-``end`` crosses one clip edge."""
    x1, y1 = start
    x2, y2 = end
    if edge in (0, 1):
        boundary = box.min_x if edge == 0 else box.max_x
        # The caller only reaches here when the endpoints straddle the edge, so
        # the denominator cannot be zero.
        t = (boundary - x1) / (x2 - x1)
        return (boundary, y1 + t * (y2 - y1))
    boundary = box.min_y if edge == 2 else box.max_y
    t = (boundary - y1) / (y2 - y1)
    return (x1 + t * (x2 - x1), boundary)


def clip_polygon(points: list[Point], box: BoundingBox) -> list[Point]:
    """Clip a closed polygon to a rectangle with the Sutherland-Hodgman algorithm.

    Args:
        points: The polygon's vertices, without a repeated closing point.
        box: The clip rectangle.

    Returns:
        The clipped polygon, or an empty list if nothing survives. A concave
        polygon may come back with degenerate edges running along the boundary,
        which is harmless for filling.

    """
    if len(points) < 3 or box.is_empty:
        return []

    output = list(points)
    for edge in range(4):
        if not output:
            return []
        current = output
        output = []
        previous = current[-1]
        previous_inside = _is_inside(previous, edge, box)
        for point in current:
            point_inside = _is_inside(point, edge, box)
            if point_inside:
                if not previous_inside:
                    output.append(_intersect(previous, point, edge, box))
                output.append(point)
            elif previous_inside:
                output.append(_intersect(previous, point, edge, box))
            previous, previous_inside = point, point_inside
    return output


def _clip_segment(start: Point, end: Point, box: BoundingBox) -> tuple[Point, Point] | None:
    """Clip one segment to a rectangle with the Liang-Barsky algorithm.

    Returns:
        The clipped endpoints, or ``None`` if the segment misses the box.

    """
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0

    for p, q in (
        (-dx, x1 - box.min_x),
        (dx, box.max_x - x1),
        (-dy, y1 - box.min_y),
        (dy, box.max_y - y1),
    ):
        if abs(p) < 1e-18:
            # Parallel to this edge: outside means the whole segment is out.
            if q < 0.0:
                return None
            continue
        t = q / p
        if p < 0.0:
            if t > t1:
                return None
            t0 = max(t0, t)
        else:
            if t < t0:
                return None
            t1 = min(t1, t)

    if t0 > t1:
        return None
    return ((x1 + t0 * dx, y1 + t0 * dy), (x1 + t1 * dx, y1 + t1 * dy))


def clip_polyline(points: list[Point], box: BoundingBox) -> list[list[Point]]:
    """Clip an open polyline to a rectangle.

    A polyline that leaves and re-enters the box becomes several runs, so the
    result is a list of polylines rather than one.

    Args:
        points: The polyline's vertices.
        box: The clip rectangle.

    Returns:
        The surviving runs, each with at least two points.

    """
    if len(points) < 2 or box.is_empty:
        return []

    runs: list[list[Point]] = []
    current: list[Point] = []
    for start, end in zip(points, points[1:], strict=False):
        clipped = _clip_segment(start, end, box)
        if clipped is None:
            if len(current) >= 2:
                runs.append(current)
            current = []
            continue
        piece_start, piece_end = clipped
        if not current:
            current = [piece_start, piece_end]
        elif current[-1] == piece_start:
            current.append(piece_end)
        else:
            # The segment was clipped at its start, so the polyline re-entered
            # the box and a new run begins here.
            if len(current) >= 2:
                runs.append(current)
            current = [piece_start, piece_end]

    if len(current) >= 2:
        runs.append(current)
    return runs
