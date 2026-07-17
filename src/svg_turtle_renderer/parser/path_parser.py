"""Parsing of SVG path data into polylines.

The scanner is hand-written rather than regex-driven because path data is not
quite a token stream: in ``a1 1 0 011 1`` the two arc flags are single digits
with no separator, so ``011`` is *three* values, not one. Only a parser that
knows which argument it is reading can get that right, and files exported by
common optimisers rely on it.

Curves are flattened here, in user units, so ``tolerance`` is expressed in the
same space as the path data.
"""

from __future__ import annotations

import re

from svg_turtle_renderer.core.exceptions import PathSyntaxError
from svg_turtle_renderer.core.model import SubPath
from svg_turtle_renderer.geometry.bezier import flatten_arc, flatten_cubic, flatten_quadratic
from svg_turtle_renderer.geometry.coordinate_system import Point
from svg_turtle_renderer.utils.logger import get_logger

logger = get_logger(__name__)

_NUMBER_RE = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
_WHITESPACE = " \t\r\n\f\v,"
_COMMANDS = "MmLlHhVvCcSsQqTtAaZz"

# Commands whose trailing control point seeds the reflection used by S/T.
_CUBIC_COMMANDS = frozenset("CcSs")
_QUADRATIC_COMMANDS = frozenset("QqTt")

# A set, not the string "Zz": `x in "Zz"` is a substring test, and the empty
# string is a substring of everything, so the initial "no previous command"
# state would masquerade as a closepath.
_CLOSE_COMMANDS = frozenset("Zz")


class _Scanner:
    """A cursor over path data that reads numbers, flags and command letters."""

    def __init__(self, text: str) -> None:
        """Wrap ``text`` for scanning from the start."""
        self._text = text
        self._pos = 0

    def skip_separators(self) -> None:
        """Advance past whitespace and commas."""
        text, length = self._text, len(self._text)
        while self._pos < length and text[self._pos] in _WHITESPACE:
            self._pos += 1

    @property
    def at_end(self) -> bool:
        """Report whether all meaningful input has been consumed."""
        self.skip_separators()
        return self._pos >= len(self._text)

    def try_read_command(self) -> str | None:
        """Consume and return the next command letter, if one is next."""
        self.skip_separators()
        if self._pos < len(self._text) and self._text[self._pos] in _COMMANDS:
            char = self._text[self._pos]
            self._pos += 1
            return char
        return None

    def read_number(self) -> float:
        """Consume and return the next number.

        Raises:
            PathSyntaxError: If the next token is not a number.

        """
        self.skip_separators()
        match = _NUMBER_RE.match(self._text, self._pos)
        if match is None:
            raise PathSyntaxError(
                f"Expected a number at offset {self._pos} in path data: "
                f"{self._text[self._pos : self._pos + 20]!r}"
            )
        self._pos = match.end()
        return float(match.group())

    def read_flag(self) -> bool:
        """Consume and return an arc flag, which is a bare ``0`` or ``1``.

        Raises:
            PathSyntaxError: If the next character is not ``0`` or ``1``.

        """
        self.skip_separators()
        if self._pos < len(self._text) and self._text[self._pos] in "01":
            flag = self._text[self._pos] == "1"
            self._pos += 1
            return flag
        raise PathSyntaxError(
            f"Expected an arc flag (0 or 1) at offset {self._pos} in path data: "
            f"{self._text[self._pos : self._pos + 20]!r}"
        )

    def peek_is_number(self) -> bool:
        """Report whether a number follows, which signals an implicit repeat."""
        self.skip_separators()
        return _NUMBER_RE.match(self._text, self._pos) is not None


