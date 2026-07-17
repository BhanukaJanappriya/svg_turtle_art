"""Tests for the turtle backend.

Most of this module needs a real display. Those tests are marked ``display`` and
are skipped automatically when there is no screen; CI runs them under a virtual
framebuffer. The rest check the behaviour that does not need a window.
"""

from __future__ import annotations

import os
import sys

import pytest

from svg_turtle_renderer.core.exceptions import RenderError
from svg_turtle_renderer.parser.color_parser import BLACK, WHITE, Color
from svg_turtle_renderer.renderer.turtle_renderer import TurtleCanvas


def has_display() -> bool:
    """Report whether a turtle window can be opened here.

    This deliberately does *not* build a probe Tk to find out. Collection happens
    while pytest's file-descriptor capture is active, and a Tcl interpreter
    initialised with the standard channels redirected leaves Tcl's globals in a
    state that makes later windows fail intermittently, anywhere in the run. So
    availability is inferred from the platform, and the first real interpreter is
    created inside a test, with capture lifted.
    """
    try:
        import tkinter  # noqa: F401
    except ImportError:
        return False
    if sys.platform.startswith(("linux", "freebsd")):
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return True


requires_display = pytest.mark.skipif(not has_display(), reason="needs a display")


@pytest.fixture
def real_window(capfd):
    """Allow a real Tk window to be created inside a test.

    pytest captures at the file-descriptor level by default, swapping out fds 1
    and 2. Tcl consults the standard channels while initialising, so with them
    redirected its setup intermittently fails on Windows with a misleading
    "Can't find a usable tk.tcl". The failure moves between tests from run to
    run, which is the tell that it is a capture race and not a bug in the code
    under test -- turtle opens hundreds of windows quite happily with capture
    off. Restoring the real fds for the duration makes these tests reliable.
    """
    with capfd.disabled():
        yield


class TestWithoutAWindow:
    def test_constructing_a_canvas_opens_nothing(self):
        # Construction must stay cheap and side-effect free; importing turtle is
        # deferred to open() so the package imports fine on a headless box.
        canvas = TurtleCanvas(800, 600, WHITE)
        assert canvas.size == (800, 600)

    def test_drawing_before_opening_is_a_clear_error(self):
        canvas = TurtleCanvas(800, 600, WHITE)
        with pytest.raises(RenderError, match="open"):
            canvas.stroke_polyline([(0, 0), (1, 1)], BLACK, 1.0, False)

    def test_filling_before_opening_is_a_clear_error(self):
        canvas = TurtleCanvas(800, 600, WHITE)
        with pytest.raises(RenderError, match="open"):
            canvas.fill_polygons([[(0, 0), (1, 0), (1, 1)]], BLACK)

    def test_exporting_before_opening_is_a_clear_error(self, tmp_path):
        canvas = TurtleCanvas(800, 600, WHITE)
        with pytest.raises(RenderError, match="open"):
            canvas.export(tmp_path / "out.png")

    def test_closing_an_unopened_canvas_is_harmless(self):
        TurtleCanvas(800, 600, WHITE).close()

    def test_frame_on_an_unopened_canvas_is_harmless(self):
        TurtleCanvas(800, 600, WHITE).frame()


class FakePen:
    """Records the moves a fill makes, standing in for a real turtle."""

    def __init__(self) -> None:
        self.path: list[tuple[float, float]] = []
        self.filling = False

    def penup(self) -> None:
        pass

    def fillcolor(self, _color) -> None:
        pass

    def begin_fill(self) -> None:
        self.filling = True
        self.path = []

    def end_fill(self) -> None:
        self.filling = False

    def goto(self, x, y=None) -> None:
        self.path.append((x, y))


