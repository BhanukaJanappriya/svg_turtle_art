"""The turtle backend.

:class:`TurtleCanvas` is the only module in the package that imports ``turtle``,
and it does so lazily inside :meth:`TurtleCanvas.open`. Everything else can be
imported, and tested, on a machine with no display.
"""

from __future__ import annotations

import io
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from svg_turtle_renderer.core.exceptions import RenderError
from svg_turtle_renderer.geometry.coordinate_system import Point
from svg_turtle_renderer.parser.color_parser import Color
from svg_turtle_renderer.utils.logger import get_logger

logger = get_logger(__name__)

# A pencil, drawn tip-first at the origin so the tip sits exactly on the point
# being drawn. turtle maps a shape's +y axis onto the heading (see _polytrafo in
# the turtle module), so a shape that runs from the tip at (0, 0) back along -y
# points forwards along the direction of travel once a heading is set.
_PENCIL_SHAPE = (
    (0.0, 0.0),  # tip, sitting exactly on the pen position
    (-2.0, -6.0),
    (-4.0, -13.0),  # collar where the sharpened wood meets the barrel
    (-4.0, -36.0),
    (-2.5, -40.0),  # ferrule
    (2.5, -40.0),
    (4.0, -36.0),
    (4.0, -13.0),
    (2.0, -6.0),
)
_PENCIL_SHAPE_NAME = "svg_turtle_pencil"

# A round paintbrush, likewise tip-first: soft bristles at the point, a metal
# ferrule, then the handle. Wider than the pencil so it reads as a brush.
_BRUSH_SHAPE = (
    (0.0, 0.0),  # bristle tip, on the pen position
    (-5.0, -7.0),
    (-6.0, -14.0),  # spread of the bristles
    (-4.0, -18.0),
    (-4.5, -30.0),  # ferrule
    (-3.0, -46.0),  # handle
    (3.0, -46.0),
    (4.5, -30.0),
    (4.0, -18.0),
    (6.0, -14.0),
    (5.0, -7.0),
)
_BRUSH_SHAPE_NAME = "svg_turtle_brush"

# Registry of cursor kinds: outline shape, its registered name, and the two
# colours (line, fill) it is drawn in.
_CURSORS = {
    "pencil": (_PENCIL_SHAPE, _PENCIL_SHAPE_NAME, ("#2b2b2b", "#e8b552")),
    "brush": (_BRUSH_SHAPE, _BRUSH_SHAPE_NAME, ("#5a3b1a", "#b5651d")),
}