class PathParser:
    """Converts an SVG ``d`` attribute into flattened sub-paths.

    Args:
        tolerance: Curve flattening tolerance, in SVG user units.
        strict: When true a syntax error raises. Otherwise the path is truncated
            at the error, which is what the specification requires.

    """

    def __init__(self, tolerance: float = 0.25, strict: bool = False) -> None:
        """Store the flattening tolerance and the error policy."""
        self._tolerance = max(tolerance, 1e-6)
        self._strict = strict

    def parse(self, data: str) -> list[SubPath]:
        """Parse path data into sub-paths of absolute points in user units.

        On malformed data the specification is explicit: "The SVG user agent
        shall render a 'path' element up to (but not including) the path command
        containing the first error in the path data specification." So a bad
        command truncates the path and logs a warning rather than discarding
        artwork that was perfectly well specified up to that point. Passing
        ``strict`` opts into an exception instead.

        Args:
            data: The contents of a ``d`` attribute.

        Returns:
            The sub-paths, in order. Sub-paths with fewer than two points are
            dropped, since they cannot be drawn or filled.

        Raises:
            PathSyntaxError: If the data is malformed and ``strict`` is true.

        """
        if not data or not data.strip():
            return []

        scanner = _Scanner(data)
        subpaths: list[SubPath] = []
        current: SubPath | None = None

        # Path state, per the SVG grammar.
        cursor: Point = (0.0, 0.0)
        start: Point = (0.0, 0.0)
        previous_control: Point | None = None
        previous_command = ""
        command: str | None = None

        try:
            while not scanner.at_end:
                letter = scanner.try_read_command()
                if letter is not None:
                    command = letter
                elif command is None:
                    raise PathSyntaxError(
                        "Expected 'Z' to be followed by a command letter"
                        if previous_command in _CLOSE_COMMANDS
                        else "Path data must begin with a moveto command"
                    )
                else:
                    # No letter, but arguments remain: the previous command
                    # repeats. A repeated moveto implicitly becomes a lineto.
                    command = {"M": "L", "m": "l"}.get(command, command)

                if command in _CLOSE_COMMANDS:
                    if current is not None:
                        current.closed = True
                        if current.is_drawable:
                            subpaths.append(current)
                        cursor = start
                        current = None
                    previous_control = None
                    previous_command = command
                    # A closepath takes no arguments, so it cannot repeat: a
                    # number after 'Z' is an error, not another closepath.
                    command = None
                    continue

                if command in "Mm":
                    x, y = self._read_point(scanner, cursor, command == "m")
                    if current is not None and current.is_drawable:
                        subpaths.append(current)
                    current = SubPath(points=[(x, y)])
                    cursor = start = (x, y)
                    previous_control = None
                    previous_command = command
                    continue

                if current is None:
                    if previous_command not in _CLOSE_COMMANDS:
                        raise PathSyntaxError(
                            f"Command {command!r} appears before any moveto in path data"
                        )
                    # "If a closepath is followed immediately by any other
                    # command, then the next subpath starts at the same initial
                    # point as the current subpath."
                    current = SubPath(points=[start])
                    cursor = start

                cursor, previous_control = self._consume_segment(
                    scanner, command, cursor, previous_control, previous_command, current
                )
                previous_command = command
        except PathSyntaxError as exc:
            if self._strict:
                raise
            logger.warning("Truncating path at a syntax error: %s", exc)

        if current is not None and current.is_drawable:
            subpaths.append(current)
        return subpaths

    def _read_point(self, scanner: _Scanner, cursor: Point, relative: bool) -> Point:
        """Read an ``x y`` pair, resolving it against ``cursor`` if relative."""
        x = scanner.read_number()
        y = scanner.read_number()
        return (cursor[0] + x, cursor[1] + y) if relative else (x, y)

    def _reflected_control(
        self,
        cursor: Point,
        previous_control: Point | None,
        previous_command: str,
        expected: frozenset[str],
    ) -> Point:
        """Return the control point implied by a smooth (``S``/``T``) command.

        The reflection is only valid when the previous command was of the same
        degree; otherwise the specification says to use the current point, which
        makes the segment start out straight.
        """
        if previous_control is None or previous_command not in expected:
            return cursor
        return (2.0 * cursor[0] - previous_control[0], 2.0 * cursor[1] - previous_control[1])

    def _consume_segment(
        self,
        scanner: _Scanner,
        command: str,
        cursor: Point,
        previous_control: Point | None,
        previous_command: str,
        current: SubPath,
    ) -> tuple[Point, Point | None]:
        """Read one segment, append its points, and return the new path state.

        Returns:
            The new cursor position and the control point a following smooth
            command should reflect (``None`` when reflection does not apply).

        """
        relative = command.islower()
        upper = command.upper()

        if upper == "L":
            end = self._read_point(scanner, cursor, relative)
            current.points.append(end)
            return end, None

        if upper == "H":
            x = scanner.read_number()
            end = (cursor[0] + x, cursor[1]) if relative else (x, cursor[1])
            current.points.append(end)
            return end, None

        if upper == "V":
            y = scanner.read_number()
            end = (cursor[0], cursor[1] + y) if relative else (cursor[0], y)
            current.points.append(end)
            return end, None

        if upper == "C":
            c1 = self._read_point(scanner, cursor, relative)
            c2 = self._read_point(scanner, cursor, relative)
            end = self._read_point(scanner, cursor, relative)
            current.points.extend(flatten_cubic(cursor, c1, c2, end, self._tolerance))
            return end, c2

        if upper == "S":
            c1 = self._reflected_control(
                cursor, previous_control, previous_command, _CUBIC_COMMANDS
            )
            c2 = self._read_point(scanner, cursor, relative)
            end = self._read_point(scanner, cursor, relative)
            current.points.extend(flatten_cubic(cursor, c1, c2, end, self._tolerance))
            return end, c2

        if upper == "Q":
            control = self._read_point(scanner, cursor, relative)
            end = self._read_point(scanner, cursor, relative)
            current.points.extend(flatten_quadratic(cursor, control, end, self._tolerance))
            return end, control

        if upper == "T":
            control = self._reflected_control(
                cursor, previous_control, previous_command, _QUADRATIC_COMMANDS
            )
            end = self._read_point(scanner, cursor, relative)
            current.points.extend(flatten_quadratic(cursor, control, end, self._tolerance))
            return end, control

        if upper == "A":
            rx = scanner.read_number()
            ry = scanner.read_number()
            rotation = scanner.read_number()
            large_arc = scanner.read_flag()
            sweep = scanner.read_flag()
            end = self._read_point(scanner, cursor, relative)
            current.points.extend(
                flatten_arc(cursor, rx, ry, rotation, large_arc, sweep, end, self._tolerance)
            )
            return end, None

        raise PathSyntaxError(f"Unsupported path command: {command!r}")


def parse_path(data: str, tolerance: float = 0.25, strict: bool = False) -> list[SubPath]:
    """Parse path data with a throwaway parser.

    A convenience wrapper for callers that do not need to reuse a configured
    :class:`PathParser`.
    """
    return PathParser(tolerance, strict).parse(data)
