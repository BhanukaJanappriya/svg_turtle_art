"""Tests for fill-rule handling.

SVG defaults to nonzero; the turtle backend can only fill even-odd. These cover
the translation between the two.
"""

from __future__ import annotations

from svg_turtle_renderer.geometry.fill_rule import group_rings, point_in_ring, signed_area


def square(x, y, size, clockwise=True):
    """Return a square ring, wound as asked (clockwise on a y-down screen)."""
    points = [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]
    return points if clockwise else points[::-1]


class TestPrimitives:
    def test_orientation_shows_in_the_sign_of_the_area(self):
        assert signed_area(square(0, 0, 10, clockwise=True)) > 0
        assert signed_area(square(0, 0, 10, clockwise=False)) < 0

    def test_area_magnitude_is_correct(self):
        assert abs(signed_area(square(0, 0, 10))) == 100

    def test_point_in_ring(self):
        ring = square(0, 0, 10)
        assert point_in_ring((5, 5), ring)
        assert not point_in_ring((15, 5), ring)
        assert not point_in_ring((-5, 5), ring)

    def test_point_in_ring_handles_a_concave_outline(self):
        # An L shape: the notch is outside despite being within the bounds.
        ring = [(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)]
        assert point_in_ring((2, 2), ring)
        assert not point_in_ring((8, 8), ring)

    def test_a_ray_through_a_vertex_is_not_double_counted(self):
        # y=5 passes exactly through the vertices of this diamond.
        diamond = [(5, 0), (10, 5), (5, 10), (0, 5)]
        assert point_in_ring((5, 5), diamond)
        assert not point_in_ring((12, 5), diamond)


class TestEvenOdd:
    def test_even_odd_keeps_every_ring_in_one_group(self):
        # Even-odd is the backend's own rule, so nothing needs splitting.
        rings = [square(0, 0, 100), square(20, 20, 10), square(50, 50, 10)]
        assert group_rings(rings, even_odd=True) == [rings]

    def test_degenerate_rings_are_dropped(self):
        assert group_rings([[(0, 0), (1, 1)]], even_odd=True) == []

    def test_no_rings_gives_no_groups(self):
        assert group_rings([], even_odd=False) == []


class TestNonZero:
    def test_a_single_ring_is_one_group(self):
        rings = [square(0, 0, 10)]
        assert group_rings(rings, even_odd=False) == [rings]

    def test_a_hole_stays_with_its_parent_so_even_odd_can_cut_it(self):
        # Opposite winding inside: a genuine donut. One group means the backend
        # fills them together and the hole appears.
        outer = square(0, 0, 100, clockwise=True)
        hole = square(30, 30, 40, clockwise=False)
        groups = group_rings([outer, hole], even_odd=False)
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_same_winding_rings_are_separate_groups_so_they_union(self):
        # This is the case even-odd gets wrong: two overlapping same-direction
        # rings must union under nonzero, not cancel into a hole.
        a = square(0, 0, 50, clockwise=True)
        b = square(25, 25, 50, clockwise=True)
        assert len(group_rings([a, b], even_odd=False)) == 2

    def test_disjoint_rings_are_separate_groups(self):
        a = square(0, 0, 10)
        b = square(100, 100, 10)
        assert len(group_rings([a, b], even_odd=False)) == 2

    def test_a_same_winding_nested_ring_is_not_a_hole(self):
        # Nested but wound the same way: winding is 2, so it stays filled. Under
        # even-odd it would wrongly become a hole.
        outer = square(0, 0, 100, clockwise=True)
        inner = square(30, 30, 40, clockwise=True)
        assert len(group_rings([outer, inner], even_odd=False)) == 2

    def test_an_island_inside_a_hole_is_filled_in_its_own_group(self):
        outer = square(0, 0, 100, clockwise=True)
        hole = square(20, 20, 60, clockwise=False)
        island = square(40, 40, 20, clockwise=True)
        groups = group_rings([outer, hole, island], even_odd=False)
        # outer+hole together (so the hole is cut), and the island on its own.
        assert len(groups) == 2
        assert any(len(g) == 2 for g in groups)
        assert any(len(g) == 1 and g[0] == island for g in groups)

    def test_many_holes_all_attach_to_their_parent(self):
        outer = square(0, 0, 1000, clockwise=True)
        holes = [square(i * 100 + 10, 10, 50, clockwise=False) for i in range(9)]
        groups = group_rings([outer, *holes], even_odd=False)
        assert len(groups) == 1
        assert len(groups[0]) == 10

    def test_a_ring_is_only_a_hole_when_its_winding_reaches_zero(self):
        # Counter-clockwise inside *two* clockwise rings winds to +1, not 0, so
        # it stays filled. Nesting depth alone cannot decide this -- only the
        # winding sum can, which is the whole difference from even-odd.
        outer = square(0, 0, 1000, clockwise=True)
        middle = square(100, 100, 800, clockwise=True)
        inner = square(200, 200, 100, clockwise=False)
        groups = group_rings([outer, middle, inner], even_odd=False)
        assert len(groups) == 3
        assert all(len(g) == 1 for g in groups)

    def test_a_hole_attaches_to_its_innermost_parent(self):
        # Four levels: outer(+1) > hole(0) > island(+1) > pocket(0). The pocket
        # must be cut from the island, not from the outer ring.
        outer = square(0, 0, 1000, clockwise=True)
        hole = square(100, 100, 800, clockwise=False)
        island = square(200, 200, 600, clockwise=True)
        pocket = square(300, 300, 100, clockwise=False)
        groups = group_rings([outer, hole, island, pocket], even_odd=False)

        assert len(groups) == 2
        by_parent = {g[0][0]: g for g in groups}
        assert by_parent[outer[0]][1] == hole
        assert by_parent[island[0]][1] == pocket

    def test_ring_order_is_preserved(self):
        a = square(0, 0, 10)
        b = square(100, 100, 10)
        c = square(200, 200, 10)
        groups = group_rings([a, b, c], even_odd=False)
        assert [g[0] for g in groups] == [a, b, c]
