"""Reduction of an SVG document to a flat list of drawable shapes.

The parser walks the element tree once, carrying inherited style and an
accumulated transform down the recursion. Geometry is baked into absolute user
coordinates as it goes, so nothing downstream needs the tree, and by the time
:class:`~svg_turtle_renderer.core.model.Drawing` is returned the XML is gone.

Unsupported constructs (text, gradients, filters) are reported through the logger
and skipped. The alternative -- guessing -- produces artwork that is wrong in
ways the user cannot see, which is worse than a visible omission.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path

from svg_turtle_renderer.core.exceptions import InvalidSVGError, PathSyntaxError
from svg_turtle_renderer.core.model import Drawing, Shape, Style, SubPath
from svg_turtle_renderer.geometry.bezier import flatten_arc, flatten_cubic
from svg_turtle_renderer.geometry.clipping import clip_polygon, clip_polyline
from svg_turtle_renderer.geometry.coordinate_system import BoundingBox, Matrix, Point
from svg_turtle_renderer.parser.color_parser import BLACK, Color, parse_color, parse_opacity
from svg_turtle_renderer.parser.path_parser import PathParser
from svg_turtle_renderer.parser.transform_parser import parse_transform
from svg_turtle_renderer.utils.helpers import (
    parse_length,
    parse_points,
    parse_style_attribute,
    strip_namespace,
)
from svg_turtle_renderer.utils.logger import get_logger

logger = get_logger(__name__)

SVG_NAMESPACE = "http://www.w3.org/2000/svg"
XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"

# The circular-arc magic number: the control-point offset, as a fraction of the
# radius, that makes a cubic Bezier approximate a quarter circle to within about
# one part in 10^4 -- far below any visible error once flattened.
_KAPPA = 0.5522847498307936

# Elements that hold children but are never painted where they are defined.
_NON_RENDERING_CONTAINERS = frozenset({"defs", "symbol", "clippath", "mask", "marker", "pattern"})
_CONTAINERS = frozenset({"g", "svg", "a"})

# Conditional-processing attributes. A <switch> renders the first child whose
# tests all pass; an empty value fails by definition, per the specification.
_CONDITIONAL_ATTRIBUTES = ("requiredFeatures", "requiredExtensions", "systemLanguage")
_SHAPE_TAGS = frozenset({"path", "rect", "circle", "ellipse", "line", "polygon", "polyline"})

# Reported once each rather than per element, so a text-heavy file does not bury
# the progress output in warnings.
_KNOWN_UNSUPPORTED = frozenset(
    {
        "text",
        "tspan",
        "textpath",
        "image",
        "foreignobject",
        "filter",
        "lineargradient",
        "radialgradient",
        "animate",
        "animatetransform",
        "animatemotion",
        "script",
        "style",
        "font",
        "marker",
    }
)


@dataclass(frozen=True, slots=True)
class _StyleState:
    """Inheritable style, carried down the element tree.

    ``fill`` and ``stroke`` use ``None`` for "do not paint". Absent attributes are
    not represented here at all -- the walker simply keeps the parent's value,
    which is what CSS inheritance means.
    """

    fill: Color | None = BLACK
    stroke: Color | None = None
    stroke_width: float = 1.0
    fill_opacity: float = 1.0
    stroke_opacity: float = 1.0
    group_opacity: float = 1.0
    current_color: Color = BLACK
    visible: bool = True
    # SVG's initial fill-rule is nonzero, not even-odd.
    even_odd: bool = False


class SVGParser:
    """Parses SVG documents into :class:`Drawing` objects.

    A tolerance in user units only means something relative to the document's own
    scale, and the parser is the first thing to see the viewBox. So the usual way
    to configure precision is ``resolution``, a scale-free quality factor, and to
    let the parser derive the tolerance once the viewport is known.

    Args:
        tolerance: An explicit flattening tolerance in user units. Leave as
            ``None`` to derive one from ``resolution`` and the viewBox.
        resolution: Quality multiplier used when ``tolerance`` is ``None``.
            Higher is smoother and produces more vertices.
        strict: When true, a malformed path or transform aborts the parse.
            Otherwise the offending element is skipped with a warning.

    """

    def __init__(
        self,
        tolerance: float | None = None,
        resolution: float = 1.0,
        strict: bool = False,
    ) -> None:
        """Configure flattening precision and error strictness."""
        self._explicit_tolerance = max(tolerance, 1e-6) if tolerance is not None else None
        self._resolution = max(resolution, 0.01)
        self._strict = strict
        # Replaced once the viewBox is known; only used if a caller reaches for
        # geometry helpers before parsing a document.
        self._tolerance = self._explicit_tolerance or 0.25
        self._path_parser = PathParser(self._tolerance, strict=self._strict)
        self._ids: dict[str, ElementTree.Element] = {}
        self._use_stack: list[str] = []
        self._warned: set[str] = set()

    @property
    def tolerance(self) -> float:
        """Return the flattening tolerance used by the most recent parse."""
        return self._tolerance

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    def parse_file(self, path: str | Path) -> Drawing:
        """Parse an SVG file from disk.

        Args:
            path: Path to the ``.svg`` file.

        Returns:
            The parsed drawing.

        Raises:
            InvalidSVGError: If the file is missing, unreadable, or not valid SVG.

        """
        file_path = Path(path)
        if not file_path.exists():
            raise InvalidSVGError(f"File not found: {file_path}")
        if not file_path.is_file():
            raise InvalidSVGError(f"Not a file: {file_path}")
        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Some tools still emit legacy encodings; the XML declaration would
            # name it, but latin-1 never fails and the tags are ASCII regardless.
            try:
                text = file_path.read_bytes().decode("latin-1")
            except OSError as exc:
                raise InvalidSVGError(f"Cannot read {file_path}: {exc}") from exc
        except OSError as exc:
            raise InvalidSVGError(f"Cannot read {file_path}: {exc}") from exc
        return self.parse_string(text, source=str(file_path))

    def parse_string(self, text: str, source: str = "<string>") -> Drawing:
        """Parse SVG markup held in memory.

        Args:
            text: The document markup.
            source: A label used in error messages.

        Returns:
            The parsed drawing.

        Raises:
            InvalidSVGError: If the markup is not well-formed XML or is not SVG.

        """
        if not text.strip():
            raise InvalidSVGError(f"{source} is empty")
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError as exc:
            raise InvalidSVGError(f"{source} is not well-formed XML: {exc}") from exc

        if strip_namespace(root.tag).lower() != "svg":
            raise InvalidSVGError(
                f"{source} has root element <{strip_namespace(root.tag)}>, expected <svg>"
            )

        self._ids = {element.get("id", ""): element for element in root.iter() if element.get("id")}
        self._use_stack = []
        self._warned = set()

        viewbox, width, height = self._parse_viewport(root)

        # Now that the document's scale is known, the flattening tolerance can be
        # made proportionate to it.
        self._tolerance = self._explicit_tolerance or estimate_tolerance(viewbox, self._resolution)
        self._path_parser = PathParser(self._tolerance, strict=self._strict)

        shapes: list[Shape] = []
        root_style = _StyleState()

        # The root <svg> carries style and may carry a transform of its own.
        root_style = self._resolve_style(root, root_style)
        root_transform = self._element_transform(root)
        for child in root:
            shapes.extend(self._walk(child, root_transform, root_style))

        logger.debug(
            "Parsed %s: %d shapes, %d vertices, tolerance %.4g",
            source,
            len(shapes),
            sum(s.vertex_count for s in shapes),
            self._tolerance,
        )
        return Drawing(shapes=shapes, viewbox=viewbox, width=width, height=height)

    # ------------------------------------------------------------------
    # Viewport
    # ------------------------------------------------------------------

    def _parse_viewport(self, root: ElementTree.Element) -> tuple[BoundingBox, float, float]:
        """Determine the viewBox and nominal pixel size of the document.

        A document may declare a viewBox, explicit width and height, both, or
        neither. Each is derived from the other where possible; when neither is
        present the SVG default viewport of 300x150 applies, and the caller can
        still choose to fit to content instead.
        """
        raw_viewbox = root.get("viewBox") or root.get("viewbox")
        viewbox: BoundingBox | None = None

        if raw_viewbox:
            numbers = (
                [float(token) for token in raw_viewbox.replace(",", " ").split() if token]
                if self._viewbox_is_numeric(raw_viewbox)
                else []
            )
            if len(numbers) == 4 and numbers[2] > 0 and numbers[3] > 0:
                viewbox = BoundingBox(
                    numbers[0], numbers[1], numbers[0] + numbers[2], numbers[1] + numbers[3]
                )
            else:
                logger.warning("Ignoring malformed viewBox: %r", raw_viewbox)

        width = parse_length(root.get("width"), default=0.0, percent_of=None)
        height = parse_length(root.get("height"), default=0.0, percent_of=None)

        if viewbox is None:
            if width > 0 and height > 0:
                viewbox = BoundingBox(0.0, 0.0, width, height)
            else:
                viewbox = BoundingBox(0.0, 0.0, 300.0, 150.0)
        if width <= 0.0:
            width = viewbox.width
        if height <= 0.0:
            height = viewbox.height
        return viewbox, width, height

    @staticmethod
    def _viewbox_is_numeric(raw: str) -> bool:
        """Report whether every token of a viewBox parses as a number."""
        try:
            for token in raw.replace(",", " ").split():
                float(token)
        except ValueError:
            return False
        return True

    # ------------------------------------------------------------------
    # Tree walking
    # ------------------------------------------------------------------

    def _walk(
        self,
        element: ElementTree.Element,
        transform: Matrix,
        inherited: _StyleState,
    ) -> Iterator[Shape]:
        """Yield the shapes produced by ``element`` and its descendants."""
        tag = strip_namespace(element.tag).lower()

        if tag in _NON_RENDERING_CONTAINERS:
            # Registered by id already; only <use> brings these into the picture.
            return
        if tag == "use":
            yield from self._expand_use(element, transform, inherited)
            return

        style = self._resolve_style(element, inherited)
        if not style.visible:
            return

        local_transform = transform @ self._element_transform(element)

        if tag == "switch":
            # Unlike a group, a switch renders at most one child.
            for child in element:
                if self._conditions_pass(child):
                    yield from self._walk(child, local_transform, style)
                    return
            return

        if tag in _CONTAINERS:
            for child in element:
                yield from self._walk(child, local_transform, style)
            return

        if tag in _SHAPE_TAGS:
            shape = self._build_shape(element, tag, local_transform, style)
            if shape is not None:
                yield shape
            return

        if tag in _KNOWN_UNSUPPORTED:
            self._warn_once(tag, f"<{tag}> elements are not supported and will be skipped")
        elif tag not in ("title", "desc", "metadata"):
            self._warn_once(tag, f"Unknown element <{tag}> skipped")

    def _expand_use(
        self,
        element: ElementTree.Element,
        transform: Matrix,
        inherited: _StyleState,
    ) -> Iterator[Shape]:
        """Yield the shapes of a ``<use>`` instance.

        The referenced element is walked again with the instance's transform and
        style, which is what gives each instance its own paint. A reference that
        forms a cycle is refused, since expanding it would never terminate.
        """
        href = element.get("href") or element.get(f"{{{XLINK_NAMESPACE}}}href")
        if not href or not href.startswith("#"):
            self._warn_once(
                "use-external", f"<use> reference {href!r} is not a local id and was skipped"
            )
            return

        target_id = href[1:]
        target = self._ids.get(target_id)
        if target is None:
            logger.warning("<use> references unknown id %r", target_id)
            return
        if target_id in self._use_stack:
            logger.warning("Refusing to expand circular <use> reference to %r", target_id)
            return

        style = self._resolve_style(element, inherited)
        if not style.visible:
            return

        # x/y on <use> are defined as an extra translation applied after the
        # element's own transform.
        offset = Matrix.translate(
            parse_length(element.get("x"), 0.0), parse_length(element.get("y"), 0.0)
        )
        local_transform = transform @ self._element_transform(element) @ offset

        self._use_stack.append(target_id)
        try:
            target_tag = strip_namespace(target.tag).lower()
            if target_tag in ("symbol", "svg"):
                # A referenced <symbol> renders as if it were a <g>.
                target_style = self._resolve_style(target, style)
                inner = local_transform @ self._element_transform(target)
                for child in target:
                    yield from self._walk(child, inner, target_style)
            else:
                yield from self._walk(target, local_transform, style)
        finally:
            self._use_stack.pop()

    def _conditions_pass(self, element: ElementTree.Element) -> bool:
        """Report whether a ``<switch>`` child's conditional attributes pass.

        A child with none of these attributes always passes, which is how the
        usual fallback-last-child idiom works. An *empty* value is defined to
        fail. Feature strings and extensions are not evaluated: this renderer
        supports no extensions, so anything that demands one cannot be honoured,
        while ``systemLanguage`` is accepted so that localised artwork picks its
        first offered language rather than falling through to nothing.
        """
        for name in _CONDITIONAL_ATTRIBUTES:
            value = element.get(name)
            if value is None:
                continue
            if not value.strip():
                return False
            if name == "requiredExtensions":
                return False
            if name == "requiredFeatures":
                self._warn_once(
                    "switch-features",
                    "<switch> requiredFeatures is not evaluated; the first candidate child is used",
                )
        return True

    def _element_transform(self, element: ElementTree.Element) -> Matrix:
        """Return the element's own ``transform``, or the identity."""
        raw = element.get("transform")
        if not raw:
            return Matrix.identity()
        return parse_transform(raw, strict=self._strict)

    def _warn_once(self, key: str, message: str) -> None:
        """Log ``message`` the first time ``key`` is seen."""
        if key not in self._warned:
            self._warned.add(key)
            logger.warning(message)

    # ------------------------------------------------------------------
    # Style
    # ------------------------------------------------------------------

    def _properties(self, element: ElementTree.Element) -> dict[str, str]:
        """Collect an element's style properties.

        Presentation attributes are gathered first and then overridden by the
        inline ``style`` attribute, which is the cascade order the specification
        requires.
        """
        properties = {
            name.lower(): value
            for name, value in element.attrib.items()
            if not name.startswith("{")
        }
        properties.update(parse_style_attribute(element.get("style")))
        return properties

    def _resolve_style(self, element: ElementTree.Element, inherited: _StyleState) -> _StyleState:
        """Resolve an element's style against its inherited style."""
        properties = self._properties(element)

        if properties.get("display", "").strip().lower() == "none":
            return replace(inherited, visible=False)
        if properties.get("visibility", "").strip().lower() in ("hidden", "collapse"):
            return replace(inherited, visible=False)

        current_color = inherited.current_color
        if "color" in properties:
            resolved = parse_color(properties["color"], current_color=current_color)
            if resolved is not None:
                current_color = resolved

        fill = inherited.fill
        if "fill" in properties:
            fill = parse_color(properties["fill"], current_color=current_color)

        stroke = inherited.stroke
        if "stroke" in properties:
            stroke = parse_color(properties["stroke"], current_color=current_color)

        stroke_width = inherited.stroke_width
        if "stroke-width" in properties:
            stroke_width = max(0.0, parse_length(properties["stroke-width"], stroke_width))

        even_odd = inherited.even_odd
        if "fill-rule" in properties:
            rule = properties["fill-rule"].strip().lower()
            if rule in ("evenodd", "nonzero"):
                even_odd = rule == "evenodd"

        return _StyleState(
            fill=fill,
            stroke=stroke,
            stroke_width=stroke_width,
            fill_opacity=parse_opacity(properties.get("fill-opacity"), inherited.fill_opacity),
            stroke_opacity=parse_opacity(
                properties.get("stroke-opacity"), inherited.stroke_opacity
            ),
            # Group opacity should composite the group as a unit; turtle cannot
            # do that, so it is folded into each descendant's alpha instead. The
            # difference only shows where members of a group overlap.
            group_opacity=inherited.group_opacity * parse_opacity(properties.get("opacity"), 1.0),
            current_color=current_color,
            visible=True,
            even_odd=even_odd,
        )

    def _bake_style(self, style: _StyleState, transform: Matrix) -> Style:
        """Collapse inheritable style into the flat :class:`Style` of a shape."""
        fill = style.fill
        if fill is not None:
            fill = fill.with_alpha(style.fill_opacity * style.group_opacity)
            if fill.a <= 0.0:
                fill = None

        stroke = style.stroke
        if stroke is not None:
            stroke = stroke.with_alpha(style.stroke_opacity * style.group_opacity)
            if stroke.a <= 0.0:
                stroke = None

        return Style(
            fill=fill,
            stroke=stroke,
            stroke_width=style.stroke_width * transform.mean_scale,
            even_odd=style.even_odd,
        )

    # ------------------------------------------------------------------
    # Shape construction
    # ------------------------------------------------------------------

    def _build_shape(
        self,
        element: ElementTree.Element,
        tag: str,
        transform: Matrix,
        style: _StyleState,
    ) -> Shape | None:
        """Build one shape from a geometry element, or ``None`` if it draws nothing."""
        try:
            subpaths = self._geometry(element, tag)
        except PathSyntaxError as exc:
            if self._strict:
                raise
            logger.warning("Skipping <%s id=%s>: %s", tag, element.get("id"), exc)
            return None

        if not subpaths:
            return None

        # A line can only ever be stroked, whatever the fill says.
        baked = self._bake_style(style, transform)
        if tag in ("line", "polyline") and baked.fill is not None:
            baked = replace(baked, fill=None)
        if baked.fill is None and baked.stroke is None:
            return None

        for subpath in subpaths:
            subpath.points = transform.apply_all(subpath.points)

        subpaths = self._apply_clip(element, subpaths, transform)
        subpaths = [sp for sp in subpaths if sp.is_drawable]
        if not subpaths:
            return None

        return Shape(
            subpaths=subpaths,
            style=baked,
            element_id=element.get("id"),
            source_tag=tag,
        )

    def _geometry(self, element: ElementTree.Element, tag: str) -> list[SubPath]:
        """Return an element's geometry as sub-paths in its own user space."""
        if tag == "path":
            return self._path_parser.parse(element.get("d") or "")
        if tag == "rect":
            return self._rect(element)
        if tag == "circle":
            radius = parse_length(element.get("r"), 0.0)
            return self._ellipse_subpath(
                parse_length(element.get("cx"), 0.0),
                parse_length(element.get("cy"), 0.0),
                radius,
                radius,
            )
        if tag == "ellipse":
            return self._ellipse_subpath(
                parse_length(element.get("cx"), 0.0),
                parse_length(element.get("cy"), 0.0),
                parse_length(element.get("rx"), 0.0),
                parse_length(element.get("ry"), 0.0),
            )
        if tag == "line":
            start = (parse_length(element.get("x1"), 0.0), parse_length(element.get("y1"), 0.0))
            end = (parse_length(element.get("x2"), 0.0), parse_length(element.get("y2"), 0.0))
            if start == end:
                return []
            return [SubPath(points=[start, end], closed=False)]
        if tag in ("polygon", "polyline"):
            points = parse_points(element.get("points"))
            if len(points) < 2:
                return []
            return [SubPath(points=points, closed=tag == "polygon")]
        return []

    def _rect(self, element: ElementTree.Element) -> list[SubPath]:
        """Build a rectangle, honouring the ``rx``/``ry`` rounded corners."""
        x = parse_length(element.get("x"), 0.0)
        y = parse_length(element.get("y"), 0.0)
        width = parse_length(element.get("width"), 0.0)
        height = parse_length(element.get("height"), 0.0)
        if width <= 0.0 or height <= 0.0:
            return []

        # Either radius may be given alone, in which case it supplies both, and
        # each is capped at half the corresponding side.
        raw_rx = element.get("rx")
        raw_ry = element.get("ry")
        rx = parse_length(raw_rx, 0.0) if raw_rx not in (None, "auto") else None
        ry = parse_length(raw_ry, 0.0) if raw_ry not in (None, "auto") else None
        if rx is None and ry is None:
            rx = ry = 0.0
        elif rx is None:
            rx = ry
        elif ry is None:
            ry = rx
        rx = min(max(rx or 0.0, 0.0), width / 2.0)
        ry = min(max(ry or 0.0, 0.0), height / 2.0)

        if rx <= 0.0 or ry <= 0.0:
            corners: list[Point] = [
                (x, y),
                (x + width, y),
                (x + width, y + height),
                (x, y + height),
            ]
            return [SubPath(points=corners, closed=True)]

        right, bottom = x + width, y + height
        points: list[Point] = [(x + rx, y)]
        for start, end, sweep_start in (
            ((right - rx, y), (right, y + ry), True),
            ((right, bottom - ry), (right - rx, bottom), True),
            ((x + rx, bottom), (x, bottom - ry), True),
            ((x, y + ry), (x + rx, y), True),
        ):
            points.append(start)
            points.extend(flatten_arc(start, rx, ry, 0.0, False, sweep_start, end, self._tolerance))
        return [SubPath(points=points, closed=True)]

    def _ellipse_subpath(self, cx: float, cy: float, rx: float, ry: float) -> list[SubPath]:
        """Build an ellipse from four cubic Beziers, then flatten it."""
        if rx <= 0.0 or ry <= 0.0:
            return []
        ox, oy = rx * _KAPPA, ry * _KAPPA
        right, left = cx + rx, cx - rx
        bottom, top = cy + ry, cy - ry

        points: list[Point] = [(right, cy)]
        for p0, c1, c2, p3 in (
            ((right, cy), (right, cy + oy), (cx + ox, bottom), (cx, bottom)),
            ((cx, bottom), (cx - ox, bottom), (left, cy + oy), (left, cy)),
            ((left, cy), (left, cy - oy), (cx - ox, top), (cx, top)),
            ((cx, top), (cx + ox, top), (right, cy - oy), (right, cy)),
        ):
            points.extend(flatten_cubic(p0, c1, c2, p3, self._tolerance))
        return [SubPath(points=points, closed=True)]

    # ------------------------------------------------------------------
    # Clipping
    # ------------------------------------------------------------------

    def _apply_clip(
        self,
        element: ElementTree.Element,
        subpaths: list[SubPath],
        transform: Matrix,
    ) -> list[SubPath]:
        """Clip a shape to its ``clip-path``, if it has one.

        Only the clip path's bounding rectangle is honoured; see
        :mod:`svg_turtle_renderer.geometry.clipping` for why.
        """
        reference = self._properties(element).get("clip-path")
        if not reference:
            return subpaths

        box = self._clip_bounds(reference, transform)
        if box is None:
            return subpaths

        clipped: list[SubPath] = []
        for subpath in subpaths:
            if subpath.closed:
                points = clip_polygon(subpath.points, box)
                if len(points) >= 3:
                    clipped.append(SubPath(points=points, closed=True))
            else:
                for run in clip_polyline(subpath.points, box):
                    clipped.append(SubPath(points=run, closed=False))
        return clipped

    def _clip_bounds(self, reference: str, transform: Matrix) -> BoundingBox | None:
        """Return the bounds of a referenced ``<clipPath>``, in the same space.

        The clip path's children are walked with the *shape's* transform so that
        the resulting box is directly comparable to the already-transformed
        geometry.
        """
        text = reference.strip()
        if not text.startswith("url(") or "#" not in text:
            return None
        clip_id = text[text.index("#") + 1 :].rstrip(")").strip("'\" ")

        clip_element = self._ids.get(clip_id)
        if clip_element is None or strip_namespace(clip_element.tag).lower() != "clippath":
            logger.warning("clip-path references unknown clipPath %r", clip_id)
            return None
        if clip_element.get("clipPathUnits") == "objectBoundingBox":
            self._warn_once(
                "clip-units",
                "clipPathUnits='objectBoundingBox' is not supported; clip ignored",
            )
            return None

        box: BoundingBox | None = None
        clip_transform = transform @ self._element_transform(clip_element)
        for child in clip_element:
            tag = strip_namespace(child.tag).lower()
            if tag not in _SHAPE_TAGS:
                continue
            try:
                subpaths = self._geometry(child, tag)
            except PathSyntaxError:
                continue
            child_transform = clip_transform @ self._element_transform(child)
            for subpath in subpaths:
                child_box = BoundingBox.from_points(child_transform.apply_all(subpath.points))
                if child_box is not None:
                    box = child_box if box is None else box.union(child_box)

        if box is not None:
            self._warn_once(
                "clip-approx",
                "clip-path support is approximate: shapes are clipped to the "
                "clip path's bounding box, not its exact outline",
            )
        return box


