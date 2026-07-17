"""Pacing for progressive drawing.

Turtle's own per-move animation is far too slow for real artwork -- a mandala
with 40,000 vertices would take hours. Instead the screen's tracer is switched
off and the image is presented at a fixed frame rate, which looks like drawing
while running at full speed.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Decides when the screen is redrawn during a render.

    Two implementations exist and they pull in opposite directions, which is why
    the renderer talks to the interface rather than either one: :class:`FrameClock`
    is handed work faster than it can show and drops frames; :class:`SketchClock`
    is handed work faster than it *should* show and waits.
    """

    @property
    def frames_presented(self) -> int:
        """Return how many frames have been presented."""
        ...

    def start(self) -> None:
        """Begin timing."""
        ...

    def tick(self) -> None:
        """Offer a frame; the clock decides what to do with it."""
        ...

    def final(self) -> None:
        """Present the finished image."""
        ...


class FrameClock:
    """Decides when a partially drawn image should be presented.

    Args:
        fps: Target presentations per second.
        present: The callback that actually redraws the screen.
        enabled: When false every method is a no-op, so the caller does not need
            to branch between animated and instant modes.

    """

    def __init__(self, fps: int, present: Callable[[], None], enabled: bool = True) -> None:
        """Configure the frame rate and the presentation callback."""
        self._interval = 1.0 / max(fps, 1)
        self._present = present
        self._enabled = enabled
        self._last = 0.0
        self._frames = 0

    @property
    def frames_presented(self) -> int:
        """Return how many frames have been presented."""
        return self._frames

    def start(self) -> None:
        """Begin timing, so the first frame is not presented immediately."""
        self._last = time.perf_counter()
        self._frames = 0

    def tick(self) -> None:
        """Present a frame if enough time has passed since the last one.

        Cheap to call after every shape: on a fast render the clock check is all
        that happens, and the expensive screen update is skipped.
        """
        if not self._enabled:
            return
        now = time.perf_counter()
        if now - self._last >= self._interval:
            self._last = now
            self._frames += 1
            self._present()

    def final(self) -> None:
        """Present the finished image, whatever the clock says."""
        self._frames += 1
        self._present()


class SketchClock:
    """Holds a steady frame rate by waiting, for the pencil sketch effect.

    :class:`FrameClock` and this are opposites, and the difference is the whole
    point. FrameClock is given work as fast as the machine can produce it and
    *drops* frames to stay at the target rate. A sketch has the reverse problem:
    the work for one frame takes a fraction of a frame's time, so it must *wait*,
    or the drawing finishes in a blink no matter what speed was asked for.

    The next deadline is advanced from the previous deadline rather than from the
    current time, so a frame that runs long is absorbed by the frames after it
    instead of making the whole drawing drift slower.

    Args:
        fps: Target frames per second.
        present: The callback that redraws the screen.

    """

    def __init__(self, fps: int, present: Callable[[], None]) -> None:
        """Configure the frame rate and the presentation callback."""
        self._interval = 1.0 / max(fps, 1)
        self._present = present
        self._deadline = 0.0
        self._frames = 0

    @property
    def frames_presented(self) -> int:
        """Return how many frames have been presented."""
        return self._frames

    def start(self) -> None:
        """Begin timing from now."""
        self._deadline = time.perf_counter() + self._interval
        self._frames = 0

    def tick(self) -> None:
        """Present a frame, then wait until its slot is used up."""
        self._present()
        self._frames += 1

        now = time.perf_counter()
        remaining = self._deadline - now
        if remaining > 0.0:
            time.sleep(remaining)
            self._deadline += self._interval
        else:
            # Already behind: give up the lost time rather than trying to claw
            # it back, which would only rush the frames that follow.
            self._deadline = now + self._interval

    def final(self) -> None:
        """Present the finished image without waiting."""
        self._frames += 1
        self._present()
