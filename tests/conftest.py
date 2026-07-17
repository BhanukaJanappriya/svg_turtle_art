"""Shared fixtures.

The whole suite runs headless: nothing here opens a turtle window, because the
pipeline is built so that it does not have to.
"""

from __future__ import annotations

import logging

import pytest

from svg_turtle_renderer.core.config import RenderConfig
from svg_turtle_renderer.renderer.canvas import RecordingCanvas


@pytest.fixture(autouse=True)
def isolate_package_logging():
    """Undo any global logging changes a test makes.

    ``configure_logging`` attaches a handler and sets ``propagate = False`` on the
    package logger. That is correct for an application, but it is global state:
    once a test calls the CLI, ``caplog`` -- which captures through propagation to
    the root logger -- silently stops seeing records in every test that follows.
    Snapshotting and restoring keeps tests order-independent.
    """
    logger = logging.getLogger("svg_turtle_renderer")
    saved = (list(logger.handlers), logger.propagate, logger.level)
    try:
        yield
    finally:
        logger.handlers, logger.propagate, logger.level = saved


@pytest.fixture
def recording_canvas() -> RecordingCanvas:
    """Return a canvas that records drawing calls instead of painting them."""
    return RecordingCanvas()


@pytest.fixture
def svg_file(tmp_path):
    """Return a factory that writes SVG markup to a temporary file."""

    def _write(markup: str, name: str = "test.svg") -> str:
        path = tmp_path / name
        path.write_text(markup, encoding="utf-8")
        return str(path)

    return _write


@pytest.fixture
def config(tmp_path):
    """Return a factory for configurations pointing at a real temporary file."""

    def _build(**overrides) -> RenderConfig:
        path = overrides.pop("input_path", None)
        if path is None:
            path = tmp_path / "input.svg"
            path.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>')
        defaults = {"input_path": str(path), "show_progress": False, "keep_open": False}
        defaults.update(overrides)
        return RenderConfig(**defaults)

    return _build


SQUARE_SVG = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">
  <rect x="10" y="10" width="80" height="80" fill="red" stroke="blue" stroke-width="4"/>
</svg>
"""
