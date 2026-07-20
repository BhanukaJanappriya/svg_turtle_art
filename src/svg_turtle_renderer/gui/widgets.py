"""Custom widgets for the dashboard.

Tk's own checkbutton draws a small square that all but disappears on a dark
panel. :class:`ToggleSwitch` replaces it with a pill-and-knob switch: the track
turns the accent colour when on, grey when off, and the knob slides between the
two, so a setting's state reads at a glance and changing it feels deliberate.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from svg_turtle_renderer.gui import theme

_STEPS = 6  # frames in the knob's slide
_STEP_MS = 12


class ToggleSwitch(tk.Canvas):
    """An animated on/off switch bound to a ``BooleanVar``.

    Args:
        parent: The containing widget.
        variable: The boolean the switch reflects and sets.
        command: Called after the value changes.
        width: Switch width in pixels.
        height: Switch height in pixels.

    """

    def __init__(
        self,
        parent: tk.Widget,
        variable: tk.BooleanVar,
        command: Callable[[], None] | None = None,
        width: int = 46,
        height: int = 24,
    ) -> None:
        """Draw the switch in its current state and wire up the click."""
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=theme.SURFACE,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self._var = variable
        self._command = command
        self._width = width
        self._height = height
        self._pad = 3
        self._radius = height / 2.0
        self._hover = False

        self._on = bool(variable.get())
        self._knob = self._target_x(self._on)
        self._after_id: str | None = None
        self.bind("<Button-1>", lambda _e: self.toggle())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        # Keep in step if the value is changed elsewhere in the app.
        self._trace = variable.trace_add("write", self._on_var_changed)
        self._render()

    def _target_x(self, on: bool) -> float:
        """Return the knob's centre x for the given state."""
        if on:
            return self._width - self._radius
        return self._radius

    def toggle(self) -> None:
        """Flip the value, animate to it, and fire the callback."""
        self._var.set(not self._var.get())
        # The variable trace drives the animation, so only the callback is left.
        if self._command is not None:
            self._command()

    def _on_var_changed(self, *_args: object) -> None:
        """Animate to match the variable when it changes."""
        target = bool(self._var.get())
        if target != self._on:
            self._on = target
            self._animate_to(self._target_x(target))

    def _animate_to(self, target: float, step: int = 0) -> None:
        """Slide the knob to ``target`` over a few frames."""
        if not self.winfo_exists():  # the window closed mid-slide
            return
        self._after_id = None
        if step >= _STEPS:
            self._knob = target
            self._render()
            return
        self._knob += (target - self._knob) / (_STEPS - step)
        self._render()
        self._after_id = self.after(_STEP_MS, lambda: self._animate_to(target, step + 1))

    def _on_enter(self, _event: object) -> None:
        """Brighten on hover."""
        self._hover = True
        self._render()

    def _on_leave(self, _event: object) -> None:
        """Return to rest when the pointer leaves."""
        self._hover = False
        self._render()

    def _render(self) -> None:
        """Repaint the track and knob for the current state."""
        self.delete("all")
        track = theme.ACCENT if self._on else theme.LINE
        if self._hover:
            track = theme.ACCENT_DIM if self._on else theme.MUTED
        # A capsule: a circle at each end joined by a rectangle.
        self.create_oval(0, 0, self._height, self._height, fill=track, outline="")
        self.create_oval(
            self._width - self._height, 0, self._width, self._height, fill=track, outline=""
        )
        self.create_rectangle(
            self._radius, 0, self._width - self._radius, self._height, fill=track, outline=""
        )

        knob_r = self._radius - self._pad
        self.create_oval(
            self._knob - knob_r,
            self._radius - knob_r,
            self._knob + knob_r,
            self._radius + knob_r,
            fill=theme.TEXT if self._on else theme.MUTED,
            outline="",
        )

    def destroy(self) -> None:
        """Drop the variable trace and any pending slide before going away."""
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
        try:
            self._var.trace_remove("write", self._trace)
        except Exception:
            pass
        super().destroy()
