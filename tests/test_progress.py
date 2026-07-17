"""Tests for progress reporting."""

from __future__ import annotations

from svg_turtle_renderer.utils.progress import (
    NullProgress,
    Progress,
    TqdmProgress,
    make_progress,
)


class TestNullProgress:
    def test_it_accepts_work_and_does_nothing(self):
        # Callers advance unconditionally rather than branching on a bar
        # existing, so this must swallow everything quietly.
        progress = NullProgress()
        progress.advance()
        progress.advance(123.4)
        progress.close()

    def test_it_satisfies_the_protocol(self):
        assert isinstance(NullProgress(), Progress)


class TestTqdmProgress:
    def test_it_satisfies_the_protocol(self):
        bar = TqdmProgress(10, "Testing", "unit")
        try:
            assert isinstance(bar, Progress)
        finally:
            bar.close()

    def test_advancing_moves_the_bar(self):
        bar = TqdmProgress(10, "Testing", "unit")
        try:
            bar.advance(4)
            assert bar._bar.n == 4
        finally:
            bar.close()

    def test_it_accepts_fractional_work(self):
        # Sketch progress is a distance in pixels, not a whole count.
        bar = TqdmProgress(10, "Testing", "px")
        try:
            bar.advance(0.5)
            bar.advance(0.25)
            assert bar._bar.n == 0.75
        finally:
            bar.close()

    def test_closing_twice_is_harmless(self):
        bar = TqdmProgress(10, "Testing", "unit")
        bar.close()
        bar.close()

    def test_advancing_after_close_is_harmless(self):
        bar = TqdmProgress(10, "Testing", "unit")
        bar.close()
        bar.advance(1)


class TestMakeProgress:
    def test_disabled_gives_a_silent_reporter(self):
        assert isinstance(make_progress(False, 100, "x", "unit"), NullProgress)

    def test_enabled_gives_a_bar(self):
        progress = make_progress(True, 100, "x", "unit")
        try:
            assert isinstance(progress, TqdmProgress)
        finally:
            progress.close()

    def test_a_zero_total_gives_a_silent_reporter(self):
        # A bar that can never move is worse than no bar.
        assert isinstance(make_progress(True, 0, "x", "unit"), NullProgress)

    def test_a_negative_total_gives_a_silent_reporter(self):
        assert isinstance(make_progress(True, -5, "x", "unit"), NullProgress)
