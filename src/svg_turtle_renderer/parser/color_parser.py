"""Resolution of SVG paint values into RGB triples.

Turtle only understands opaque RGB, so every supported notation -- hex, ``rgb()``,
``rgba()``, ``hsl()``, ``hsla()`` and the CSS named colours -- collapses to a
:class:`Color`. Alpha survives parsing and is composited against the background
later by :mod:`svg_turtle_renderer.renderer.turtle_renderer`, since turtle has no
real transparency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from svg_turtle_renderer.core.exceptions import ColorError

# The CSS Color Module Level 3 extended colour keywords, which SVG adopts.
NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "aliceblue": (240, 248, 255),
    "antiquewhite": (250, 235, 215),
    "aqua": (0, 255, 255),
    "aquamarine": (127, 255, 212),
    "azure": (240, 255, 255),
    "beige": (245, 245, 220),
    "bisque": (255, 228, 196),
    "black": (0, 0, 0),
    "blanchedalmond": (255, 235, 205),
    "blue": (0, 0, 255),
    "blueviolet": (138, 43, 226),
    "brown": (165, 42, 42),
    "burlywood": (222, 184, 135),
    "cadetblue": (95, 158, 160),
    "chartreuse": (127, 255, 0),
    "chocolate": (210, 105, 30),
    "coral": (255, 127, 80),
    "cornflowerblue": (100, 149, 237),
    "cornsilk": (255, 248, 220),
    "crimson": (220, 20, 60),
    "cyan": (0, 255, 255),
    "darkblue": (0, 0, 139),
    "darkcyan": (0, 139, 139),
    "darkgoldenrod": (184, 134, 11),
    "darkgray": (169, 169, 169),
    "darkgreen": (0, 100, 0),
    "darkgrey": (169, 169, 169),
    "darkkhaki": (189, 183, 107),
    "darkmagenta": (139, 0, 139),
    "darkolivegreen": (85, 107, 47),
    "darkorange": (255, 140, 0),
    "darkorchid": (153, 50, 204),
    "darkred": (139, 0, 0),
    "darksalmon": (233, 150, 122),
    "darkseagreen": (143, 188, 143),
    "darkslateblue": (72, 61, 139),
    "darkslategray": (47, 79, 79),
    "darkslategrey": (47, 79, 79),
    "darkturquoise": (0, 206, 209),
    "darkviolet": (148, 0, 211),
    "deeppink": (255, 20, 147),
    "deepskyblue": (0, 191, 255),
    "dimgray": (105, 105, 105),
    "dimgrey": (105, 105, 105),
    "dodgerblue": (30, 144, 255),
    "firebrick": (178, 34, 34),
    "floralwhite": (255, 250, 240),
    "forestgreen": (34, 139, 34),
    "fuchsia": (255, 0, 255),
    "gainsboro": (220, 220, 220),
    "ghostwhite": (248, 248, 255),
    "gold": (255, 215, 0),
    "goldenrod": (218, 165, 32),
    "gray": (128, 128, 128),
    "green": (0, 128, 0),
    "greenyellow": (173, 255, 47),
    "grey": (128, 128, 128),
    "honeydew": (240, 255, 240),
    "hotpink": (255, 105, 180),
    "indianred": (205, 92, 92),
    "indigo": (75, 0, 130),
    "ivory": (255, 255, 240),
    "khaki": (240, 230, 140),
    "lavender": (230, 230, 250),
    "lavenderblush": (255, 240, 245),
    "lawngreen": (124, 252, 0),
    "lemonchiffon": (255, 250, 205),
    "lightblue": (173, 216, 230),
    "lightcoral": (240, 128, 128),
    "lightcyan": (224, 255, 255),
    "lightgoldenrodyellow": (250, 250, 210),
    "lightgray": (211, 211, 211),
    "lightgreen": (144, 238, 144),
    "lightgrey": (211, 211, 211),
    "lightpink": (255, 182, 193),
    "lightsalmon": (255, 160, 122),
    "lightseagreen": (32, 178, 170),
    "lightskyblue": (135, 206, 250),
    "lightslategray": (119, 136, 153),
    "lightslategrey": (119, 136, 153),
    "lightsteelblue": (176, 196, 222),
    "lightyellow": (255, 255, 224),
    "lime": (0, 255, 0),
    "limegreen": (50, 205, 50),
    "linen": (250, 240, 230),
    "magenta": (255, 0, 255),
    "maroon": (128, 0, 0),
    "mediumaquamarine": (102, 205, 170),
    "mediumblue": (0, 0, 205),
    "mediumorchid": (186, 85, 211),
    "mediumpurple": (147, 112, 219),
    "mediumseagreen": (60, 179, 113),
    "mediumslateblue": (123, 104, 238),
    "mediumspringgreen": (0, 250, 154),
    "mediumturquoise": (72, 209, 204),
    "mediumvioletred": (199, 21, 133),
    "midnightblue": (25, 25, 112),
    "mintcream": (245, 255, 250),
    "mistyrose": (255, 228, 225),
    "moccasin": (255, 228, 181),
    "navajowhite": (255, 222, 173),
    "navy": (0, 0, 128),
    "oldlace": (253, 245, 230),
    "olive": (128, 128, 0),
    "olivedrab": (107, 142, 35),
    "orange": (255, 165, 0),
    "orangered": (255, 69, 0),
    "orchid": (218, 112, 214),
    "palegoldenrod": (238, 232, 170),
    "palegreen": (152, 251, 152),
    "paleturquoise": (175, 238, 238),
    "palevioletred": (219, 112, 147),
    "papayawhip": (255, 239, 213),
    "peachpuff": (255, 218, 185),
    "peru": (205, 133, 63),
    "pink": (255, 192, 203),
    "plum": (221, 160, 221),
    "powderblue": (176, 224, 230),
    "purple": (128, 0, 128),
    "rebeccapurple": (102, 51, 153),
    "red": (255, 0, 0),
    "rosybrown": (188, 143, 143),
    "royalblue": (65, 105, 225),
    "saddlebrown": (139, 69, 19),
    "salmon": (250, 128, 114),
    "sandybrown": (244, 164, 96),
    "seagreen": (46, 139, 87),
    "seashell": (255, 245, 238),
    "sienna": (160, 82, 45),
    "silver": (192, 192, 192),
    "skyblue": (135, 206, 235),
    "slateblue": (106, 90, 205),
    "slategray": (112, 128, 144),
    "slategrey": (112, 128, 144),
    "snow": (255, 250, 250),
    "springgreen": (0, 255, 127),
    "steelblue": (70, 130, 180),
    "tan": (210, 180, 140),
    "teal": (0, 128, 128),
    "thistle": (216, 191, 216),
    "tomato": (255, 99, 71),
    "turquoise": (64, 224, 208),
    "violet": (238, 130, 238),
    "wheat": (245, 222, 179),
    "white": (255, 255, 255),
    "whitesmoke": (245, 245, 245),
    "yellow": (255, 255, 0),
    "yellowgreen": (154, 205, 50),
}

_FUNCTIONAL_RE = re.compile(r"^(rgba?|hsla?)\s*\((.*)\)$", re.IGNORECASE | re.DOTALL)
_SEPARATOR_RE = re.compile(r"[\s,/]+")


def _clamp(value: float, low: float, high: float) -> float:
    """Clamp ``value`` into the inclusive range ``[low, high]``."""
    return low if value < low else (high if value > high else value)


@dataclass(frozen=True, slots=True)
class Color:
    """An 8-bit RGB colour with an alpha channel."""

    r: int
    g: int
    b: int
    a: float = 1.0

    def as_turtle(self) -> tuple[float, float, float]:
        """Return the colour as the 0.0-1.0 float triple turtle expects."""
        return (self.r / 255.0, self.g / 255.0, self.b / 255.0)

    def as_hex(self) -> str:
        """Return the colour as a ``#rrggbb`` string."""
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}"

    def with_alpha(self, alpha: float) -> Color:
        """Return a copy of this colour with ``alpha`` multiplied in."""
        return Color(self.r, self.g, self.b, _clamp(self.a * alpha, 0.0, 1.0))

    def composite_over(self, background: Color) -> Color:
        """Return this colour flattened onto an opaque ``background``.

        Turtle has no alpha channel, so partial transparency is approximated by
        blending against whatever is behind the shape. The caller supplies the
        page background, which is right for isolated shapes and an approximation
        where artwork overlaps.
        """
        if self.a >= 1.0:
            return Color(self.r, self.g, self.b, 1.0)
        alpha = _clamp(self.a, 0.0, 1.0)
        return Color(
            round(self.r * alpha + background.r * (1.0 - alpha)),
            round(self.g * alpha + background.g * (1.0 - alpha)),
            round(self.b * alpha + background.b * (1.0 - alpha)),
            1.0,
        )


