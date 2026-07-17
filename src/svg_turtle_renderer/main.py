"""Module entry point, so the package can be run with ``python -m``."""

from __future__ import annotations

import sys

from svg_turtle_renderer.cli import main

if __name__ == "__main__":
    sys.exit(main())
