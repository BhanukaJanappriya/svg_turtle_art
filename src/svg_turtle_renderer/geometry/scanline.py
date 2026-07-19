"""Finding where a horizontal line lies inside a shape.

This backs the brush fill. A brush lays paint down in strokes, so the fill is
built from horizontal brush rows rather than clipped polygons. Each row is drawn
only across the parts of that scanline that are actually inside the shape, which
is what these spans compute, honouring holes and the fill rule exactly the way
the final fill does.
"""

from __future__ import annotations

from svg_turtle_renderer.geometry.coordinate_system import Point

Span = tuple[float, float]


def horizontal_spans(rings: list[list[Point]], y: float, even_odd: bool) -> list[Span]:
    """Return the inside intervals of a ring set along the line ``y``.

    Args:
        rings: The shape's closed rings, in canvas pixels.
        y: The height of the scanline.
        even_odd: True for the even-odd rule, False for nonzero winding.

    Returns:
        The ``(x_start, x_end)`` intervals where the scanline is inside the shape,
        left to right. A hole produces a gap between intervals.

    """
    # Gather the x where each edge crosses the scanline, tagged with the edge's
    # winding direction. The half-open ``(y1 > y) != (y2 > y)`` test counts a
    # vertex exactly on the line once, not twice, which keeps the spans clean.
    crossings: list[tuple[float, int]] = []
    for ring in rings:
        count = len(ring)
        for i in range(count):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % count]
            if (y1 > y) != (y2 > y):
                x = x1 + (y - y1) / (y2 - y1) * (x2 - x1)
                crossings.append((x, 1 if y2 > y1 else -1))

    if len(crossings) < 2:
        return []
    crossings.sort()

    spans: list[Span] = []
    if even_odd:
        # Inside between the first and second crossing, the third and fourth, and
        # so on.
        for i in range(0, len(crossings) - 1, 2):
            left, right = crossings[i][0], crossings[i + 1][0]
            if right > left:
                spans.append((left, right))
        return spans

    # Nonzero: inside wherever the running winding number is not zero.
    winding = 0
    span_start: float | None = None
    for x, direction in crossings:
        was_inside = winding != 0
        winding += direction
        now_inside = winding != 0
        if not was_inside and now_inside:
            span_start = x
        elif was_inside and not now_inside and span_start is not None:
            if x > span_start:
                spans.append((span_start, x))
            span_start = None
    return spans