BLACK = Color(0, 0, 0)
WHITE = Color(255, 255, 255)


def _parse_channel(token: str) -> int:
    """Parse one rgb() channel, which may be ``0-255`` or a percentage."""
    token = token.strip()
    if token.endswith("%"):
        return round(_clamp(float(token[:-1]), 0.0, 100.0) * 255.0 / 100.0)
    return round(_clamp(float(token), 0.0, 255.0))


def _parse_alpha(token: str) -> float:
    """Parse an alpha component, which may be ``0-1`` or a percentage."""
    token = token.strip()
    if token.endswith("%"):
        return _clamp(float(token[:-1]) / 100.0, 0.0, 1.0)
    return _clamp(float(token), 0.0, 1.0)


def _parse_hue(token: str) -> float:
    """Parse a hue in degrees, accepting the CSS angle units."""
    token = token.strip().lower()
    for suffix, factor in (
        ("deg", 1.0),
        ("grad", 0.9),
        ("rad", 57.29577951308232),
        ("turn", 360.0),
    ):
        if token.endswith(suffix):
            return float(token[: -len(suffix)]) * factor
    return float(token)


def hsl_to_rgb(h: float, s: float, light: float) -> tuple[int, int, int]:
    """Convert HSL to 8-bit RGB using the CSS Color 3 reference algorithm.

    Args:
        h: Hue in degrees; values outside 0-360 wrap.
        s: Saturation, 0.0-1.0.
        light: Lightness, 0.0-1.0.

    """
    h = (h % 360.0) / 360.0
    s = _clamp(s, 0.0, 1.0)
    light = _clamp(light, 0.0, 1.0)
    if s == 0.0:
        value = round(light * 255.0)
        return (value, value, value)

    m2 = light * (1.0 + s) if light <= 0.5 else light + s - light * s
    m1 = 2.0 * light - m2

    def hue_to_rgb(hue: float) -> float:
        hue = hue % 1.0
        if hue < 1.0 / 6.0:
            return m1 + (m2 - m1) * 6.0 * hue
        if hue < 0.5:
            return m2
        if hue < 2.0 / 3.0:
            return m1 + (m2 - m1) * (2.0 / 3.0 - hue) * 6.0
        return m1

    return (
        round(hue_to_rgb(h + 1.0 / 3.0) * 255.0),
        round(hue_to_rgb(h) * 255.0),
        round(hue_to_rgb(h - 1.0 / 3.0) * 255.0),
    )


