"""Progress reporting.

The renderer measures its own work and reports it here, rather than having a
progress bar wrapped around the loop from outside. That is what lets the unit of
progress match what is actually happening: shapes when shapes are being painted
one after another, pixels of pencil travel when a single shape is being sketched
over half a minute.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from svg_turtle_renderer.utils.logger import get_logger

logger = get_logger(__name__)


@runtime_checkable
class Progress(Protocol):
    """Something that reports how much work has been done."""

    def advance(self, amount: float = 1.0) -> None:
        """Record that ``amount`` more units of work are finished."""
        ...

    def close(self) -> None:
        """Finish reporting and release any display."""
        ...


class NullProgress:
    """A reporter that does nothing.

    Lets callers advance progress unconditionally instead of branching on
    whether a bar exists.
    """

    def advance(self, amount: float = 1.0) -> None:
        """Ignore the work."""

    def close(self) -> None:
        """Do nothing."""


class TqdmProgress:
    """A progress bar backed by tqdm.

    Args:
        total: The total work expected, in whatever unit the caller counts in.
        description: The label shown beside the bar.
        unit: The name of one unit of work, for example ``"shape"`` or ``"px"``.
        unit_scale: Abbreviate large counts, so 20000 shows as ``20.0k``.

    """

    def __init__(
        self,
        total: float,
        description: str,
        unit: str,
        unit_scale: bool = False,
    ) -> None:
        """Create the bar, falling back to nothing if tqdm is unusable."""
        self._bar: Any = None
        try:
            from tqdm import tqdm

            self._bar = tqdm(
                total=total,
                desc=description,
                unit=unit,
                unit_scale=unit_scale,
                leave=False,
            )
        except Exception as exc:  # pragma: no cover - tqdm is a declared dependency
            # A missing or broken progress bar must never stop a drawing.
            logger.debug("Progress bar unavailable: %s", exc)

    def advance(self, amount: float = 1.0) -> None:
        """Advance the bar."""
        if self._bar is not None:
            self._bar.update(amount)

    def close(self) -> None:
        """Close the bar."""
        if self._bar is not None:
            self._bar.close()
            self._bar = None


def make_progress(
    enabled: bool,
    total: float,
    description: str,
    unit: str,
    unit_scale: bool = False,
) -> Progress:
    """Return a progress reporter, or a silent one when disabled.

    A total of zero also yields a silent reporter: a bar that can never move is
    worse than no bar, which is the whole reason this exists.
    """
    if not enabled or total <= 0:
        return NullProgress()
    return TqdmProgress(total, description, unit, unit_scale)
