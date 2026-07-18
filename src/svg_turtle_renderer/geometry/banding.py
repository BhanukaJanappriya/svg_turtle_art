"""Slicing a filled region into horizontal bands.

Turtle fills a whole polygon in one operation, so a colour cannot appear
gradually on its own. The streaming fill builds it from strips instead: the shape
is clipped to a horizontal band, that band is filled, and the band is advanced.
Filling the bands in order makes the colour read as flowing across the shape
rather than snapping in all at once.

The bands overlap very slightly. Adjacent opaque strips that merely abut can
leave a hairline seam where the backend antialiases their shared edge; a fraction
of a pixel of overlap, repainted harmlessly, removes it.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from svg_turtle_renderer.geometry.coordinate_system import BoundingBox

# Never make a band thinner than this. A fill front finer than half a pixel is
# invisible, and without a floor a very slow pencil could ask for tens of
# thousands of bands on a tall shape.
_MIN_BAND = 0.5

# Half the overlap between neighbouring bands, in pixels.
_SEAM_OVERLAP = 0.5


@dataclass(frozen=True, slots=True)
class Band:
    """One horizontal strip to fill.

    Attributes:
        box: The clip rectangle, already widened by the seam overlap.
        advance: The nominal height this band represents, without the overlap.
            Summed over a shape's bands this equals the region's height, which is
            what keeps progress reporting exact.

    """

    box: BoundingBox
    advance: float


def horizontal_bands(box: BoundingBox, step: float, top_down: bool = True) -> Iterator[Band]:
    """Yield the bands that tile ``box`` from top to bottom.

    Args:
        box: The region to slice, in canvas pixels.
        step: The nominal band height, i.e. how far the fill front advances per
            frame. Clamped up to half a pixel.
        top_down: Fill from the top of the region downwards, which is how a hand
            colouring in a shape usually moves. When false, bottom upwards.

    Yields:
        The bands in fill order.

    """
    height = box.height
    if height <= 0.0 or box.width <= 0.0:
        return

    band_height = max(step, _MIN_BAND)
    count = max(1, int(height / band_height) + (1 if height % band_height else 0))

    for i in range(count):
        index = (count - 1 - i) if top_down else i
        low = box.min_y + index * band_height
        high = min(low + band_height, box.max_y)
        yield Band(
            box=BoundingBox(
                box.min_x,
                low - _SEAM_OVERLAP,
                box.max_x,
                high + _SEAM_OVERLAP,
            ),
            advance=high - low,
        )


def group_bounds(rings: list[list[tuple[float, float]]]) -> BoundingBox | None:
    """Return the bounding box of every point across a group of rings."""
    box: BoundingBox | None = None
    for ring in rings:
        ring_box = BoundingBox.from_points(ring)
        if ring_box is not None:
            box = ring_box if box is None else box.union(ring_box)
    return box
