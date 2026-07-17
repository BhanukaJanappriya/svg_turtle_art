"""Affine transforms and the SVG-to-turtle coordinate mapping.

SVG uses a y-down coordinate system with the origin at the top-left of the
viewport. Turtle uses a y-up system with the origin at the centre of the canvas.
:class:`CoordinateSystem` owns that mapping so no other module needs to remember
which way is up.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

Point = tuple[float, float]


@dataclass(frozen=True, slots=True)
class Matrix:
    """A 2D affine transform stored as the six values SVG exposes.

    The matrix maps ``(x, y)`` to ``(a*x + c*y + e, b*x + d*y + f)``, matching
    the ``matrix(a b c d e f)`` form of the SVG ``transform`` attribute.
    """

    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    @classmethod
    def identity(cls) -> Matrix:
        """Return the identity transform."""
        return cls()

    @classmethod
    def translate(cls, tx: float, ty: float = 0.0) -> Matrix:
        """Return a translation by ``(tx, ty)``."""
        return cls(1.0, 0.0, 0.0, 1.0, tx, ty)

    @classmethod
    def scale(cls, sx: float, sy: float | None = None) -> Matrix:
        """Return a scale by ``sx`` horizontally and ``sy`` vertically.

        When ``sy`` is omitted the scale is uniform, as in SVG's ``scale(s)``.
        """
        return cls(sx, 0.0, 0.0, sx if sy is None else sy, 0.0, 0.0)

    @classmethod
    def rotate(cls, degrees: float, cx: float = 0.0, cy: float = 0.0) -> Matrix:
        """Return a rotation of ``degrees`` clockwise about ``(cx, cy)``.

        The direction is clockwise on screen because SVG's y-axis points down.
        """
        rad = math.radians(degrees)
        cos, sin = math.cos(rad), math.sin(rad)
        rotation = cls(cos, sin, -sin, cos, 0.0, 0.0)
        if cx == 0.0 and cy == 0.0:
            return rotation
        return cls.translate(cx, cy) @ rotation @ cls.translate(-cx, -cy)

    @classmethod
    def skew_x(cls, degrees: float) -> Matrix:
        """Return a horizontal skew of ``degrees``."""
        return cls(1.0, 0.0, math.tan(math.radians(degrees)), 1.0, 0.0, 0.0)

    @classmethod
    def skew_y(cls, degrees: float) -> Matrix:
        """Return a vertical skew of ``degrees``."""
        return cls(1.0, math.tan(math.radians(degrees)), 0.0, 1.0, 0.0, 0.0)

    def __matmul__(self, other: Matrix) -> Matrix:
        """Compose two transforms so ``(self @ other)`` applies ``other`` first."""
        return Matrix(
            a=self.a * other.a + self.c * other.b,
            b=self.b * other.a + self.d * other.b,
            c=self.a * other.c + self.c * other.d,
            d=self.b * other.c + self.d * other.d,
            e=self.a * other.e + self.c * other.f + self.e,
            f=self.b * other.e + self.d * other.f + self.f,
        )

    def apply(self, point: Point) -> Point:
        """Map a single point through this transform."""
        x, y = point
        return (self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f)

    def apply_all(self, points: Iterable[Point]) -> list[Point]:
        """Map many points through this transform.

        The matrix coefficients are bound to locals first; for artwork with tens
        of thousands of vertices that is measurably cheaper than re-reading the
        dataclass attributes inside the loop.
        """
        a, b, c, d, e, f = self.a, self.b, self.c, self.d, self.e, self.f
        return [(a * x + c * y + e, b * x + d * y + f) for x, y in points]

    @property
    def determinant(self) -> float:
        """Return the determinant of the linear part."""
        return self.a * self.d - self.b * self.c

    @property
    def mean_scale(self) -> float:
        """Return the scale factor SVG uses to transform stroke widths.

        A non-uniform transform stretches a stroke into an ellipse, which turtle
        cannot express. The SVG specification's own fallback for this situation
        is ``sqrt(|det|)``, and that is what a stroke width is multiplied by.
        """
        return math.sqrt(abs(self.determinant))

    def is_identity(self, tolerance: float = 1e-12) -> bool:
        """Report whether this transform leaves points unchanged."""
        return (
            abs(self.a - 1.0) < tolerance
            and abs(self.b) < tolerance
            and abs(self.c) < tolerance
            and abs(self.d - 1.0) < tolerance
            and abs(self.e) < tolerance
            and abs(self.f) < tolerance
        )


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """An axis-aligned bounding box in SVG user units."""

    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        """Return the horizontal extent."""
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        """Return the vertical extent."""
        return self.max_y - self.min_y

    @property
    def center(self) -> Point:
        """Return the midpoint of the box."""
        return ((self.min_x + self.max_x) / 2.0, (self.min_y + self.max_y) / 2.0)

    @property
    def is_empty(self) -> bool:
        """Report whether the box has no area in either axis."""
        return self.width <= 0.0 or self.height <= 0.0

    @classmethod
    def from_points(cls, points: Iterable[Point]) -> BoundingBox | None:
        """Return the tightest box containing ``points``, or ``None`` if empty."""
        xs: list[float] = []
        ys: list[float] = []
        for x, y in points:
            xs.append(x)
            ys.append(y)
        if not xs:
            return None
        return cls(min(xs), min(ys), max(xs), max(ys))

    def union(self, other: BoundingBox) -> BoundingBox:
        """Return the smallest box containing both boxes."""
        return BoundingBox(
            min(self.min_x, other.min_x),
            min(self.min_y, other.min_y),
            max(self.max_x, other.max_x),
            max(self.max_y, other.max_y),
        )


class CoordinateSystem:
    """Maps SVG user space onto turtle canvas space.

    The mapping is a single pre-composed :class:`Matrix`, so transforming a
    vertex during rendering costs four multiplies and no branching. It folds
    together, in order: centring the source box on the origin, user scale,
    mirror/flip, rotation, the y-axis inversion turtle requires, and the user's
    pixel offset.
    """

    def __init__(self, transform: Matrix, scale_factor: float) -> None:
        """Store a pre-composed transform and the scale it applies to lengths."""
        self._transform = transform
        self._scale_factor = scale_factor

    @property
    def transform(self) -> Matrix:
        """Return the composed SVG-to-canvas transform."""
        return self._transform

    @property
    def scale_factor(self) -> float:
        """Return the factor by which lengths (e.g. stroke widths) are scaled."""
        return self._scale_factor

    def to_canvas(self, point: Point) -> Point:
        """Map one point from SVG user space to canvas space."""
        return self._transform.apply(point)

    def all_to_canvas(self, points: Iterable[Point]) -> list[Point]:
        """Map many points from SVG user space to canvas space."""
        return self._transform.apply_all(points)

    def scale_length(self, length: float) -> float:
        """Scale a length (such as a stroke width) into canvas units."""
        return length * self._scale_factor
