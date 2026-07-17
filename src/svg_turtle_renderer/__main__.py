"""Support ``python -m svg_turtle_renderer artwork.svg``."""

from __future__ import annotations

import sys

from svg_turtle_renderer.cli import main

sys.exit(main())
