"""Flattening of curves into polylines.

Turtle can only draw straight segments, so every curve must become a polyline.
The functions here use *adaptive* subdivision: a segment is split only while it
is measurably further from straight than ``tolerance`` user units. A gentle
curve therefore costs a handful of points while a tight one gets as many as it
needs, which is both faster and more accurate than sampling every curve at a
fixed step count.

Each ``flatten_*`` function returns the interior and end points of the curve but
**not** its start point, because the caller already emitted that as the end of
the previous segment.
"""

from __future__ import annotations

import math

from svg_turtle_renderer.geometry.coordinate_system import Point

# Depth cap for recursive subdivision. Each level halves the curve, so 16 levels
# allow 65536 segments -- far past the point where a cusp stops being visible,
# but bounded so that a degenerate curve cannot exhaust the stack.
_MAX_DEPTH = 16


def _distance_to_line_squared(point: Point, start: Point, end: Point) -> float:
    """Return the squared distance from ``point`` to the segment ``start``-``end``."""
    px, py = point
    sx, sy = start
    ex, ey = end
    dx, dy = ex - sx, ey - sy
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-18:
        return (px - sx) ** 2 + (py - sy) ** 2
    t = ((px - sx) * dx + (py - sy) * dy) / length_squared
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    nx, ny = sx + t * dx, sy + t * dy
    return (px - nx) ** 2 + (py - ny) ** 2


def _cubic_is_flat(p0: Point, p1: Point, p2: Point, p3: Point, tolerance: float) -> bool:
    """Report whether a cubic is within ``tolerance`` of the chord ``p0``-``p3``.

    Both control points must lie close to the chord. Testing the control points
    rather than sampling the curve is conservative -- the curve is always inside
    the hull of its control points -- and needs no extra evaluation.
    """
    limit = tolerance * tolerance
    return (
        _distance_to_line_squared(p1, p0, p3) <= limit
        and _distance_to_line_squared(p2, p0, p3) <= limit
    )


def _subdivide_cubic(
    p0: Point,
    p1: Point,
    p2: Point,
    p3: Point,
    tolerance: float,
    depth: int,
    out: list[Point],
) -> None:
    """Recursively split a cubic until flat, appending points to ``out``."""
    if depth >= _MAX_DEPTH or _cubic_is_flat(p0, p1, p2, p3, tolerance):
        out.append(p3)
        return

    # de Casteljau split at t = 0.5.
    p01 = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
    p12 = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
    p23 = ((p2[0] + p3[0]) / 2, (p2[1] + p3[1]) / 2)
    p012 = ((p01[0] + p12[0]) / 2, (p01[1] + p12[1]) / 2)
    p123 = ((p12[0] + p23[0]) / 2, (p12[1] + p23[1]) / 2)
    mid = ((p012[0] + p123[0]) / 2, (p012[1] + p123[1]) / 2)

    _subdivide_cubic(p0, p01, p012, mid, tolerance, depth + 1, out)
    _subdivide_cubic(mid, p123, p23, p3, tolerance, depth + 1, out)


def flatten_cubic(
    p0: Point,
    p1: Point,
    p2: Point,
    p3: Point,
    tolerance: float = 0.25,
) -> list[Point]:
    """Flatten a cubic Bezier into points, excluding the start point ``p0``.

    Args:
        p0: Start point.
        p1: First control point.
        p2: Second control point.
        p3: End point.
        tolerance: Maximum deviation from the true curve, in user units.

    Returns:
        The interior and end points of the flattened curve.

    """
    out: list[Point] = []
    _subdivide_cubic(p0, p1, p2, p3, max(tolerance, 1e-6), 0, out)
    return out


def flatten_quadratic(
    p0: Point,
    p1: Point,
    p2: Point,
    tolerance: float = 0.25,
) -> list[Point]:
    """Flatten a quadratic Bezier by exact elevation to a cubic.

    A quadratic is degree-elevated to a cubic without any loss, so this reuses
    the cubic subdivision rather than duplicating it.
    """
    c1 = (p0[0] + 2.0 / 3.0 * (p1[0] - p0[0]), p0[1] + 2.0 / 3.0 * (p1[1] - p0[1]))
    c2 = (p2[0] + 2.0 / 3.0 * (p1[0] - p2[0]), p2[1] + 2.0 / 3.0 * (p1[1] - p2[1]))
    return flatten_cubic(p0, c1, c2, p2, tolerance)


