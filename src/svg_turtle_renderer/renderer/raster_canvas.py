"""A headless raster backend.

The turtle canvas can only be photographed off the screen, which needs a display
and, for a clean result, Ghostscript. This draws the same ``Canvas`` operations
straight into a Pillow image instead, with no window at all. That buys two
things: a PNG export that works anywhere, and -- by snapshotting the image at
each frame -- an animated GIF of the drawing being made, which is the whole point
of the sketch and brush modes.

The image is supersampled and downscaled so the lines come out smooth, since
Pillow's own drawing is not antialiased.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from svg_turtle_renderer.core.exceptions import RenderError
from svg_turtle_renderer.geometry.coordinate_system import BoundingBox, Point
from svg_turtle_renderer.geometry.scanline import horizontal_spans
from svg_turtle_renderer.parser.color_parser import Color
from svg_turtle_renderer.utils.logger import get_logger

logger = get_logger(__name__)

# How many GIF frames to keep at most. A long sketch ticks hundreds of times;
# past this the file balloons for no visible gain, so frames are sampled evenly
# down to this count and the per-frame delay is stretched to hold the timing.
_MAX_GIF_FRAMES = 160


class RasterCanvas:
    """Draws ``Canvas`` operations into a Pillow image.

    Args:
        width: Logical canvas width in pixels.
        height: Logical canvas height in pixels.
        background: The page colour.
        supersample: Draw at this multiple of the size and downscale, for
            smoother edges than Pillow draws natively.
        capture_frames: Snapshot the image at every :meth:`frame`, for a GIF.

    Raises:
        RenderError: If Pillow is not installed.

    """

    def __init__(
        self,
        width: int,
        height: int,
        background: Color,
        supersample: int = 2,
        capture_frames: bool = False,
    ) -> None:
        """Create the backing image, or explain that Pillow is required."""
        try:
            from PIL import Image, ImageDraw
        except ImportError as exc:  # pragma: no cover - export is an optional extra
            raise RenderError(
                "Rasterising needs Pillow. Install it with "
                "pip install 'svg-turtle-renderer[export]'."
            ) from exc

        self._size = (width, height)
        self._scale = max(1, supersample)
        self._capture = capture_frames
        self._background = background
        self._frames: list = []

        self._image = Image.new(
            "RGB", (width * self._scale, height * self._scale), background.as_hex()
        )
        self._draw = ImageDraw.Draw(self._image)
        self._Image = Image

    @property
    def size(self) -> tuple[int, int]:
        """Return the logical canvas size."""
        return self._size

    @property
    def frame_count(self) -> int:
        """Return how many frames have been captured."""
        return len(self._frames)

    def _to_image(self, point: Point) -> tuple[float, float]:
        """Map a canvas-space point (origin centre, y up) to image pixels."""
        width, height = self._size
        return (
            (point[0] + width / 2.0) * self._scale,
            (height / 2.0 - point[1]) * self._scale,
        )

    # ------------------------------------------------------------------
    # Canvas protocol
    # ------------------------------------------------------------------

    def fill_polygons(self, rings: Sequence[Sequence[Point]], color: Color) -> None:
        """Fill one shape, honouring holes with the even-odd rule."""
        drawable = [list(ring) for ring in rings if len(ring) >= 3]
        if not drawable:
            return
        rgb = (color.r, color.g, color.b)
        if len(drawable) == 1:
            # A single ring has no holes, so Pillow's own polygon fill is both
            # correct and much faster than going scanline by scanline.
            self._draw.polygon([self._to_image(p) for p in drawable[0]], fill=rgb)
        else:
            self._scanline_fill(drawable, rgb)

    def _scanline_fill(self, rings: list[list[Point]], rgb: tuple[int, int, int]) -> None:
        """Fill a multi-ring shape row by row, so holes come out right."""
        box = BoundingBox.from_points(p for ring in rings for p in ring)
        if box is None:
            return
        # One image row per pixel, stepping in canvas units scaled up.
        step = 1.0 / self._scale
        y = box.min_y
        while y <= box.max_y:
            for x0, x1 in horizontal_spans(rings, y, even_odd=True):
                start = self._to_image((x0, y))
                end = self._to_image((x1, y))
                self._draw.line([start, end], fill=rgb, width=1)
            y += step

    def stroke_polyline(
        self, points: Sequence[Point], color: Color, width: float, closed: bool
    ) -> None:
        """Stroke a polyline with round joins and caps."""
        if len(points) < 2:
            return
        pixels = [self._to_image(p) for p in points]
        if closed:
            pixels.append(pixels[0])
        rgb = (color.r, color.g, color.b)
        line_width = max(1, round(width * self._scale))
        self._draw.line(pixels, fill=rgb, width=line_width, joint="curve")
        if line_width > 2:
            # Pillow rounds joints but not the free ends; a disc at each end gives
            # the round cap that makes a thick brush stroke look continuous.
            radius = line_width / 2.0
            for cx, cy in (pixels[0], pixels[-1]):
                self._draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=rgb)

    def frame(self) -> None:
        """Snapshot the current image when capturing for a GIF."""
        if self._capture:
            self._frames.append(self._downscaled())

    def show_cursor(self, visible: bool, kind: str = "pencil") -> None:
        """Ignore the cursor: an exported animation shows the drawing, not a tool."""

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def _downscaled(self):
        """Return the image at logical size, smoothed down from the supersample."""
        if self._scale == 1:
            return self._image.copy()
        return self._image.resize(self._size, self._Image.Resampling.LANCZOS)

    def save_png(self, path: str | Path) -> Path:
        """Write the finished image as a PNG."""
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._downscaled().save(destination)
        logger.info("Exported %s", destination)
        return destination

    def save_gif(self, path: str | Path, fps: int) -> Path:
        """Write the captured frames as an animated GIF.

        Args:
            path: The destination ``.gif``.
            fps: The rate the frames were captured at, which sets playback speed.

        Returns:
            The written path.

        Raises:
            RenderError: If no frames were captured.

        """
        if not self._frames:
            raise RenderError("No frames were captured; render with capture_frames=True")

        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)

        frames = self._sampled_frames()
        # Spread the original duration across however many frames survived, so the
        # animation still runs for the time it was drawn over.
        seconds = len(self._frames) / max(fps, 1)
        per_frame_ms = max(20, round(seconds * 1000 / len(frames)))

        # Hold the finished drawing at the end so it does not snap back to blank.
        hold = [frames[-1]] * max(1, round(1000 / per_frame_ms))
        sequence = frames + hold

        sequence[0].save(
            destination,
            save_all=True,
            append_images=sequence[1:],
            duration=per_frame_ms,
            loop=0,
            optimize=True,
            disposal=1,
        )
        logger.info("Exported %s (%d frames, %.1fs)", destination, len(sequence), seconds)
        return destination

    def _sampled_frames(self) -> list:
        """Return the captured frames, evenly thinned to the frame cap."""
        total = len(self._frames)
        if total <= _MAX_GIF_FRAMES:
            return list(self._frames)
        picks = [round(i * (total - 1) / (_MAX_GIF_FRAMES - 1)) for i in range(_MAX_GIF_FRAMES)]
        return [self._frames[i] for i in picks]
