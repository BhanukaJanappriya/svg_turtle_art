"""Logging setup for the package.

The library never configures the root logger on import; :func:`configure_logging`
is called by the CLI, so an embedding application keeps control of its own
logging.
"""

from __future__ import annotations

import logging
import sys

_PACKAGE_LOGGER = "svg_turtle_renderer"


class _ColorFormatter(logging.Formatter):
    """A formatter that tints the level name when the stream is a terminal."""

    _COLORS = {
        logging.DEBUG: "\033[36m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[1;31m",
    }
    _RESET = "\033[0m"

    def __init__(self, fmt: str, use_color: bool) -> None:
        """Store the format string and whether to emit escape codes."""
        super().__init__(fmt)
        self._use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        """Format ``record``, colouring its level name where supported."""
        if not self._use_color:
            return super().format(record)
        color = self._COLORS.get(record.levelno, "")
        original = record.levelname
        record.levelname = f"{color}{original}{self._RESET}"
        try:
            return super().format(record)
        finally:
            # Handlers share the record, so the mutation must not leak.
            record.levelname = original


def configure_logging(verbose: bool = False, quiet: bool = False) -> None:
    """Attach a single stderr handler to the package logger.

    Logs go to stderr so that piping stdout stays clean, and the handler is
    replaced rather than added to, which keeps repeated calls idempotent.

    Args:
        verbose: Emit debug-level detail.
        quiet: Emit warnings and errors only. Takes precedence over ``verbose``.

    """
    logger = logging.getLogger(_PACKAGE_LOGGER)
    level = logging.WARNING if quiet else (logging.DEBUG if verbose else logging.INFO)
    logger.setLevel(level)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    fmt = "%(levelname)s  %(message)s" if not verbose else "%(levelname)s  %(name)s: %(message)s"
    handler.setFormatter(_ColorFormatter(fmt, use_color=sys.stderr.isatty()))
    logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return the package logger for a module.

    Args:
        name: Normally the caller's ``__name__``.

    """
    if name == _PACKAGE_LOGGER or name.startswith(f"{_PACKAGE_LOGGER}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_PACKAGE_LOGGER}.{name}")