def _angle_between(ux: float, uy: float, vx: float, vy: float) -> float:
    """Return the signed angle in radians from vector ``u`` to vector ``v``."""
    dot = ux * vx + uy * vy
    magnitude = math.hypot(ux, uy) * math.hypot(vx, vy)
    if magnitude <= 1e-18:
        return 0.0
    cosine = max(-1.0, min(1.0, dot / magnitude))
    angle = math.acos(cosine)
    return -angle if (ux * vy - uy * vx) < 0.0 else angle


def flatten_arc(
    start: Point,
    rx: float,
    ry: float,
    x_axis_rotation: float,
    large_arc: bool,
    sweep: bool,
    end: Point,
    tolerance: float = 0.25,
) -> list[Point]:
    """Flatten an SVG elliptical arc into points, excluding ``start``.

    Implements the endpoint-to-centre parameterisation from the SVG 1.1
    specification, appendix F.6, including the required out-of-range radius
    correction, then samples the resulting elliptical sweep.

    Args:
        start: Current point before the arc.
        rx: X radius, before ``x_axis_rotation``.
        ry: Y radius, before ``x_axis_rotation``.
        x_axis_rotation: Rotation of the ellipse's x-axis, in degrees.
        large_arc: The large-arc flag from the path data.
        sweep: The sweep flag from the path data.
        end: Final point of the arc.
        tolerance: Maximum deviation from the true arc, in user units.

    Returns:
        The interior and end points of the flattened arc.

    """
    x1, y1 = start
    x2, y2 = end

    # A zero-length arc draws nothing; a zero radius degrades to a line. Both are
    # explicitly specified behaviours, not error cases.
    if math.isclose(x1, x2, abs_tol=1e-12) and math.isclose(y1, y2, abs_tol=1e-12):
        return []
    rx, ry = abs(rx), abs(ry)
    if rx <= 1e-12 or ry <= 1e-12:
        return [end]

    phi = math.radians(x_axis_rotation % 360.0)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)

    # Step 1: translate the endpoints into the ellipse's own frame.
    dx2, dy2 = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    x1p = cos_phi * dx2 + sin_phi * dy2
    y1p = -sin_phi * dx2 + cos_phi * dy2

    # Step 2: scale up radii that are too small to span the endpoints.
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1.0:
        scale = math.sqrt(lam)
        rx *= scale
        ry *= scale

    # Step 3: locate the centre in the ellipse frame.
    numerator = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    denominator = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    factor = math.sqrt(max(0.0, numerator / denominator)) if denominator > 1e-18 else 0.0
    if large_arc == sweep:
        factor = -factor
    cxp = factor * rx * y1p / ry
    cyp = -factor * ry * x1p / rx

    # Step 4: map the centre back into user space.
    cx = cos_phi * cxp - sin_phi * cyp + (x1 + x2) / 2.0
    cy = sin_phi * cxp + cos_phi * cyp + (y1 + y2) / 2.0

    # Step 5: derive the start angle and the angular sweep.
    ux, uy = (x1p - cxp) / rx, (y1p - cyp) / ry
    vx, vy = (-x1p - cxp) / rx, (-y1p - cyp) / ry
    theta1 = _angle_between(1.0, 0.0, ux, uy)
    delta = _angle_between(ux, uy, vx, vy)
    if not sweep and delta > 0.0:
        delta -= 2.0 * math.pi
    elif sweep and delta < 0.0:
        delta += 2.0 * math.pi

    # Choose a step from the sagitta error of a chord on the larger radius, so
    # the segment count follows the arc's actual on-screen size.
    radius = max(rx, ry)
    ratio = max(-1.0, min(1.0, 1.0 - tolerance / radius))
    max_step = 2.0 * math.acos(ratio) if radius > tolerance else math.pi / 2.0
    max_step = max(max_step, 1e-3)
    steps = max(2, min(2048, math.ceil(abs(delta) / max_step)))

    points: list[Point] = []
    for i in range(1, steps + 1):
        theta = theta1 + delta * (i / steps)
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        px = cx + rx * cos_t * cos_phi - ry * sin_t * sin_phi
        py = cy + rx * cos_t * sin_phi + ry * sin_t * cos_phi
        points.append((px, py))

    # Land exactly on the commanded endpoint rather than a rounded sample, so a
    # following segment starts where the path data says it should.
    points[-1] = end
    return points
