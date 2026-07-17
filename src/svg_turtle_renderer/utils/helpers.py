"""Small pure helpers used across layers.

Everything here is a free function with no state and no I/O, so it can be tested
in isolation and reused from any layer without creating a dependency cycle.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import TypeVar

from svg_turtle_renderer.geometry.coordinate_system import Point

T = TypeVar("T")

_LENGTH_RE = re.compile(
    r"^\s*([-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?)\s*([a-z%]*)\s*$", re.IGNORECASE
)

# CSS absolute units in terms of the 96-dpi reference pixel that SVG assumes.
_UNIT_SCALE: dict[str, float] = {
    "": 1.0,
    "px": 1.0,
    "pt": 96.0 / 72.0,
    "pc": 16.0,
    "in": 96.0,
    "cm": 96.0 / 2.54,
    "mm": 96.0 / 25.4,
    "q": 96.0 / 101.6,
}


def parse_length(
    value: str | None,
    default: float = 0.0,
    percent_of: float | None = None,
) -> float:
    """Parse an SVG length into user units.

    Args:
        value: The attribute text, such as ``"12"``, ``"2.5cm"`` or ``"50%"``.
        default: Returned when ``value`` is absent or unparseable.
        percent_of: The reference length a percentage resolves against. When a
            percentage is given without a reference, ``default`` is returned,
            since guessing a viewport would silently misplace geometry.

    Returns:
        The length in user units.

    """
    if value is None:
        return default
    match = _LENGTH_RE.match(value)
    if match is None:
        return default

    number = float(match.group(1))
    unit = match.group(2).lower()

    if unit == "%":
        return default if percent_of is None else number / 100.0 * percent_of
    if unit in ("em", "ex", "rem", "ch"):
        # Font-relative units need a resolved font size, which this renderer has
        # no notion of. Treating them as user units keeps the geometry sane.
        return number
    return number * _UNIT_SCALE.get(unit, 1.0)


def parse_points(value: str | None) -> list[Point]:
    """Parse the ``points`` attribute of a polygon or polyline.

    An odd trailing coordinate is dropped, matching the SVG rule that a point
    list with an unpaired value renders the pairs that came before it.
    """
    if not value:
        return []
    numbers = [float(n) for n in re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", value)]
    return [(numbers[i], numbers[i + 1]) for i in range(0, len(numbers) - 1, 2)]


def parse_style_attribute(value: str | None) -> dict[str, str]:
    """Parse an inline ``style`` attribute into a property dictionary.

    Declarations without a colon are skipped rather than raising, which is what
    a browser does with malformed CSS.
    """
    if not value:
        return {}
    properties: dict[str, str] = {}
    for declaration in value.split(";"):
        name, separator, text = declaration.partition(":")
        if not separator:
            continue
        name = name.strip().lower()
        text = text.strip()
        if name and text:
            properties[name] = text
    return properties


def douglas_peucker(points: Sequence[Point], tolerance: float) -> list[Point]:
    """Simplify a polyline, keeping every point within ``tolerance`` of it.

    A vertex is dropped only when the resulting line still passes within
    ``tolerance`` of it, so the silhouette is preserved while redundant vertices
    from dense curve flattening are removed.

    The recursion is written as an explicit stack because deeply curved paths can
    otherwise exceed Python's recursion limit on long point runs.

    Args:
        points: The polyline to simplify.
        tolerance: Maximum permitted deviation, in the same units as ``points``.

    Returns:
        The simplified polyline, always retaining the first and last points.

    """
    if tolerance <= 0.0 or len(points) < 3:
        return list(points)

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack: list[tuple[int, int]] = [(0, len(points) - 1)]
    limit = tolerance * tolerance

    while stack:
        first, last = stack.pop()
        if last <= first + 1:
            continue

        ax, ay = points[first]
        bx, by = points[last]
        dx, dy = bx - ax, by - ay
        length_squared = dx * dx + dy * dy

        worst_index = -1
        worst_distance = 0.0
        for i in range(first + 1, last):
            px, py = points[i]
            if length_squared <= 1e-18:
                distance = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = ((px - ax) * dx + (py - ay) * dy) / length_squared
                t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
                distance = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
            if distance > worst_distance:
                worst_distance = distance
                worst_index = i

        if worst_distance > limit and worst_index > 0:
            keep[worst_index] = True
            stack.append((first, worst_index))
            stack.append((worst_index, last))

    return [point for point, keeper in zip(points, keep, strict=True) if keeper]


def strip_namespace(tag: str) -> str:
    """Return an XML tag without its ``{namespace}`` prefix."""
    if tag.startswith("{"):
        return tag.rpartition("}")[2]
    return tag


def format_duration(seconds: float) -> str:
    """Format a duration for human-readable reports."""
    if seconds < 1.0:
        return f"{seconds * 1000.0:.0f} ms"
    if seconds < 60.0:
        return f"{seconds:.2f} s"
    minutes, remainder = divmod(seconds, 60.0)
    return f"{int(minutes)}m {remainder:.1f}s"


def unique_preserving_order(items: Iterable[T]) -> list[T]:
    """Return ``items`` with duplicates removed, keeping first-seen order."""
    seen: set[T] = set()
    result: list[T] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
