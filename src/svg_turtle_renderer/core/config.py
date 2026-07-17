"""Configuration for a rendering run.

:class:`RenderConfig` is the single source of truth for every knob the CLI, the
engine and the renderer share. It validates itself on construction, so an
invalid combination is caught before a window opens rather than halfway through
drawing.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Literal

from svg_turtle_renderer.core.exceptions import ConfigError

ColorMode = Literal["original", "mono", "random"]
FitMode = Literal["viewbox", "content"]

#: Named themes, applied before any explicit flag so the flag still wins.
THEMES: dict[str, dict[str, Any]] = {
    "dark": {"background": "#11131a", "mono_color": "#e6e6e6"},
    "light": {"background": "#ffffff", "mono_color": "#1a1a1a"},
    "blueprint": {"background": "#0b3d91", "mono_color": "#ffffff", "color_mode": "mono"},
    "sepia": {"background": "#f4ecd8", "mono_color": "#5b4636"},
    "neon": {"background": "#05050a", "color_mode": "random"},
}


@dataclass(slots=True)
class RenderConfig:
    """Everything a render needs to know.

    Attributes:
        input_path: The SVG file to render.
        output_path: Where to save a PNG, or ``None`` to skip export.
        canvas_width: Window width in pixels.
        canvas_height: Window height in pixels.
        fullscreen: Size the window to the screen instead.
        background: Page colour, in any notation the colour parser accepts.
        scale: Explicit scale factor, or ``None`` to fit automatically.
        margin: Padding kept clear around auto-fitted artwork, in pixels.
        fit: Whether to frame the viewBox or the artwork's own bounds.
        offset_x: Horizontal nudge in pixels.
        offset_y: Vertical nudge in pixels, positive being up.
        rotate: Clockwise rotation in degrees.
        mirror: Mirror horizontally.
        flip: Flip vertically.
        fill: Paint fills.
        stroke: Paint strokes.
        wireframe: Draw outlines only, in a single colour, ignoring paint.
        color_mode: Use the document's colours, one colour, or random colours.
        mono_color: The colour used by ``mono`` and wireframe modes.
        theme: A named preset from :data:`THEMES`.
        speed: Turtle's native per-move speed, 1 (slowest) to 10; 0 draws with
            no per-move animation, which is far faster. Ignored when ``animate``
            is set, since the two pace the screen differently.
        animate: Draw progressively, presenting frames at ``fps``.
        fps: Target screen updates per second while animating or sketching.
        sketch: Trace every shape's outline with a pencil before painting it,
            at a steady hand-speed, from a blank canvas.
        pencil_speed: How fast the pencil travels, in pixels per second.
        duration: Sketch for this many seconds, overriding ``pencil_speed``, so a
            drawing takes the same time whatever its size.
        pencil_color: The colour the pencil traces with. ``None`` traces each
            shape in its own ink.
        pencil_width: The pencil line's width in pixels.
        show_pencil: Show a pencil cursor following the line while sketching.
        resolution: Curve quality multiplier; higher is smoother and slower.
        simplify: Douglas-Peucker tolerance in pixels; 0 disables simplification.
        optimize_order: Reorder shapes to shorten pen travel.
        hide_turtle: Hide the cursor once drawing finishes.
        keep_open: Wait for a click before closing the window.
        show_progress: Display a progress bar.
        stats: Print document and timing statistics.
        strict: Fail on malformed paths and transforms instead of skipping them.
        verbose: Emit debug logging.
        quiet: Emit warnings and errors only.

    """

    input_path: str
    output_path: str | None = None

    canvas_width: int = 1000
    canvas_height: int = 800
    fullscreen: bool = False
    background: str = "white"

    scale: float | None = None
    margin: float = 20.0
    fit: FitMode = "viewbox"
    offset_x: float = 0.0
    offset_y: float = 0.0
    rotate: float = 0.0
    mirror: bool = False
    flip: bool = False

    fill: bool = True
    stroke: bool = True
    wireframe: bool = False
    color_mode: ColorMode = "original"
    mono_color: str = "black"
    theme: str | None = None

    speed: int = 0
    animate: bool = False
    fps: int = 30

    sketch: bool = False
    pencil_speed: float = 900.0
    duration: float | None = None
    pencil_color: str | None = None
    pencil_width: float = 1.0
    show_pencil: bool = True

    resolution: float = 1.0
    simplify: float = 0.0
    optimize_order: bool = False

    hide_turtle: bool = True
    keep_open: bool = True
    show_progress: bool = True
    stats: bool = False
    strict: bool = False
    verbose: bool = False
    quiet: bool = False

    #: Names of fields the user set explicitly, so a theme cannot clobber them.
    _explicit: frozenset[str] = field(default_factory=frozenset, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Apply the theme, then validate."""
        if self.theme is not None:
            self._apply_theme()
        self.validate()

    def _apply_theme(self) -> None:
        """Fill in theme defaults for fields the user did not set explicitly."""
        assert self.theme is not None
        preset = THEMES.get(self.theme.lower())
        if preset is None:
            raise ConfigError(
                f"Unknown theme {self.theme!r}. Available: {', '.join(sorted(THEMES))}"
            )
        for name, value in preset.items():
            if name not in self._explicit:
                setattr(self, name, value)

    def validate(self) -> None:
        """Check the configuration for internally inconsistent values.

        Raises:
            ConfigError: On the first problem found, described in terms of the
                CLI flag the user would have typed.

        """
        if not self.input_path:
            raise ConfigError("An input SVG path is required")
        if self.canvas_width < 100 or self.canvas_height < 100:
            raise ConfigError(
                f"Canvas must be at least 100x100 pixels, got "
                f"{self.canvas_width}x{self.canvas_height}"
            )
        if self.scale is not None and self.scale <= 0.0:
            raise ConfigError(f"--scale must be positive, got {self.scale}")
        if self.margin < 0.0:
            raise ConfigError(f"--margin cannot be negative, got {self.margin}")
        if not 0 <= self.speed <= 10:
            raise ConfigError(f"--speed must be between 0 and 10, got {self.speed}")
        if self.fps < 1:
            raise ConfigError(f"--fps must be at least 1, got {self.fps}")
        if self.pencil_speed <= 0.0:
            raise ConfigError(f"--pencil-speed must be positive, got {self.pencil_speed}")
        if self.duration is not None and self.duration <= 0.0:
            raise ConfigError(f"--duration must be positive, got {self.duration}")
        if self.pencil_width <= 0.0:
            raise ConfigError(f"--pencil-width must be positive, got {self.pencil_width}")
        if self.resolution <= 0.0:
            raise ConfigError(f"--resolution must be positive, got {self.resolution}")
        if self.simplify < 0.0:
            raise ConfigError(f"--simplify cannot be negative, got {self.simplify}")
        if self.fit not in ("viewbox", "content"):
            raise ConfigError(f"--fit must be 'viewbox' or 'content', got {self.fit!r}")
        if self.color_mode not in ("original", "mono", "random"):
            raise ConfigError(
                f"--color-mode must be 'original', 'mono' or 'random', got {self.color_mode!r}"
            )
        if not self.fill and not self.stroke and not self.wireframe:
            raise ConfigError(
                "Nothing would be drawn: --no-fill and --no-stroke are both set. "
                "Pass --wireframe to draw outlines only."
            )

    @property
    def turtle_speed(self) -> int:
        """Return the native turtle speed the backend should use.

        ``--animate`` and ``--sketch`` pace whole frames rather than individual
        pen moves, so they cannot share the screen with turtle's own animation.
        Either therefore forces it off; the progressive effect comes from the
        frame clock, which is orders of magnitude faster on real artwork.
        """
        return 0 if (self.animate or self.sketch) else self.speed

    def with_overrides(self, **changes: Any) -> RenderConfig:
        """Return a copy with ``changes`` applied and re-validated."""
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        """Return the configuration as a JSON-serialisable dictionary."""
        data = asdict(self)
        data.pop("_explicit", None)
        return data

    @classmethod
    def field_names(cls) -> frozenset[str]:
        """Return the names of every public configuration field."""
        return frozenset(f.name for f in fields(cls) if not f.name.startswith("_"))

    @classmethod
    def from_file(cls, path: str | Path, **overrides: Any) -> RenderConfig:
        """Load a configuration from a JSON file.

        Args:
            path: The JSON file to read.
            overrides: Values that take precedence over the file, normally the
                flags the user typed.

        Returns:
            The loaded configuration.

        Raises:
            ConfigError: If the file is missing, not valid JSON, or names a key
                that is not a configuration field.

        """
        config_path = Path(path)
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigError(f"Config file not found: {config_path}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Config file {config_path} is not valid JSON: {exc}") from exc
        except OSError as exc:
            raise ConfigError(f"Cannot read config file {config_path}: {exc}") from exc

        if not isinstance(raw, dict):
            raise ConfigError(f"Config file {config_path} must contain a JSON object")

        known = cls.field_names()
        unknown = set(raw) - known
        if unknown:
            raise ConfigError(
                f"Config file {config_path} has unknown keys: {', '.join(sorted(unknown))}"
            )

        merged: dict[str, Any] = {**raw, **overrides}
        explicit = frozenset(merged) - {"_explicit"}
        return cls(**merged, _explicit=explicit)