def _parse_hex(value: str) -> Color:
    """Parse ``#rgb``, ``#rgba``, ``#rrggbb`` or ``#rrggbbaa``."""
    digits = value[1:]
    try:
        if len(digits) in (3, 4):
            channels = [int(c * 2, 16) for c in digits]
        elif len(digits) in (6, 8):
            channels = [int(digits[i : i + 2], 16) for i in range(0, len(digits), 2)]
        else:
            raise ColorError(f"Hex colour {value!r} must have 3, 4, 6 or 8 digits")
    except ValueError as exc:
        raise ColorError(f"Hex colour {value!r} contains non-hex digits") from exc

    alpha = channels[3] / 255.0 if len(channels) == 4 else 1.0
    return Color(channels[0], channels[1], channels[2], alpha)


def _parse_functional(name: str, body: str) -> Color:
    """Parse an ``rgb()``, ``rgba()``, ``hsl()`` or ``hsla()`` body."""
    tokens = [t for t in _SEPARATOR_RE.split(body.strip()) if t]
    if len(tokens) not in (3, 4):
        raise ColorError(f"{name}() expects 3 or 4 components, got {len(tokens)}")

    alpha = _parse_alpha(tokens[3]) if len(tokens) == 4 else 1.0
    if name.startswith("rgb"):
        r, g, b = (_parse_channel(t) for t in tokens[:3])
    else:
        hue = _parse_hue(tokens[0])
        saturation = _parse_alpha(tokens[1]) if tokens[1].endswith("%") else float(tokens[1])
        lightness = _parse_alpha(tokens[2]) if tokens[2].endswith("%") else float(tokens[2])
        r, g, b = hsl_to_rgb(hue, saturation, lightness)
    return Color(r, g, b, alpha)


