#!/usr/bin/env python3
"""End-to-end smoke test against real turtle windows.

This lives outside the pytest suite on purpose. Opening several Tk interpreters
in one pytest process fails spuriously on Windows ("can't find init.tcl"), so the
multi-window paths -- which a plain script exercises perfectly well -- are checked
here instead.

Run it from the repository root::

    python scripts/smoke_render.py

It exits non-zero on the first failure, so CI can depend on it.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from svg_turtle_renderer.core.config import RenderConfig  # noqa: E402
from svg_turtle_renderer.core.engine import RenderEngine  # noqa: E402
from svg_turtle_renderer.parser.color_parser import BLACK, WHITE  # noqa: E402
from svg_turtle_renderer.renderer.turtle_renderer import TurtleCanvas  # noqa: E402

CHECKS: list[tuple[str, object]] = []


def check(name):
    """Register a smoke check."""

    def decorate(function):
        CHECKS.append((name, function))
        return function

    return decorate


@check("a window opens, draws and closes")
def _draws() -> None:
    with TurtleCanvas(400, 300, WHITE) as canvas:
        canvas.fill_polygons([[(0, 0), (60, 0), (60, 60)]], BLACK)
        canvas.stroke_polyline([(-50, -50), (50, 50)], BLACK, 2.0, False)
        canvas.frame()


@check("windows can be reopened repeatedly")
def _reopens() -> None:
    # turtle's bye() leaves TurtleScreen._RUNNING False, so without the backend's
    # reset every second window would raise Terminator. Four cycles catches the
    # alternation.
    for index in range(4):
        with TurtleCanvas(300, 200, WHITE) as canvas:
            canvas.stroke_polyline([(0, 0), (50, 50)], BLACK, 2.0, False)
            if canvas.size[0] <= 0:
                raise AssertionError(f"cycle {index}: window reported no width")


@check("several files render in one process")
def _renders_several() -> None:
    for name in ("sample.svg", "examples/features.svg"):
        path = ROOT / "assets" / name
        if not path.exists():
            continue
        config = RenderConfig(
            input_path=str(path),
            keep_open=False,
            show_progress=False,
            canvas_width=400,
            canvas_height=400,
        )
        stats = RenderEngine(config).run()
        if stats.shapes_painted == 0:
            raise AssertionError(f"{name}: nothing was painted")


@check("export always writes a file")
def _exports() -> None:
    with tempfile.TemporaryDirectory() as directory:
        destination = Path(directory) / "out.png"
        with TurtleCanvas(400, 300, WHITE) as canvas:
            canvas.stroke_polyline([(0, 0), (50, 50)], BLACK, 2.0, False)
            written = canvas.export(destination)
        if not written.exists():
            raise AssertionError("export produced no file")


def main() -> int:
    """Run every check, reporting the first failure."""
    failures = 0
    for name, function in CHECKS:
        try:
            function()
        except Exception as exc:  # noqa: BLE001 - a smoke runner reports anything
            print(f"FAIL  {name}\n      {type(exc).__name__}: {exc}")
            failures += 1
        else:
            print(f"ok    {name}")
    print(f"\n{len(CHECKS) - failures}/{len(CHECKS)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