class TestFillBridging:
    """The stitching that joins several rings into one Tk polygon.

    Tk fills a single polygon per call, so a multi-ring shape has to be stitched
    together. If the bridges between rings are not retraced, they form a polygon
    of their own whose edges flip even-odd parity, chequerboarding the artwork.
    Two rings hide the bug -- the lone bridge and the closing edge coincide by
    luck -- so these use three or more.
    """

    def _fill(self, rings):
        canvas = TurtleCanvas(400, 400, WHITE)
        pen = FakePen()
        canvas._turtle = pen
        canvas.fill_polygons(rings, BLACK)
        return pen.path

    @staticmethod
    def _edges(path):
        return list(zip(path, path[1:], strict=False))

    def test_every_bridge_is_retraced_so_it_cancels(self):
        rings = [
            [(0, 0), (10, 0), (10, 10)],
            [(100, 100), (110, 100), (110, 110)],
            [(200, 200), (210, 200), (210, 210)],
        ]
        edges = self._edges(self._fill(rings))
        ring_points = {p for ring in rings for p in ring}

        # Any edge that is not part of a ring outline is stitching, and must
        # appear again reversed so its parity contribution cancels.
        for a, b in edges:
            if a == b:
                continue
            joins_rings = not (a in ring_points and b in ring_points)
            spans_two_rings = any(
                a in set(r1) and b in set(r2)
                for i, r1 in enumerate(rings)
                for j, r2 in enumerate(rings)
                if i != j
            )
            if joins_rings or spans_two_rings:
                assert (b, a) in edges, f"bridge {a}->{b} is never retraced"

    def test_each_ring_is_closed(self):
        rings = [
            [(0, 0), (10, 0), (10, 10)],
            [(100, 100), (110, 100), (110, 110)],
            [(200, 200), (210, 200), (210, 210)],
        ]
        path = self._fill(rings)
        for ring in rings:
            for point in ring:
                assert point in path

    def test_bridges_never_form_a_closed_loop_between_ring_starts(self):
        # The chain A->B->C->A is what produced the chequerboard: three distinct
        # bridge edges enclosing a region. Spokes from a hub cannot do that.
        rings = [
            [(0, 0), (10, 0), (10, 10)],
            [(100, 0), (110, 0), (110, 10)],
            [(0, 100), (10, 100), (10, 110)],
        ]
        edges = self._edges(self._fill(rings))
        starts = [r[0] for r in rings]
        chain = [(a, b) for a, b in edges if a in starts and b in starts and a != b]
        for a, b in chain:
            assert (b, a) in chain, "ring starts are chained rather than spoked"

    def test_a_single_ring_needs_no_stitching(self):
        path = self._fill([[(0, 0), (10, 0), (10, 10)]])
        assert len(path) <= 6

    def test_rings_with_too_few_points_are_skipped(self):
        assert self._fill([[(0, 0), (1, 1)]]) == []


@requires_display
@pytest.mark.display
@pytest.mark.usefixtures("real_window")
class TestWithAWindow:
    """Smoke tests against a real Tk window.

    These deliberately open as few windows as possible. Tk is not reliable when
    a single process creates and tears down many interpreters in quick
    succession -- the failure wanders between tests and reports a bogus "can't
    find init.tcl" -- so the checks that need a window are folded into one test
    rather than spread over a dozen. The drawing logic itself is covered
    headless, against the Canvas protocol, elsewhere in the suite.
    """

    def test_a_window_opens_draws_and_exports(self, tmp_path):
        destination = tmp_path / "nested" / "out.eps"
        with TurtleCanvas(640, 480, WHITE) as canvas:
            width, height = canvas.size
            # A window manager need not grant the size asked for, which is why
            # open() reports back instead of the caller assuming.
            assert width > 0 and height > 0

            canvas.fill_polygons([[(0, 0), (50, 0), (50, 50)]], Color(255, 0, 0))
            canvas.stroke_polyline([(0, 0), (50, 50)], Color(0, 0, 255), 2.0, False)
            canvas.frame()

            # Degenerate geometry must be ignored, not raise.
            canvas.fill_polygons([[(0, 0), (1, 1)]], Color(255, 0, 0))
            canvas.stroke_polyline([(0, 0)], BLACK, 1.0, False)

            # The .eps route needs no Ghostscript, so it always works, and the
            # export must create any missing directories.
            written = canvas.export(destination)
            assert written == destination
            assert written.read_text().startswith("%!PS")

        assert canvas._screen is None

    # There is deliberately no test here for reopening a window, though the
    # backend does support it (turtle's bye() leaves TurtleScreen._RUNNING False,
    # which would make every second window raise Terminator, so open() resets the
    # flag). A second Tk interpreter in the *same pytest process* fails
    # reliably on Windows with a spurious "can't find init.tcl", while a plain
    # script opens window after window quite happily. Asserting it here would
    # test pytest's process state rather than this code, so the reopen path is
    # exercised by scripts/smoke_render.py instead.
