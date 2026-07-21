"""The command-line interface.

Every flag defaults to ``None`` rather than to the value in
:class:`~svg_turtle_renderer.core.config.RenderConfig`. That is deliberate: it is
the only way to tell "the user asked for white" from "nobody said", which in turn
lets a ``--theme`` or a ``--config`` file supply defaults without overwriting the
flags the user actually typed.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Any

from svg_turtle_renderer import __version__
from svg_turtle_renderer.core.config import THEMES, RenderConfig
from svg_turtle_renderer.core.engine import RenderEngine
from svg_turtle_renderer.core.exceptions import RenderError, SVGTurtleError
from svg_turtle_renderer.utils.logger import configure_logging, get_logger

logger = get_logger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130

_EPILOG = """\
examples:
  render with automatic fit and instant drawing
    %(prog)s artwork.svg

  watch a pencil draw it from a blank canvas
    %(prog)s artwork.svg --sketch

  sketch it in graphite, taking exactly 45 seconds however big it is
    %(prog)s artwork.svg --sketch --duration 45 --pencil-color '#555'

  watch it draw progressively on a dark background, then save a PNG
    %(prog)s artwork.svg --animate --fps 60 --theme dark --export out.png

  outlines only, in one colour, on a 1400x900 canvas
    %(prog)s map.svg --wireframe --width 1400 --height 900

  fit tightly to the artwork, zoom in and nudge it up
    %(prog)s logo.svg --fit content --scale 2.5 --offset-y 40

  fastest possible render of a very large file
    %(prog)s huge.svg --simplify 0.5 --resolution 0.5 --no-progress
"""


def _scale_type(value: str) -> float | None:
    """Parse ``--scale``, which is either ``auto`` or a positive number."""
    if value.strip().lower() == "auto":
        return None
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a number or 'auto', got {value!r}") from None
    if number <= 0.0:
        raise argparse.ArgumentTypeError(f"must be positive, got {number}")
    return number


def _positive_int(value: str) -> int:
    """Parse an integer that must be greater than zero."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected an integer, got {value!r}") from None
    if number <= 0:
        raise argparse.ArgumentTypeError(f"must be positive, got {number}")
    return number


def _positive_float(value: str) -> float:
    """Parse a float that must be greater than zero."""
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a number, got {value!r}") from None
    if number <= 0.0:
        raise argparse.ArgumentTypeError(f"must be positive, got {number}")
    return number


def _bed_size(value: str) -> tuple[float, float]:
    """Parse a ``WIDTHxHEIGHT`` plotter bed size in millimetres."""
    parts = value.lower().replace("mm", "").split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"expected WIDTHxHEIGHT, got {value!r}")
    try:
        width, height = float(parts[0]), float(parts[1])
    except ValueError:
        raise argparse.ArgumentTypeError(f"bed dimensions must be numbers, got {value!r}") from None
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError(f"bed dimensions must be positive, got {value!r}")
    return (width, height)