def parse_color(
    value: str | None,
    *,
    current_color: Color = BLACK,
    strict: bool = False,
) -> Color | None:
    """Resolve an SVG paint value to a :class:`Color`.

    Args:
        value: The raw attribute text, such as ``"#f80"``, ``"rgb(255,0,0)"``,
            ``"hsl(210 50% 40%)"``, ``"tomato"``, ``"none"`` or ``"currentColor"``.
        current_color: The value ``currentColor`` resolves to, inherited from an
            ancestor's ``color`` property.
        strict: When true an unrecognised value raises; otherwise it resolves to
            ``None`` so one bad attribute cannot abort a whole drawing.

    Returns:
        The colour, or ``None`` when the value is ``none`` or unparseable in
        non-strict mode. ``None`` means "do not paint".

    Raises:
        ColorError: If the value cannot be parsed and ``strict`` is true.

    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None

    lowered = text.lower()
    if lowered in ("none", "transparent"):
        return None
    if lowered == "currentcolor":
        return current_color
    if lowered in NAMED_COLORS:
        r, g, b = NAMED_COLORS[lowered]
        return Color(r, g, b)

    try:
        if text.startswith("#"):
            return _parse_hex(text)
        match = _FUNCTIONAL_RE.match(text)
        if match:
            return _parse_functional(match.group(1).lower(), match.group(2))
        # Gradients and patterns arrive as url(#id). They are not supported, and
        # painting them a wrong flat colour would be worse than not painting.
        if lowered.startswith("url("):
            raise ColorError(f"Paint servers are not supported: {text!r}")
        raise ColorError(f"Unrecognised colour: {text!r}")
    except (ColorError, ValueError) as exc:
        if strict:
            raise exc if isinstance(exc, ColorError) else ColorError(str(exc)) from exc
        return None


def parse_opacity(value: str | None, default: float = 1.0) -> float:
    """Parse an opacity attribute, clamped to ``0.0-1.0``.

    Unparseable input falls back to ``default``, matching the SVG error-handling
    rule that a bad presentation attribute is ignored rather than fatal.
    """
    if value is None:
        return default
    text = value.strip()
    if not text:
        return default
    try:
        if text.endswith("%"):
            return _clamp(float(text[:-1]) / 100.0, 0.0, 1.0)
        return _clamp(float(text), 0.0, 1.0)
    except ValueError:
        return default
