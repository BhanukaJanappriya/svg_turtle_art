"""Embedding the turtle canvas inside a Tk widget, and pacing it in a GUI.

The standalone renderer owns its own window and blocks on a click. A dashboard
cannot: the window belongs to the application, and the event loop must keep
running so the controls stay live and the Stop button responds. These two pieces
adapt the renderer to that world without touching its drawing code.

* :class:`EmbeddedTurtleCanvas` draws onto a ``tkinter.Canvas`` the dashboard
  owns, reusing every drawing method from :class:`TurtleCanvas`.
* :class:`GuiClock` paces the animation by pumping the Tk event loop instead of
  sleeping, so a long render never freezes the interface, and it raises out of
  the render when the user asks to stop.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from svg_turtle_renderer.core.exceptions import RenderError, RenderInterrupted
from svg_turtle_renderer.parser.color_parser import Color
from svg_turtle_renderer.renderer.turtle_renderer import TurtleCanvas
from svg_turtle_renderer.utils.logger import get_logger

logger = get_logger(__name__)


class EmbeddedTurtleCanvas(TurtleCanvas):
    """A turtle canvas that draws inside a Tk widget the caller owns.

    All the drawing, cursor and export logic is inherited unchanged; only the
    lifecycle differs. The window is not ours to create or destroy, so ``open``
    attaches to the supplied widget and ``close`` merely clears our own turtles.

    Args:
        widget: The ``tkinter.Canvas`` to draw on.
        background: The page colour.

    """

    def __init__(self, widget: Any, background: Color) -> None:
        """Wrap an existing Tk canvas widget."""
        width = max(int(widget.winfo_width()), 1)
        height = max(int(widget.winfo_height()), 1)
        super().__init__(width=width, height=height, background=background)
        self._widget = widget

    def _new_turtle(self) -> Any:
        """Create a turtle bound to the embedded screen, not turtle's singleton."""
        import turtle

        return turtle.RawTurtle(self._screen, visible=False)

    def open(self) -> tuple[int, int]:
        """Attach a turtle screen to the widget and return its size."""
        try:
            import turtle
        except ImportError as exc:  # pragma: no cover - depends on the build
            raise RenderError("Python's turtle module is unavailable.") from exc

        # turtle's class-level running flag must be set, exactly as the windowed
        # canvas does, or a second render in the same process fails.
        turtle.TurtleScreen._RUNNING = True  # type: ignore[attr-defined]
        try:
            self._screen = turtle.TurtleScreen(self._widget)
            self._screen.colormode(1.0)
            self._screen.bgcolor(self._background.as_turtle())
            self._screen.tracer(0, 0)
            self._turtle = self._new_turtle()
            self._turtle.hideturtle()
            self._turtle.penup()
        except Exception as exc:  # pragma: no cover - depends on the display
            raise RenderError(f"Could not attach a turtle canvas: {exc}") from exc

        self._widget.update_idletasks()
        self._size = (max(self._widget.winfo_width(), 1), max(self._widget.winfo_height(), 1))
        return self._size

    def set_background(self, background: Color) -> None:
        """Change the page colour of the live canvas."""
        self._background = background
        if self._screen is not None:
            self._screen.bgcolor(background.as_turtle())

    def clear(self) -> None:
        """Wipe the canvas for a fresh drawing, keeping the screen attached."""
        self._current_pen = None
        if self._turtle is not None:
            self._turtle.clear()
        if self._cursor is not None:
            self._cursor.clear()
            self._cursor.hideturtle()
        self._cursor_visible = False
        self.frame()

    def refit(self) -> tuple[int, int]:
        """Re-read the widget size after a resize and return it."""
        self._widget.update_idletasks()
        self._size = (max(self._widget.winfo_width(), 1), max(self._widget.winfo_height(), 1))
        return self._size

    def close(self) -> None:
        """Detach without destroying the widget, which the dashboard owns."""
        self._turtle = None
        self._cursor = None
        self._cursor_visible = False
        self._screen = None

    def wait_for_click(self) -> None:  # pragma: no cover - never used in the GUI
        """Do nothing: the dashboard owns the window's lifetime, not the canvas."""

    def _export_by_screen_grab(self, destination: Any) -> Any:  # pragma: no cover - display
        """Grab the canvas widget without the windowed backend's mainloop dance.

        The parent runs a nested ``mainloop`` to bring a standalone window to the
        front before grabbing it. The dashboard's window is already up and its
        event loop is already running, so a nested loop would be both unnecessary
        and fragile; a plain repaint before the grab is enough.
        """
        from pathlib import Path

        try:
            from PIL import ImageGrab
        except ImportError:
            return None
        if self._screen is None:
            return None

        try:
            widget = self._screen.getcanvas()
            widget.update_idletasks()
            screenshot = ImageGrab.grab()
            ratio = screenshot.width / widget.winfo_screenwidth()
            left = widget.winfo_rootx() * ratio
            top = widget.winfo_rooty() * ratio
            box = (
                round(left),
                round(top),
                round(left + widget.winfo_width() * ratio),
                round(top + widget.winfo_height() * ratio),
            )
            image = screenshot.crop(box)
            image.save(Path(destination))
        except Exception as exc:
            logger.debug("Canvas grab failed: %s", exc)
            return None

        logger.warning(
            "Ghostscript was not found, so %s was captured from the screen. "
            "Anything overlapping the canvas will appear in it.",
            destination,
        )
        return Path(destination)


class GuiClock:
    """Paces a render inside a live Tk event loop.

    Where :class:`~svg_turtle_renderer.renderer.animation.SketchClock` sleeps
    between frames, this pumps the event loop instead. That keeps the controls
    responsive and lets the Stop button take effect: the button sets a flag, and
    the clock raises :class:`RenderInterrupted` at the next frame so the render
    unwinds and leaves the partial drawing in place.

    The clock satisfies the same protocol as the other clocks, so the renderer
    drives it without knowing it is in a GUI.

    Args:
        fps: Target frames per second.
        present: Redraws the canvas.
        pump: Processes pending Tk events, typically ``root.update``.
        should_stop: Returns true when the user has asked to stop.
        paced: When false, frames are shown as fast as they arrive (for an
            instant render); when true, they are held to ``fps``.

    """

    def __init__(
        self,
        fps: int,
        present: Callable[[], None],
        pump: Callable[[], None],
        should_stop: Callable[[], bool],
        paced: bool = True,
    ) -> None:
        """Configure the frame rate and the event-loop hooks."""
        self._interval = 1.0 / max(fps, 1)
        self._present = present
        self._pump = pump
        self._should_stop = should_stop
        self._paced = paced
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
        self._check_stop()

    def tick(self) -> None:
        """Present a frame, keep the interface alive, and hold the frame rate."""
        self._present()
        self._frames += 1
        self._pump()
        self._check_stop()

        if not self._paced:
            return
        now = time.perf_counter()
        remaining = self._deadline - now
        if remaining > 0.0:
            # Spend the rest of the frame pumping events rather than sleeping, so
            # the controls stay live and a stop is noticed promptly.
            end = self._deadline
            while time.perf_counter() < end:
                self._pump()
                self._check_stop()
                time.sleep(0.001)
            self._deadline += self._interval
        else:
            self._deadline = now + self._interval

    def final(self) -> None:
        """Present the finished image without waiting."""
        self._frames += 1
        self._present()
        self._pump()

    def _check_stop(self) -> None:
        """Raise out of the render if the user has asked to stop."""
        if self._should_stop():
            raise RenderInterrupted
