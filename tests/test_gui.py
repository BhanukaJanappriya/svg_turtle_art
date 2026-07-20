"""Tests for the dashboard's non-display logic.

The tkinter widgets need a screen and are covered by scripts/smoke_render.py.
The pacing clock and the progress reporter are pure logic and are tested here,
because getting the stop signal and the throttling right is what keeps the
dashboard responsive.
"""

from __future__ import annotations

import pytest

from svg_turtle_renderer.core.exceptions import RenderInterrupted
from svg_turtle_renderer.gui.render_job import GuiProgress
from svg_turtle_renderer.gui.tk_canvas import GuiClock


class Recorder:
    """Counts calls."""

    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1


class FakeTime:
    """A clock the test drives by hand."""

    def __init__(self):
        self.now = 1000.0

    def perf_counter(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def fake_time(monkeypatch):
    """Replace the clock the GUI pacing uses."""
    clock = FakeTime()
    monkeypatch.setattr("svg_turtle_renderer.gui.tk_canvas.time.perf_counter", clock.perf_counter)
    monkeypatch.setattr("svg_turtle_renderer.gui.tk_canvas.time.sleep", clock.sleep)
    return clock


class TestGuiClock:
    def test_a_tick_presents_and_pumps(self, fake_time):
        present, pump = Recorder(), Recorder()
        clock = GuiClock(30, present, pump, lambda: False, paced=False)
        clock.start()
        clock.tick()
        assert present.calls == 1
        assert pump.calls >= 1

    def test_it_pumps_the_event_loop_rather_than_freezing(self, fake_time):
        # The whole reason the GUI clock exists: while it waits out a frame it
        # keeps the interface alive by pumping, not by sleeping blindly.
        pump = Recorder()
        clock = GuiClock(10, Recorder(), pump, lambda: False, paced=True)
        clock.start()
        before = pump.calls
        clock.tick()  # a 100ms frame at 10fps, pumped in ~1ms steps
        assert pump.calls > before + 10

    def test_an_unpaced_clock_does_not_wait(self, fake_time):
        pump = Recorder()
        clock = GuiClock(1, Recorder(), pump, lambda: False, paced=False)
        clock.start()
        start = fake_time.now
        clock.tick()
        assert fake_time.now == start  # no sleeping at all

    def test_stop_raises_out_of_a_tick(self, fake_time):
        flag = {"stop": False}
        clock = GuiClock(30, Recorder(), Recorder(), lambda: flag["stop"], paced=False)
        clock.start()
        clock.tick()  # fine
        flag["stop"] = True
        with pytest.raises(RenderInterrupted):
            clock.tick()

    def test_stop_is_noticed_at_start(self, fake_time):
        clock = GuiClock(30, Recorder(), Recorder(), lambda: True, paced=False)
        with pytest.raises(RenderInterrupted):
            clock.start()

    def test_stop_is_noticed_while_pacing(self, fake_time):
        # A stop requested during the wait must not have to wait out the frame.
        pumped = {"n": 0}

        def should_stop():
            pumped["n"] += 1
            return pumped["n"] > 3  # trips partway through the pacing loop

        clock = GuiClock(2, Recorder(), Recorder(), should_stop, paced=True)
        clock.start()
        with pytest.raises(RenderInterrupted):
            clock.tick()

    def test_frames_are_counted(self, fake_time):
        clock = GuiClock(30, Recorder(), Recorder(), lambda: False, paced=False)
        clock.start()
        clock.tick()
        clock.tick()
        clock.final()
        assert clock.frames_presented == 3

    def test_final_presents_without_waiting(self, fake_time):
        present = Recorder()
        clock = GuiClock(1, present, Recorder(), lambda: False, paced=True)
        clock.start()
        start = fake_time.now
        clock.final()
        assert present.calls == 1
        assert fake_time.now == start

    def test_a_zero_fps_request_does_not_divide_by_zero(self):
        assert GuiClock(0, Recorder(), Recorder(), lambda: False)._interval == 1.0


class TestGuiProgress:
    def test_it_reports_when_it_moves_enough(self):
        seen = []
        progress = GuiProgress(100.0, "px", lambda done, total, unit: seen.append(done))
        for _ in range(100):
            progress.advance(1.0)
        # Throttled to a report roughly every 0.4% -- far fewer than 100 calls,
        # but enough to look smooth.
        assert 0 < len(seen) <= 100

    def test_tiny_advances_are_coalesced(self):
        seen = []
        progress = GuiProgress(1000.0, "px", lambda done, total, unit: seen.append(done))
        for _ in range(1000):
            progress.advance(0.1)  # 0.01% each, below the refresh threshold
        # A thousand sub-threshold advances collapse into a handful of repaints.
        assert len(seen) < 50

    def test_close_snaps_to_full(self):
        seen = []
        progress = GuiProgress(100.0, "px", lambda done, total, unit: seen.append((done, total)))
        progress.advance(10.0)
        progress.close()
        assert seen[-1] == (100.0, 100.0)

    def test_the_unit_is_passed_through(self):
        seen = []
        progress = GuiProgress(5.0, "shape", lambda done, total, unit: seen.append(unit))
        progress.advance(1.0)
        progress.close()
        assert seen[-1] == "shape"

    def test_a_zero_total_does_not_divide_by_zero(self):
        progress = GuiProgress(0.0, "px", lambda *a: None)
        progress.advance(1.0)
        progress.close()
