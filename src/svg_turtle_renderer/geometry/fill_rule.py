"""Support for SVG's two fill rules.

Tk's polygon fill is **even-odd** only, but SVG's *default* is **nonzero**. The
two agree on a simple donut and disagree badly on artwork where same-direction
rings overlap: even-odd cancels the overlap into a hole, producing a chequerboard
where the drawing should be solid.

Nonzero says a region is filled when the winding number of its interior is not
zero. Computing that exactly for arbitrary overlapping rings needs full polygon
boolean operations. This module takes a cheaper route that is exact for the
shapes real artwork actually contains:

* Each ring's winding number is evaluated at one of its own vertices, summing the
  orientations of every ring that contains it.
* A ring whose winding is zero is a hole.
* Every filled ring is then grouped with the holes immediately inside it, and each
  group is handed to the even-odd backend separately.

Because each group is drawn on its own, overlapping rings union rather than
cancel (which is what nonzero means), while a hole still sits inside its own
parent's group, so even-odd cuts it correctly.

The assumption is that rings do not cross each other's outlines -- they nest or
they are disjoint. That holds for glyphs, icons, traced silhouettes and every
compound path an editor emits.
"""

from __future__ import annotations

from svg_turtle_renderer.geometry.coordinate_system import Point

Ring = list[Point]


def signed_area(ring: Ring) -> float:
    """Return the signed area of a ring via the shoelace formula.

    The sign gives the ring's orientation, which is what carries the winding
    information; the magnitude is not used here.
    """
    total = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True):
        total += x1 * y2 - x2 * y1
    return total / 2.0


def _bounds(ring: Ring) -> tuple[float, float, float, float]:
    """Return ``(min_x, min_y, max_x, max_y)`` for a ring."""
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return (min(xs), min(ys), max(xs), max(ys))


def point_in_ring(point: Point, ring: Ring) -> bool:
    """Report whether ``point`` lies inside ``ring`` by ray casting.

    A horizontal ray is cast and crossings are counted. The ``(y1 > py) !=
    (y2 > py)`` test counts each edge by its half-open span, so a ray passing
    exactly through a vertex is counted once rather than twice.
    """
    px, py = point
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True):
        if (y1 > py) != (y2 > py):
            crossing_x = x1 + (py - y1) / (y2 - y1) * (x2 - x1)
            if px < crossing_x:
                inside = not inside
    return inside


def group_rings(rings: list[Ring], even_odd: bool) -> list[list[Ring]]:
    """Split a shape's rings into groups, each fillable with the even-odd rule.

    Args:
        rings: The shape's closed rings.
        even_odd: True for ``fill-rule: evenodd``, False for ``nonzero``.

    Returns:
        Groups of rings. Each group should be filled as one even-odd polygon, and
        the groups painted independently.

        For ``evenodd`` this is simply one group of everything, since that is
        exactly what the backend already does. For ``nonzero`` it is one group
        per filled ring, each carrying the holes directly inside it.

    """
    drawable = [ring for ring in rings if len(ring) >= 3]
    if not drawable:
        return []
    # Even-odd is the backend's native rule, and a single ring cannot overlap
    # itself in a way the two rules disagree about.
    if even_odd or len(drawable) == 1:
        return [drawable]

    signs = [1 if signed_area(ring) > 0 else -1 for ring in drawable]
    boxes = [_bounds(ring) for ring in drawable]

    # containers[i] lists the rings that enclose ring i.
    containers: list[list[int]] = []
    for i, ring in enumerate(drawable):
        probe = ring[0]
        enclosing: list[int] = []
        for j, other in enumerate(drawable):
            if i == j:
                continue
            # Reject on bounding box first: point-in-ring is the expensive part,
            # and most pairs in real artwork do not overlap at all.
            min_x, min_y, max_x, max_y = boxes[j]
            if not (min_x <= probe[0] <= max_x and min_y <= probe[1] <= max_y):
                continue
            if point_in_ring(probe, other):
                enclosing.append(j)
        containers.append(enclosing)

    winding = [signs[i] + sum(signs[j] for j in containers[i]) for i in range(len(drawable))]
    is_hole = [w == 0 for w in winding]
    depth = [len(c) for c in containers]

    # A hole belongs to the innermost filled ring that encloses it.
    groups: dict[int, list[Ring]] = {
        i: [drawable[i]] for i in range(len(drawable)) if not is_hole[i]
    }
    for i in range(len(drawable)):
        if not is_hole[i]:
            continue
        parents = [j for j in containers[i] if not is_hole[j]]
        if not parents:
            # A hole with nothing filled around it paints nothing at all.
            continue
        parent = max(parents, key=lambda j: depth[j])
        groups[parent].append(drawable[i])

    # Preserve ring order so that painting stays deterministic.
    return [groups[i] for i in sorted(groups)]