class TurtleCanvas:
    """A drawing surface backed by Python's turtle graphics.

    The canvas is a context manager, so the window is always torn down even if
    rendering raises::

        with TurtleCanvas(1000, 800, WHITE) as canvas:
            canvas.stroke_polyline(points, BLACK, 2.0, closed=False)

    Args:
        width: Requested window width in pixels.
        height: Requested window height in pixels.
        background: Page colour.
        fullscreen: Size the window to the whole screen instead.
        speed: Turtle's native per-move speed, 1-10; 0 draws with no per-move
            animation, which is dramatically faster.
        title: Window title.

    """

    def __init__(
        self,
        width: int,
        height: int,
        background: Color,
        fullscreen: bool = False,
        speed: int = 0,
        title: str = "SVG Turtle Renderer",
    ) -> None:
        """Store window settings without touching turtle or tkinter yet."""
        self._requested = (width, height)
        self._background = background
        self._fullscreen = fullscreen
        self._speed = speed
        self._title = title

        self._screen: Any = None
        self._turtle: Any = None
        self._size: tuple[int, int] = (width, height)
        self._current_pen: tuple[Color, float] | None = None
        self._cursor: Any = None
        self._cursor_visible = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> tuple[int, int]:
        """Create the window and return the canvas size actually granted.

        The size is returned rather than assumed because a fullscreen window, or
        a window larger than the display, will not be the size that was asked
        for -- and the artwork has to be fitted to the real one.

        Returns:
            The canvas width and height in pixels.

        Raises:
            RenderError: If turtle or tkinter is unavailable, which on a server
                normally means there is no display.

        """
        try:
            import turtle
        except ImportError as exc:  # pragma: no cover - depends on the build
            raise RenderError(
                "Python's turtle module is unavailable. It requires tkinter; "
                "on Debian or Ubuntu install it with 'apt install python3-tk'."
            ) from exc

        # turtle keeps its state in class-level globals, and `bye()` leaves
        # `TurtleScreen._RUNNING` set to False. The next drawing operation then
        # hits `_incrementudc`, which raises Terminator *and* flips the flag back
        # to True -- so without this, reopening a window alternates between
        # working and failing. Restoring the flag lets one process render several
        # files in a row, which the library API otherwise invites and the test
        # suite depends on.
        turtle.TurtleScreen._RUNNING = True  # type: ignore[attr-defined]

        try:
            self._screen = turtle.Screen()
            if self._fullscreen:
                self._screen.setup(width=1.0, height=1.0)
            else:
                self._screen.setup(width=self._requested[0], height=self._requested[1])
            self._screen.title(self._title)
            self._screen.colormode(1.0)
            self._screen.bgcolor(self._background.as_turtle())
            # Batching is switched on unconditionally; the caller decides when a
            # frame is presented, via frame().
            self._screen.tracer(0, 0)

            self._turtle = self._new_turtle()
            self._turtle.hideturtle()
            self._turtle.penup()
            self._turtle.speed(self._speed if self._speed > 0 else 0)
            if self._speed > 0:
                # Native animation only makes sense when the screen is redrawing
                # each move, so hand tracing back to turtle itself.
                self._screen.tracer(1, 0)
        except Exception as exc:  # tkinter raises bare TclError on no display
            raise RenderError(f"Could not open a turtle window: {exc}") from exc

        self._size = (self._screen.window_width(), self._screen.window_height())
        logger.debug("Canvas opened at %dx%d", *self._size)
        return self._size

    @property
    def size(self) -> tuple[int, int]:
        """Return the canvas size in pixels."""
        return self._size

    def __enter__(self) -> TurtleCanvas:
        """Open the window and return the canvas."""
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Close the window."""
        self.close()

    def close(self) -> None:
        """Destroy the window, ignoring an already-closed one."""
        if self._screen is None:
            return
        try:
            self._screen.bye()
        except Exception:
            # The user closing the window themselves already tore down the Tcl
            # interpreter; there is nothing left to clean up.
            pass
        finally:
            self._screen = None
            self._turtle = None
            self._cursor = None
            self._cursor_visible = False

    def _require_turtle(self) -> Any:
        """Return the turtle, or explain that the canvas was never opened."""
        if self._turtle is None:
            raise RenderError("Canvas.open() must be called before drawing")
        return self._turtle

    def _new_turtle(self) -> Any:
        """Create a turtle on this canvas's screen.

        A subclass that embeds turtle in an existing Tk widget overrides this to
        bind new turtles -- the drawing pen and the cursor -- to its own screen
        rather than turtle's global singleton.
        """
        import turtle

        return turtle.Turtle(visible=False)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def fill_polygons(self, rings: Sequence[Sequence[Point]], color: Color) -> None:
        """Fill one shape, whose rings are painted as a single even-odd region.

        The pen stays up throughout: turtle records the fill path regardless of
        pen state, so lifting it fills without also stroking an unwanted outline
        in the fill colour.

        Tk fills a single polygon, so several rings have to be stitched into one
        point list, and the stitching must not paint anything itself. Every ring
        is therefore reached by a *spoke* out from a shared hub and left by the
        same spoke back: each bridge is traversed twice in opposite directions, so
        its even-odd contribution cancels exactly and only the rings survive.

        Walking the rings in a chain instead (A to B to C, letting end_fill close
        C back to A) does not cancel: the bridges form a polygon of their own,
        whose edges flip the parity of everything they enclose. With two rings the
        single bridge and the closing edge happen to coincide and it looks
        correct, which is exactly why the mistake survives a donut test and then
        chequerboards a 60-ring drawing.
        """
        pen = self._require_turtle()
        drawable = [ring for ring in rings if len(ring) >= 3]
        if not drawable:
            return

        pen.penup()
        pen.fillcolor(color.as_turtle())
        hub = drawable[0][0]
        pen.goto(*hub)
        pen.begin_fill()
        for ring in drawable:
            pen.goto(*ring[0])  # spoke out; degenerate for the first ring
            for x, y in ring[1:]:
                pen.goto(x, y)
            pen.goto(*ring[0])  # close the ring
            pen.goto(*hub)  # spoke back, retracing and cancelling
        pen.end_fill()

    def stroke_polyline(
        self, points: Sequence[Point], color: Color, width: float, closed: bool
    ) -> None:
        """Stroke a polyline with the pen down."""
        if len(points) < 2:
            return
        pen = self._require_turtle()

        # Pen changes force a new Tk line item, so skip them when nothing moved.
        desired = (color, width)
        if self._current_pen != desired:
            pen.pencolor(color.as_turtle())
            pen.pensize(max(width, 1.0))
            self._current_pen = desired

        pen.penup()
        pen.goto(*points[0])
        pen.pendown()
        for x, y in points[1:]:
            pen.goto(x, y)
        if closed:
            pen.goto(*points[0])
        pen.penup()

        # goto() never changes heading, so the cursor would otherwise point a
        # fixed direction while the pen moves. Aiming it along the last segment
        # is what makes the pencil look like it is being pushed along the line.
        # Only worth doing when the cursor is actually on screen -- it is two
        # extra calls per stroke, and a large drawing has thousands.
        if self._cursor_visible:
            self._aim_cursor(points)

    def frame(self) -> None:
        """Present what has been drawn so far."""
        if self._screen is None:
            return
        try:
            self._screen.update()
        except Exception:  # pragma: no cover - window closed mid-render
            pass

    def _aim_cursor(self, points: Sequence[Point]) -> None:
        """Move the cursor to the pen tip and point it along the stroke."""
        if self._cursor is None:
            return
        tail, head = points[-2], points[-1]
        self._cursor.goto(*head)
        dx, dy = head[0] - tail[0], head[1] - tail[1]
        if dx or dy:
            # Canvas space is y-up, which is turtle's own convention, so atan2
            # gives the heading directly.
            self._cursor.setheading(math.degrees(math.atan2(dy, dx)))

    def show_cursor(self, visible: bool, kind: str = "pencil") -> None:
        """Show or hide a pencil or brush cursor that follows the pen.

        The cursor gets a turtle of its own rather than reusing the drawing pen.
        A turtle's shape is painted in its *own* pen and fill colours, so sharing
        would repaint the cursor with every shape's ink; a separate turtle keeps
        its own look, and it can be moved without touching the drawing.
        """
        if self._turtle is None or self._screen is None:
            return
        self._cursor_visible = visible

        if not visible:
            if self._cursor is not None:
                self._cursor.hideturtle()
            return

        shape, name, colours = _CURSORS.get(kind, _CURSORS["pencil"])
        try:
            if self._cursor is None:
                self._cursor = self._new_turtle()
                self._cursor.penup()  # it must never draw
                self._cursor.speed(0)
            if name not in self._screen.getshapes():
                self._screen.register_shape(name, shape)
            self._cursor.shape(name)
            self._cursor.color(*colours)
        except Exception as exc:  # pragma: no cover - a cosmetic failure only
            logger.debug("Could not install the %s cursor: %s", kind, exc)
            self._cursor = None
            self._cursor_visible = False
            return

        self._cursor.showturtle()

    def show_turtle(self) -> None:
        """Reveal the turtle cursor at its final position."""
        if self._turtle is not None:
            self._turtle.showturtle()
            self.frame()

    def wait_for_click(self) -> None:
        """Block until the window is clicked or closed.

        A user closing the window is a normal way to end the program, not an
        error, so the resulting Tcl failure is swallowed.
        """
        if self._screen is None:
            return
        try:
            self._screen.exitonclick()
        except Exception:
            pass
        finally:
            self._screen = None
            self._turtle = None

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export(self, path: str | Path) -> Path:
        """Save the canvas to an image file.

        Tk itself can only export PostScript, so producing a raster image takes
        one of three routes, tried in order:

        1. Pillow rasterises the PostScript. Needs Ghostscript, and gives the
           best result -- it is a true render of the vector canvas.
        2. Pillow grabs the window from the screen. Needs no Ghostscript but
           captures whatever is physically on top of the window.
        3. The PostScript is written as ``.eps``.

        The drawing is never simply lost, and the route taken is logged.

        Args:
            path: The destination file. A ``.ps`` or ``.eps`` suffix skips
                rasterising entirely.

        Returns:
            The path actually written, which may differ in suffix.

        Raises:
            RenderError: If the canvas is not open, or PostScript export fails.

        """
        if self._screen is None:
            raise RenderError("Canvas.open() must be called before exporting")

        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.frame()

        width, height = self._size
        try:
            canvas = self._screen.getcanvas()
            postscript = canvas.postscript(
                colormode="color",
                x=-width / 2,
                y=-height / 2,
                width=width,
                height=height,
            )
        except Exception as exc:
            raise RenderError(f"Could not capture the canvas: {exc}") from exc

        if destination.suffix.lower() in (".ps", ".eps"):
            destination.write_text(postscript, encoding="utf-8")
            logger.info("Saved %s", destination)
            return destination

        try:
            from PIL import Image
        except ImportError:
            return self._save_postscript_fallback(
                destination,
                postscript,
                "Pillow is not installed (pip install 'svg-turtle-renderer[export]')",
            )

        try:
            opened = Image.open(io.BytesIO(postscript.encode("utf-8")))
            # EPS is vector: rasterising at 2x and downsampling is the cheapest
            # way to get an antialiased result out of Ghostscript. `scale` is
            # specific to EpsImageFile, which is what Image.open returns here.
            opened.load(scale=2)  # type: ignore[call-arg]
            image = opened.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)
            image.save(destination)
        except Exception as exc:
            logger.debug("PostScript rasterising failed: %s", exc)
            grabbed = self._export_by_screen_grab(destination)
            if grabbed is not None:
                return grabbed
            return self._save_postscript_fallback(
                destination,
                postscript,
                f"Could not rasterise the PostScript ({exc}), and grabbing the "
                f"window did not work either. Installing Ghostscript enables "
                f"proper PNG export",
            )

        logger.info("Exported %s", destination)
        return destination

    def _export_by_screen_grab(self, destination: Path) -> Path | None:
        """Save a PNG by capturing the window from the screen.

        This is the fallback when Ghostscript is absent. It is a screenshot, so
        it captures the window's actual pixels -- including anything overlapping
        it -- and it only works on a desktop session where the window is visible.

        Returns:
            The written path, or ``None`` if grabbing was not possible.

        """
        try:
            from PIL import Image, ImageGrab
        except ImportError:
            return None
        if self._screen is None:
            return None

        try:
            canvas = self._screen.getcanvas()
            root = canvas.winfo_toplevel()
            root.lift()
            root.update()
            # Let the compositor actually put the window on screen before the
            # grab; without this the capture can catch the previous frame.
            root.after(120, root.quit)
            root.mainloop()

            screenshot = ImageGrab.grab()

            # Tk reports positions in logical pixels while the screenshot is in
            # physical ones. On any display with OS scaling -- 125% and 150% are
            # the Windows defaults -- those differ, and cropping with unscaled
            # coordinates would capture the wrong region entirely. The ratio is
            # measured rather than assumed so this holds on any display.
            ratio = screenshot.width / root.winfo_screenwidth()
            left = canvas.winfo_rootx() * ratio
            top = canvas.winfo_rooty() * ratio
            box = (
                round(left),
                round(top),
                round(left + canvas.winfo_width() * ratio),
                round(top + canvas.winfo_height() * ratio),
            )
            image = screenshot.crop(box)
            if image.size != self._size:
                image = image.resize(self._size, Image.Resampling.LANCZOS)
            image.save(destination)
        except Exception as exc:
            logger.debug("Screen grab failed: %s", exc)
            return None

        logger.warning(
            "Ghostscript was not found, so %s was captured from the screen rather "
            "than rendered from the canvas. Anything overlapping the window will "
            "appear in it.",
            destination,
        )
        return destination

    def _save_postscript_fallback(self, destination: Path, postscript: str, reason: str) -> Path:
        """Write the drawing as EPS when rasterising is not possible."""
        fallback = destination.with_suffix(".eps")
        fallback.write_text(postscript, encoding="utf-8")
        logger.warning("%s; saved vector PostScript to %s instead", reason, fallback)
        return fallback