def parse_svg(
    path: str | Path,
    tolerance: float | None = None,
    resolution: float = 1.0,
    strict: bool = False,
) -> Drawing:
    """Parse an SVG file with a throwaway parser."""
    return SVGParser(tolerance=tolerance, resolution=resolution, strict=strict).parse_file(path)


#: Divisor behind the default flattening tolerance. See :func:`estimate_tolerance`
#: for why this number is in effect "canvas pixels of error at resolution 1.0".
_TOLERANCE_DIVISOR = 5000.0


def estimate_tolerance(viewbox: BoundingBox, resolution: float) -> float:
    """Derive a flattening tolerance from a viewBox and a quality factor.

    A tolerance in user units means nothing on its own: 0.25 units is invisible
    in a 1000-unit viewBox and catastrophic in a 2-unit one. Tying it to the
    viewBox diagonal makes ``resolution`` behave identically for any document.

    The divisor is chosen with the *canvas* in mind. Auto-fitting scales the
    viewBox to fill the canvas, so the on-screen error works out as::

        error_px = (diagonal / N) * (canvas_diagonal / diagonal)
                 = canvas_diagonal / N

    The document's own units cancel out entirely, which means N can be picked
    once to give a sub-pixel result on any artwork: at N = 5000, a 1280-pixel
    canvas diagonal carries about a quarter-pixel of error. Curves therefore look
    smooth rather than faceted, at roughly twice the vertices of a whole-pixel
    tolerance -- a trade worth making, since vertices are cheap and visible
    corners on a circle are not.

    Args:
        viewbox: The document's viewBox.
        resolution: Quality multiplier; higher means smoother and slower.

    Returns:
        A tolerance in user units.

    """
    diagonal = math.hypot(viewbox.width, viewbox.height)
    if diagonal <= 0.0:
        return 0.25
    return max(diagonal / (_TOLERANCE_DIVISOR * max(resolution, 0.01)), 1e-6)
