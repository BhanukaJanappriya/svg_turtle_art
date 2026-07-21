"""Tests for frame pacing."""

from __future__ import annotations

import pytest

from svg_turtle_renderer.renderer.animation import (
    CaptureClock,
    Clock,
    FrameClock,
    SketchClock,
)


class Recorder:
    """Counts presentation callbacks."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1


class FakeTime:
    """A monotonic clock the test drives by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def fake_time(monkeypatch):
    """Replace the animation module's clock with a controllable one."""
    clock = FakeTime()
    monkeypatch.setattr("svg_turtle_renderer.renderer.animation.time.perf_counter", clock)
    return clock


class TestDisabledClock:
    def test_ticking_a_disabled_clock_presents_nothing(self):
        present = Recorder()
        clock = FrameClock(30, present, enabled=False)
        clock.start()
        for _ in range(100):
            clock.tick()
        assert present.calls == 0

    def test_the_final_frame_is_presented_even_when_disabled(self):
        # Instant mode still has to show the finished image exactly once.
        present = Recorder()
        clock = FrameClock(30, present, enabled=False)
        clock.start()
        clock.final()
        assert present.calls == 1


class TestPacing:
    def test_no_frame_is_presented_before_the_interval_elapses(self, fake_time):
        present = Recorder()
        clock = FrameClock(10, present)
        clock.start()
        fake_time.advance(0.05)
        clock.tick()
        assert present.calls == 0

    def test_a_frame_is_presented_once_the_interval_elapses(self, fake_time):
        present = Recorder()
        clock = FrameClock(10, present)
        clock.start()
        fake_time.advance(0.1)
        clock.tick()
        assert present.calls == 1

    def test_many_ticks_within_one_interval_present_one_frame(self, fake_time):
        # This is the point of the clock: ticking after every shape is cheap.
        present = Recorder()
        clock = FrameClock(10, present)
        clock.start()
        fake_time.advance(0.1)
        for _ in range(50):
            clock.tick()
        assert present.calls == 1

    def test_frames_track_elapsed_time(self, fake_time):
        present = Recorder()
        clock = FrameClock(10, present)
        clock.start()
        for _ in range(5):
            fake_time.advance(0.1)
            clock.tick()
        assert present.calls == 5

    def test_a_higher_frame_rate_presents_more_often(self, fake_time):
        slow_present, fast_present = Recorder(), Recorder()
        slow = FrameClock(10, slow_present)
        fast = FrameClock(100, fast_present)
        slow.start()
        fast.start()
        for _ in range(10):
            fake_time.advance(0.01)
            slow.tick()
            fast.tick()
        assert fast_present.calls > slow_present.calls

    def test_frames_presented_is_reported(self, fake_time):
        clock = FrameClock(10, Recorder())
        clock.start()
        fake_time.advance(0.5)
        clock.tick()
        clock.final()
        assert clock.frames_presented == 2

    def test_start_resets_the_counter(self, fake_time):
        clock = FrameClock(10, Recorder())
        clock.start()
        fake_time.advance(0.5)
        clock.tick()
        clock.start()
        assert clock.frames_presented == 0

    def test_a_zero_fps_request_does_not_divide_by_zero(self):
        assert FrameClock(0, Recorder())._interval == 1.0


class TestSketchClock:
    """The sketch clock waits rather than dropping frames.

    Real sleeping is faked out here: the tests assert on how long it *asks* to
    sleep, which is the behaviour that matters and costs no wall-clock time.
    """

    @pytest.fixture
    def slept(self, monkeypatch, fake_time):
        """Capture sleep requests and advance the fake clock by them."""
        calls: list[float] = []

        def record(seconds):
            calls.append(seconds)
            fake_time.advance(seconds)

        monkeypatch.setattr("svg_turtle_renderer.renderer.animation.time.sleep", record)
        return calls

    def test_every_tick_presents_a_frame(self, fake_time, slept):
        # Unlike FrameClock, nothing is ever dropped: each chunk of pencil
        # movement is one frame by construction.
        present = Recorder()
        clock = SketchClock(10, present)
        clock.start()
        for _ in range(5):
            clock.tick()
        assert present.calls == 5

    def test_it_waits_out_the_rest_of_the_frame(self, fake_time, slept):
        clock = SketchClock(10, Recorder())
        clock.start()
        clock.tick()
        assert slept == [pytest.approx(0.1)]

    def test_work_taken_by_the_frame_is_deducted_from_the_wait(self, fake_time, slept):
        clock = SketchClock(10, Recorder())
        clock.start()
        fake_time.advance(0.04)  # drawing took 40ms of the 100ms frame
        clock.tick()
        assert slept == [pytest.approx(0.06)]

    def test_an_overrunning_frame_does_not_sleep(self, fake_time, slept):
        clock = SketchClock(10, Recorder())
        clock.start()
        fake_time.advance(0.5)  # took five frames' worth
        clock.tick()
        assert slept == []

    def test_a_late_frame_does_not_rush_the_ones_after_it(self, fake_time, slept):
        # After an overrun the clock restarts from now rather than trying to
        # catch up, so the pencil keeps a steady speed instead of lurching.
        clock = SketchClock(10, Recorder())
        clock.start()
        fake_time.advance(0.5)
        clock.tick()
        clock.tick()
        assert slept == [pytest.approx(0.1)]

    def test_a_steady_run_holds_the_frame_rate(self, fake_time, slept):
        clock = SketchClock(20, Recorder())
        clock.start()
        started = fake_time.now
        for _ in range(20):
            fake_time.advance(0.01)  # each frame does 10ms of drawing
            clock.tick()
        # 20 frames at 20fps is one second, regardless of the work per frame.
        assert fake_time.now - started == pytest.approx(1.0, abs=0.02)

    def test_the_final_frame_is_presented_without_waiting(self, fake_time, slept):
        present = Recorder()
        clock = SketchClock(10, present)
        clock.start()
        clock.final()
        assert present.calls == 1
        assert slept == []

    def test_frames_are_counted(self, fake_time, slept):
        clock = SketchClock(10, Recorder())
        clock.start()
        clock.tick()
        clock.final()
        assert clock.frames_presented == 2

    def test_a_zero_fps_request_does_not_divide_by_zero(self):
        assert SketchClock(0, Recorder())._interval == 1.0


class TestCaptureClock:
    def test_it_presents_every_tick_without_pacing(self):
        # For an offline recording there is no screen to keep up with, so every
        # intended frame is presented, none dropped.
        present = Recorder()
        clock = CaptureClock(present)
        clock.start()
        for _ in range(50):
            clock.tick()
        assert present.calls == 50

    def test_frames_are_counted(self):
        clock = CaptureClock(Recorder())
        clock.start()
        clock.tick()
        clock.tick()
        clock.final()
        assert clock.frames_presented == 3


class TestClockProtocol:
    def test_all_clocks_satisfy_the_protocol(self):
        # The renderer depends on the protocol, not on any concrete class.
        assert isinstance(FrameClock(30, Recorder()), Clock)
        assert isinstance(SketchClock(30, Recorder()), Clock)
        assert isinstance(CaptureClock(Recorder()), Clock)
