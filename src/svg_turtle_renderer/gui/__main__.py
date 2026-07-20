"""Run the dashboard with ``python -m svg_turtle_renderer.gui [files...]``."""

from __future__ import annotations

import sys

from svg_turtle_renderer.gui.dashboard import launch

sys.exit(launch(sys.argv[1:]))
