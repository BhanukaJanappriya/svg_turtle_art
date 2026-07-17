#!/usr/bin/env python3
"""Run the renderer straight from a checkout: ``python main.py artwork.svg``.

Installing the package (``pip install -e .``) provides the ``svg-turtle`` command
and is the better way to use it day to day. This shim exists so that a fresh
clone works with no install step, which is what most people try first.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the package importable from a checkout without installing it.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from svg_turtle_renderer.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
