"""The dashboard's visual language.

One palette and a small type scale, kept here so every widget in the dashboard
is styled from the same source. The theme is a single deliberate dark "studio"
look: a warm-graphite surround that ties to the pencil-and-brush metaphor and
makes the paper-white canvas the brightest thing on screen.
"""

from __future__ import annotations

from tkinter import font as tkfont

# --- Colour -----------------------------------------------------------------
INK = "#17181c"  # app ground
SURFACE = "#1f2127"  # raised control panel
SURFACE_2 = "#282b33"  # inputs and cards
LINE = "#34373f"  # hairline borders
TEXT = "#e8e6e1"  # primary text, warm off-white like paper
MUTED = "#9a9ca6"  # secondary text and labels
FAINT = "#6d6f78"  # disabled text
ACCENT = "#e0a458"  # graphite-amber: the pencil, used for the primary action
ACCENT_DIM = "#b98544"  # accent, pressed
DANGER = "#d9564b"  # stop
DANGER_DIM = "#b8463d"
GOOD = "#5fa97e"  # a finished, successful render
PAPER = "#ffffff"  # the canvas the artwork is drawn on


def pick_family(*candidates: str) -> str:
    """Return the first installed font family, or Tk's default."""
    available = set(tkfont.families())
    for name in candidates:
        if name in available:
            return name
    return "TkDefaultFont"


class Fonts:
    """The type scale, resolved against whatever faces the system has.

    Built lazily on first use, because Tk fonts cannot be created before a root
    window exists.
    """

    def __init__(self) -> None:
        """Resolve the display, body and data families and their sizes."""
        sans = pick_family("Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans")
        mono = pick_family("Consolas", "SF Mono", "DejaVu Sans Mono", "Courier New")
        self.title = tkfont.Font(family=sans, size=15, weight="bold")
        self.heading = tkfont.Font(family=sans, size=10, weight="bold")
        self.eyebrow = tkfont.Font(family=sans, size=8, weight="bold")
        self.body = tkfont.Font(family=sans, size=10)
        self.button = tkfont.Font(family=sans, size=10, weight="bold")
        self.data = tkfont.Font(family=mono, size=9)