def _non_negative_float(value: str) -> float:
    """Parse a float that must not be negative."""
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a number, got {value!r}") from None
    if number < 0.0:
        raise argparse.ArgumentTypeError(f"cannot be negative, got {number}")
    return number


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser."""
    parser = argparse.ArgumentParser(
        prog="svg-turtle",
        description="Render SVG artwork with Python Turtle Graphics.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", metavar="INPUT.SVG", nargs="?", help="the SVG file to render")
    parser.add_argument(
        "--gui",
        action="store_true",
        help="open the desktop dashboard instead of rendering directly",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--config",
        metavar="FILE.JSON",
        help="load settings from a JSON file; flags given here still win",
    )

    canvas = parser.add_argument_group("canvas")
    canvas.add_argument("--width", type=_positive_int, help="window width in pixels (default 1000)")
    canvas.add_argument(
        "--height", type=_positive_int, help="window height in pixels (default 800)"
    )
    canvas.add_argument(
        "--fullscreen", action="store_true", default=None, help="use the whole screen"
    )
    canvas.add_argument(
        "--background", "--bg", metavar="COLOR", help="page colour, e.g. black or '#11131a'"
    )
    canvas.add_argument(
        "--theme",
        choices=sorted(THEMES),
        help="a preset that sets the background and colours",
    )

    framing = parser.add_argument_group("framing")
    framing.add_argument(
        "--scale", type=_scale_type, metavar="N|auto", help="scale factor, or 'auto' to fit"
    )
    framing.add_argument(
        "--fit",
        choices=("viewbox", "content"),
        help="frame the document's viewBox (default) or the artwork's own bounds",
    )
    framing.add_argument(
        "--margin", type=_non_negative_float, metavar="PX", help="padding when fitting (default 20)"
    )
    framing.add_argument("--offset-x", type=float, metavar="PX", help="nudge right")
    framing.add_argument("--offset-y", type=float, metavar="PX", help="nudge up")
    framing.add_argument("--rotate", type=float, metavar="DEG", help="rotate clockwise")
    framing.add_argument("--mirror", action="store_true", default=None, help="mirror horizontally")
    framing.add_argument("--flip", action="store_true", default=None, help="flip vertically")

    paint = parser.add_argument_group("paint")
    paint.add_argument(
        "--fill",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="paint fills (default on)",
    )
    paint.add_argument(
        "--stroke",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="paint strokes (default on)",
    )
    paint.add_argument(
        "--wireframe", action="store_true", default=None, help="outlines only, ignoring paint"
    )
    paint.add_argument(
        "--color-mode",
        choices=("original", "mono", "random"),
        help="use the document's colours (default), one colour, or random ones",
    )
    paint.add_argument("--mono-color", metavar="COLOR", help="the colour for mono and wireframe")

    drawing = parser.add_argument_group("drawing")
    drawing.add_argument(
        "--speed",
        type=int,
        choices=range(11),
        metavar="0-10",
        help="turtle pen speed; 0 is instant",
    )
    drawing.add_argument(
        "--animate", "--animation", action="store_true", default=None, help="draw progressively"
    )
    drawing.add_argument(
        "--fps", type=_positive_int, help="frames per second while animating or sketching"
    )

    pencil = parser.add_argument_group("pencil sketch")
    pencil.add_argument(
        "--sketch",
        action="store_true",
        default=None,
        help="draw from a blank canvas, tracing each outline with a pencil",
    )
    pencil.add_argument(
        "--brush",
        action="store_true",
        default=None,
        help="sketch with a paintbrush: thick coloured strokes and brush-row fills",
    )
    pencil.add_argument(
        "--sketch-tool",
        choices=("pencil", "brush"),
        help="the drawing tool for a sketch (default pencil)",
    )
    pencil.add_argument(
        "--brush-width",
        type=_positive_float,
        metavar="PX",
        help="brush stroke width in pixels (default 9)",
    )
    pencil.add_argument(
        "--pencil-speed",
        type=_positive_float,
        metavar="PX",
        help="pencil speed in pixels per second (default 900)",
    )
    pencil.add_argument(
        "--duration",
        type=_positive_float,
        metavar="SEC",
        help="finish the sketch in this many seconds, whatever the drawing's size",
    )
    pencil.add_argument(
        "--pencil-color",
        metavar="COLOR",
        help="pencil colour; the default traces each shape in its own ink",
    )
    pencil.add_argument(
        "--pencil-width", type=_positive_float, metavar="PX", help="pencil line width (default 1)"
    )
    pencil.add_argument(
        "--show-pencil",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="show a pencil cursor following the line (default on)",
    )
    pencil.add_argument(
        "--fill-flow",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="stream each fill in as a colour front instead of applying it at once (default on)",
    )
    drawing.add_argument(
        "--hide-turtle",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="hide the cursor when finished (default on)",
    )
    drawing.add_argument(
        "--keep-open",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="wait for a click before closing (default on)",
    )

    quality = parser.add_argument_group("quality and performance")
    quality.add_argument(
        "--resolution",
        type=float,
        metavar="N",
        help="curve smoothness multiplier; higher is smoother and slower (default 1.0)",
    )
    quality.add_argument(
        "--simplify",
        type=_non_negative_float,
        metavar="PX",
        help="drop vertices within this many pixels of the line; 0 disables (default)",
    )
    quality.add_argument(
        "--optimize-order",
        action="store_true",
        default=None,
        help="reorder shapes to shorten pen travel; stroke-only drawings",
    )

    output = parser.add_argument_group("output")
    output.add_argument(
        "--export",
        "--output",
        "-o",
        dest="output",
        metavar="FILE",
        help="save the drawing; a .gif records the animation, other extensions save the still",
    )
    output.add_argument(
        "--headless",
        action="store_true",
        default=None,
        help="render straight to the export file with no window (needs Pillow)",
    )
    output.add_argument(
        "--bed",
        type=_bed_size,
        metavar="WxH",
        help="plotter bed size in mm for a .gcode export (default 210x297)",
    )
    output.add_argument(
        "--feed", type=_positive_float, metavar="MM_MIN", help="plotter drawing speed (mm/min)"
    )
    output.add_argument("--stats", action="store_true", default=None, help="print statistics")
    output.add_argument(
        "--show-progress",
        action=argparse.BooleanOptionalAction,
        dest="show_progress",
        default=None,
        help="show a progress bar (default on)",
    )
    output.add_argument("--strict", action="store_true", default=None, help="fail on malformed SVG")
    output.add_argument("-v", "--verbose", action="store_true", default=None, help="debug logging")
    output.add_argument(
        "-q", "--quiet", action="store_true", default=None, help="warnings and errors only"
    )
    return parser


def _collect_overrides(args: argparse.Namespace) -> dict[str, Any]:
    """Map parsed arguments onto configuration fields.

    Only arguments the user actually supplied are returned, so everything else
    falls through to the config file, then the theme, then the dataclass default.
    """
    mapping = {
        "input": "input_path",
        "output": "output_path",
        "width": "canvas_width",
        "height": "canvas_height",
    }
    skip = {"config"}

    overrides: dict[str, Any] = {}
    known = RenderConfig.field_names()
    for name, value in vars(args).items():
        if name in skip or value is None:
            continue
        field_name = mapping.get(name, name)
        if field_name in known:
            overrides[field_name] = value
    return overrides


def build_config(argv: Sequence[str] | None = None) -> RenderConfig:
    """Parse arguments into a validated configuration.

    Args:
        argv: The argument list, defaulting to ``sys.argv[1:]``.

    Returns:
        The configuration for this run.

    Raises:
        SystemExit: If the arguments are unusable, via argparse.
        ConfigError: If the resulting settings are inconsistent.

    """
    args = build_parser().parse_args(argv)
    overrides = _collect_overrides(args)

    # --scale auto resolves to None, which _collect_overrides drops as "unset".
    # That is the right outcome anyway, since None already means "fit
    # automatically" -- but it must not be lost when a config file sets a scale.
    if "--scale" in (argv if argv is not None else sys.argv[1:]) and args.scale is None:
        overrides["scale"] = None

    # --brush is a shorthand: it turns a sketch on and selects the brush tool,
    # without the user having to type --sketch --sketch-tool brush.
    if args.brush:
        overrides["sketch"] = True
        overrides.setdefault("sketch_tool", "brush")

    if args.config:
        return RenderConfig.from_file(args.config, **overrides)
    return RenderConfig(**overrides, _explicit=frozenset(overrides))


def _export_gcode(config: RenderConfig, args: argparse.Namespace) -> int:
    """Parse the input and write pen-plotter G-code to the export path."""
    from svg_turtle_renderer.core.gcode import GCodeOptions, to_gcode
    from svg_turtle_renderer.parser.svg_parser import SVGParser

    drawing = SVGParser(resolution=config.resolution, strict=config.strict).parse_file(
        config.input_path
    )
    bed = args.bed or (210.0, 297.0)
    options = GCodeOptions(
        bed_width=bed[0],
        bed_height=bed[1],
        margin=config.margin,
        feed=args.feed or 1000.0,
        simplify=config.simplify,
        optimize=config.optimize_order or True,
    )
    text = to_gcode(drawing, options)
    from pathlib import Path

    destination = Path(config.output_path)  # type: ignore[arg-type]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")
    logger.info("Wrote %s (%d lines)", destination, text.count("\n"))
    if config.stats:
        strokes = sum(1 for line in text.splitlines() if line.startswith("G0 X"))
        print(f"Plotter G-code: {strokes} strokes, bed {bed[0]:g}x{bed[1]:g} mm")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface.

    Args:
        argv: The argument list, defaulting to ``sys.argv[1:]``.

    Returns:
        A process exit code.

    """
    args = build_parser().parse_args(argv)

    if args.gui:
        # The dashboard is preloaded with the input file when one was given.
        configure_logging(verbose=args.verbose, quiet=args.quiet)
        from svg_turtle_renderer.gui.dashboard import launch

        return launch([args.input] if args.input else [])

    if not args.input:
        print("error: an input SVG file is required (or pass --gui)", file=sys.stderr)
        return EXIT_USAGE

    try:
        config = build_config(argv)
    except SVGTurtleError as exc:
        # Logging is not configured yet, so this goes straight to stderr.
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    configure_logging(verbose=config.verbose, quiet=config.quiet)

    # A .gcode export writes pen-plotter toolpaths, not pixels; it needs neither
    # a window nor Pillow.
    if config.output_path and config.output_path.lower().endswith((".gcode", ".nc", ".gc")):
        try:
            return _export_gcode(config, args)
        except SVGTurtleError as exc:
            logger.error("%s", exc)
            return EXIT_ERROR

    # A .gif export is recorded headlessly, frame by frame, with no window; the
    # same route gives a Ghostscript-free PNG when --headless is asked for.
    wants_gif = config.output_path and config.output_path.lower().endswith(".gif")
    if config.output_path and (wants_gif or config.headless):
        try:
            from svg_turtle_renderer.core.export import export as export_headless

            stats = export_headless(config, config.output_path)
        except SVGTurtleError as exc:
            logger.error("%s", exc)
            return EXIT_ERROR
        if config.stats:
            print(stats.format_report())
        return EXIT_OK

    try:
        engine = RenderEngine(config)
        stats = engine.run()
    except KeyboardInterrupt:
        logger.warning("Cancelled")
        return EXIT_INTERRUPTED
    except RenderError as exc:
        logger.error("%s", exc)
        return EXIT_ERROR
    except SVGTurtleError as exc:
        logger.error("%s", exc)
        if config.verbose:
            logger.exception("Traceback:")
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001 - the CLI is the last line of defence
        logger.error("Unexpected failure: %s", exc)
        logger.error("Please report this at https://github.com/bhanuka/svg-turtle-renderer/issues")
        if config.verbose:
            logger.exception("Traceback:")
        return EXIT_ERROR

    if config.stats:
        print(stats.format_report())
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
