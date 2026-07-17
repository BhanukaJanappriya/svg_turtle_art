"""Walking a polyline at a constant speed.

This backs the pencil sketch effect. Pacing the pencil by *vertices* would make it
lurch: a flattened curve packs vertices tightly while a straight line has two, so
the pen would crawl round a curve and teleport across a long edge. Pacing by
*distance* gives the steady hand-speed that reads as drawing.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence

from svg_turtle_renderer.geometry.coordinate_system import Point


def polyline_length(points: Sequence[Point]) -> float:
    """Return the total length of a polyline."""
    return sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False))


def chunks_by_length(points: Sequence[Point], step: float) -> Iterator[list[Point]]:
    """Split a polyline into contiguous pieces of roughly ``step`` length.

    Consecutive chunks share an endpoint, so drawing each in turn traces the
    original line exactly, with no gaps.

    A segment longer than ``step`` is subdivided at interpolated points, which is
    the part that matters: without it the pencil would jump the whole length of a
    straight edge in a single frame.

    Args:
        points: The polyline to walk.
        step: The target length of each chunk, in the same units as ``points``.
            A non-positive step yields the whole polyline as one chunk.

    Yields:
        Polylines of at least two points each.

    """
    if len(points) < 2:
        return
    if step <= 0.0:
        yield list(points)
        return

    chunk: list[Point] = [points[0]]
    budget = step

    for a, b in zip(points, points[1:], strict=False):
        segment = math.dist(a, b)
        if segment <= 0.0:
            continue

        travelled = 0.0
        # Carve whole chunks out of this segment while it is long enough.
        while segment - travelled > budget:
            travelled += budget
            fraction = travelled / segment
            cut = (a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction)
            chunk.append(cut)
            yield chunk
            # The next chunk starts where this one ended, so the line stays
            # continuous across the join.
            chunk = [cut]
            budget = step

        budget -= segment - travelled
        chunk.append(b)

    if len(chunk) >= 2:
        yield chunk
