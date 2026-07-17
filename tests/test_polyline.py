"""Tests for walking a polyline at constant speed."""

from __future__ import annotations

import math

import pytest

from svg_turtle_renderer.geometry.polyline import chunks_by_length, polyline_length


def total_length(chunks):
    """Return the summed length of a list of chunks."""
    return sum(polyline_length(chunk) for chunk in chunks)


class TestPolylineLength:
    def test_a_straight_line(self):
        assert polyline_length([(0, 0), (10, 0)]) == 10

    def test_segments_accumulate(self):
        assert polyline_length([(0, 0), (10, 0), (10, 10)]) == 20

    def test_a_diagonal(self):
        assert polyline_length([(0, 0), (3, 4)]) == 5

    def test_degenerate_input(self):
        assert polyline_length([]) == 0
        assert polyline_length([(5, 5)]) == 0


class TestChunking:
    def test_a_short_polyline_is_one_chunk(self):
        chunks = list(chunks_by_length([(0, 0), (5, 0)], 10))
        assert chunks == [[(0, 0), (5, 0)]]

    def test_a_long_segment_is_subdivided(self):
        # The point of the whole exercise: without this the pencil would cross a
        # long straight edge in a single frame.
        chunks = list(chunks_by_length([(0, 0), (100, 0)], 10))
        assert len(chunks) == 10

    def test_chunks_are_the_requested_length(self):
        for chunk in chunks_by_length([(0, 0), (100, 0)], 10):
            assert polyline_length(chunk) == pytest.approx(10)

    def test_chunks_are_contiguous(self):
        # Each chunk must start where the last ended, or the line would have gaps.
        chunks = list(chunks_by_length([(0, 0), (37, 0), (37, 21)], 5))
        for previous, following in zip(chunks, chunks[1:], strict=False):
            assert previous[-1] == following[0]

    def test_the_chunks_reconstruct_the_original_length(self):
        points = [(0, 0), (37, 0), (37, 21), (10, 40)]
        chunks = list(chunks_by_length(points, 3.5))
        assert total_length(chunks) == pytest.approx(polyline_length(points))

    def test_the_walk_starts_and_ends_at_the_polyline_ends(self):
        points = [(0, 0), (37, 0), (37, 21)]
        chunks = list(chunks_by_length(points, 5))
        assert chunks[0][0] == (0, 0)
        assert chunks[-1][-1] == (37, 21)

    def test_vertices_are_preserved(self):
        # The corner must survive, or the traced line would cut across it.
        points = [(0, 0), (10, 0), (10, 10)]
        visited = [p for chunk in chunks_by_length(points, 3) for p in chunk]
        assert (10, 0) in visited

    def test_a_step_larger_than_the_line_gives_one_chunk(self):
        assert len(list(chunks_by_length([(0, 0), (5, 0)], 1000))) == 1

    def test_a_non_positive_step_yields_everything_at_once(self):
        points = [(0, 0), (10, 0), (20, 5)]
        assert list(chunks_by_length(points, 0)) == [points]
        assert list(chunks_by_length(points, -5)) == [points]

    def test_pacing_is_by_distance_not_by_vertices(self):
        # A densely sampled curve and a bare straight line of the same length
        # must take the same number of frames; that is what stops the pencil
        # crawling round curves and teleporting along edges.
        dense = [(i * 0.1, 0.0) for i in range(1001)]  # 100 units, 1001 vertices
        sparse = [(0.0, 0.0), (100.0, 0.0)]  # 100 units, 2 vertices
        assert len(list(chunks_by_length(dense, 10))) == len(list(chunks_by_length(sparse, 10)))

    def test_zero_length_segments_are_skipped(self):
        chunks = list(chunks_by_length([(0, 0), (0, 0), (10, 0)], 5))
        assert total_length(chunks) == pytest.approx(10)

    def test_degenerate_input_yields_nothing(self):
        assert list(chunks_by_length([], 5)) == []
        assert list(chunks_by_length([(1, 1)], 5)) == []

    def test_every_chunk_is_drawable(self):
        points = [(math.cos(i / 10) * 50, math.sin(i / 10) * 50) for i in range(64)]
        for chunk in chunks_by_length(points, 7):
            assert len(chunk) >= 2
