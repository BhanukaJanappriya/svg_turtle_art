"""Parsing of the SVG ``transform`` attribute into a matrix."""

from __future__ import annotations

import re

from svg_turtle_renderer.core.exceptions import TransformError
from svg_turtle_renderer.geometry.coordinate_system import Matrix

_FUNCTION_RE = re.compile(r"([a-zA-Z]+)\s*\(([^)]*)\)")
_NUMBER_RE = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")

# Permitted argument counts per function, used to reject malformed input early.
_ARITY: dict[str, tuple[int, ...]] = {
    "matrix": (6,),
    "translate": (1, 2),
    "scale": (1, 2),
    "rotate": (1, 3),
    "skewx": (1,),
    "skewy": (1,),
}


def _build(name: str, args: list[float]) -> Matrix:
    """Build the matrix for one transform function."""
    if name == "matrix":
        return Matrix(*args)
    if name == "translate":
        return Matrix.translate(args[0], args[1] if len(args) > 1 else 0.0)
    if name == "scale":
        return Matrix.scale(args[0], args[1] if len(args) > 1 else None)
    if name == "rotate":
        if len(args) == 3:
            return Matrix.rotate(args[0], args[1], args[2])
        return Matrix.rotate(args[0])
    if name == "skewx":
        return Matrix.skew_x(args[0])
    return Matrix.skew_y(args[0])


def parse_transform(value: str | None, *, strict: bool = False) -> Matrix:
    """Parse a ``transform`` attribute into a single composed matrix.

    Functions compose left to right, so ``translate(10,0) scale(2)`` scales
    first and then translates -- the order SVG specifies.

    Args:
        value: The attribute text, for example ``"translate(10 20) rotate(45)"``.
        strict: When true, unknown functions and bad arities raise; otherwise the
            offending function is skipped.

    Returns:
        The composed transform, or the identity when ``value`` is empty.

    Raises:
        TransformError: On malformed input when ``strict`` is true.

    """
    if not value or not value.strip():
        return Matrix.identity()

    result = Matrix.identity()
    matched_span = 0
    for match in _FUNCTION_RE.finditer(value):
        matched_span += len(match.group(0))
        name = match.group(1).lower()
        args = [float(n) for n in _NUMBER_RE.findall(match.group(2))]

        if name not in _ARITY:
            if strict:
                raise TransformError(f"Unknown transform function: {match.group(1)!r}")
            continue
        if len(args) not in _ARITY[name]:
            if strict:
                raise TransformError(
                    f"{name}() expects {' or '.join(map(str, _ARITY[name]))} arguments, "
                    f"got {len(args)}"
                )
            continue
        result = result @ _build(name, args)

    if matched_span == 0 and strict:
        raise TransformError(f"No transform functions found in {value!r}")
    return result
