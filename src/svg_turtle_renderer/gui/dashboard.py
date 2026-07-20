"""The dashboard window.

A tkinter control panel beside an embedded turtle canvas. The user queues SVG
files, chooses a pencil or a brush, sets the timing and appearance, and watches
the drawing appear in the panel. The window stays open until it is closed
deliberately; a finished render never dismisses it.

Everything runs on the main thread. A render is paced by
:class:`~svg_turtle_renderer.gui.tk_canvas.GuiClock`, which pumps the event loop
between frames, so the controls stay live and Stop takes effect at once without
threads and turtle's thread-unsafety.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk
from typing import Any

from svg_turtle_renderer.core.config import ColorMode, RenderConfig
from svg_turtle_renderer.core.exceptions import SVGTurtleError
from svg_turtle_renderer.gui import theme
from svg_turtle_renderer.gui.render_job import run_render
from svg_turtle_renderer.gui.tk_canvas import EmbeddedTurtleCanvas
from svg_turtle_renderer.parser.color_parser import WHITE, parse_color
from svg_turtle_renderer.utils.helpers import format_duration
from svg_turtle_renderer.utils.logger import get_logger

logger = get_logger(__name__)

_RAIL_WIDTH = 320
_CANVAS_MIN = (640, 560)


def _color_mode(value: str) -> ColorMode:
    """Narrow a combobox string to a colour mode, defaulting to original."""
    return value if value in ("original", "mono", "random") else "original"  # type: ignore[return-value]


class Dashboard:
    """The SVG Turtle Studio dashboard.

    Args:
        initial_files: SVG paths to preload into the queue.

    """

    def __init__(self, initial_files: list[str] | None = None) -> None:
        """Build the window, the controls and the embedded canvas."""
        self._root = tk.Tk()
        self._root.title("SVG Turtle Studio")
        self._root.configure(bg=theme.INK)
        self._root.minsize(_RAIL_WIDTH + _CANVAS_MIN[0], _CANVAS_MIN[1] + 96)
        self._fonts = theme.Fonts()

        self._files: list[str] = []
        self._rendering = False
        self._stop_requested = False
        self._canvas: EmbeddedTurtleCanvas | None = None

        self._build_state()
        self._build_style()
        self._build_header()
        self._build_body()
        self._build_statusbar()

        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        for path in initial_files or []:
            self._add_file(path)
        self._sync_tool_controls()
        self._set_running(False)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def _build_state(self) -> None:
        """Create the Tk variables backing every control."""
        self.tool = tk.StringVar(value="pencil")
        self.animate = tk.BooleanVar(value=True)
        self.duration = tk.DoubleVar(value=20.0)
        self.fps = tk.IntVar(value=30)
        self.pencil_width = tk.DoubleVar(value=1.0)
        self.brush_width = tk.DoubleVar(value=9.0)
        self.background = tk.StringVar(value="#ffffff")
        self.ink = tk.StringVar(value="")  # empty means each shape's own colour
        self.fill_flow = tk.BooleanVar(value=True)
        self.show_cursor = tk.BooleanVar(value=True)
        self.fit_content = tk.BooleanVar(value=False)
        self.paint_fill = tk.BooleanVar(value=True)
        self.paint_stroke = tk.BooleanVar(value=True)
        self.color_mode = tk.StringVar(value="original")
        self.clear_before = tk.BooleanVar(value=True)

    def _build_style(self) -> None:
        """Style the ttk widgets that the theme reaches: bar, combobox, scrollbar."""
        style = ttk.Style(self._root)
        style.theme_use("clam")
        style.configure(
            "Studio.Horizontal.TProgressbar",
            troughcolor=theme.SURFACE_2,
            background=theme.ACCENT,
            bordercolor=theme.SURFACE_2,
            lightcolor=theme.ACCENT,
            darkcolor=theme.ACCENT,
            thickness=8,
        )
        style.configure(
            "Studio.TCombobox",
            fieldbackground=theme.SURFACE_2,
            background=theme.SURFACE_2,
            foreground=theme.TEXT,
            arrowcolor=theme.MUTED,
            bordercolor=theme.LINE,
            selectbackground=theme.SURFACE_2,
            selectforeground=theme.TEXT,
        )
        style.map(
            "Studio.TCombobox",
            fieldbackground=[("readonly", theme.SURFACE_2)],
            foreground=[("readonly", theme.TEXT)],
        )
        style.configure(
            "Studio.Vertical.TScrollbar",
            background=theme.SURFACE_2,
            troughcolor=theme.SURFACE,
            bordercolor=theme.SURFACE,
            arrowcolor=theme.MUTED,
        )

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_header(self) -> None:
        """Build the title bar across the top."""
        header = tk.Frame(self._root, bg=theme.INK, height=66)
        header.pack(side="top", fill="x")
        header.pack_propagate(False)

        mark = tk.Canvas(header, width=30, height=30, bg=theme.INK, highlightthickness=0, bd=0)
        # A small pencil-nib emblem, so the window has an identity of its own.
        mark.create_polygon(6, 24, 10, 10, 20, 20, 6, 24, fill=theme.ACCENT, outline="")
        mark.create_line(6, 24, 13, 17, fill=theme.INK, width=1)
        mark.pack(side="left", padx=(18, 10), pady=13)

        titles = tk.Frame(header, bg=theme.INK)
        titles.pack(side="left", pady=10)
        tk.Label(
            titles, text="SVG Turtle Studio", bg=theme.INK, fg=theme.TEXT, font=self._fonts.title
        ).pack(anchor="w")
        tk.Label(
            titles,
            text="Watch your vector art drawn by hand",
            bg=theme.INK,
            fg=theme.MUTED,
            font=self._fonts.body,
        ).pack(anchor="w")

        tk.Frame(self._root, bg=theme.LINE, height=1).pack(side="top", fill="x")

    def _build_body(self) -> None:
        """Build the control rail and the canvas area side by side."""
        body = tk.Frame(self._root, bg=theme.INK)
        body.pack(side="top", fill="both", expand=True)

        rail = tk.Frame(body, bg=theme.SURFACE, width=_RAIL_WIDTH)
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        self._build_rail(rail)

        stage = tk.Frame(body, bg=theme.INK)
        stage.pack(side="left", fill="both", expand=True)
        pad = tk.Frame(stage, bg=theme.INK)
        pad.pack(fill="both", expand=True, padx=14, pady=14)
        self._canvas_widget = tk.Canvas(
            pad,
            bg=theme.PAPER,
            highlightthickness=1,
            highlightbackground=theme.LINE,
            bd=0,
        )
        self._canvas_widget.pack(fill="both", expand=True)

    def _build_rail(self, rail: tk.Frame) -> None:
        """Populate the rail: a scrolling body of controls over a pinned footer.

        The Draw and Stop actions live in the footer so they are always in reach,
        however small the window or however many controls the body holds; the
        sections above them scroll when they do not all fit.
        """
        footer = tk.Frame(rail, bg=theme.SURFACE)
        footer.pack(side="bottom", fill="x")
        tk.Frame(rail, bg=theme.LINE, height=1).pack(side="bottom", fill="x")
        self._build_actions(footer)

        scroller = tk.Canvas(rail, bg=theme.SURFACE, highlightthickness=0, bd=0)
        bar = ttk.Scrollbar(
            rail, orient="vertical", command=scroller.yview, style="Studio.Vertical.TScrollbar"
        )
        scroller.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        scroller.pack(side="left", fill="both", expand=True)

        body = tk.Frame(scroller, bg=theme.SURFACE)
        window = scroller.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _e: scroller.configure(scrollregion=scroller.bbox("all")))
        scroller.bind("<Configure>", lambda e: scroller.itemconfigure(window, width=e.width))

        def on_wheel(event: Any) -> None:
            scroller.yview_scroll(-1 if event.delta > 0 else 1, "units")

        for widget in (scroller, body):
            widget.bind("<MouseWheel>", on_wheel)

        self._build_files_section(body)
        self._build_tool_section(body)
        self._build_timing_section(body)
        self._build_appearance_section(body)
        tk.Frame(body, bg=theme.SURFACE, height=16).pack(side="top", fill="x")

    # ------------------------------------------------------------------
    # Rail sections
    # ------------------------------------------------------------------

    def _section(self, parent: tk.Frame, title: str) -> tk.Frame:
        """Return a padded section frame under an eyebrow label."""
        wrap = tk.Frame(parent, bg=theme.SURFACE)
        wrap.pack(side="top", fill="x", padx=18, pady=(16, 0))
        tk.Label(
            wrap,
            text=title.upper(),
            bg=theme.SURFACE,
            fg=theme.MUTED,
            font=self._fonts.eyebrow,
        ).pack(anchor="w", pady=(0, 8))
        return wrap

    def _build_files_section(self, rail: tk.Frame) -> None:
        """Build the SVG queue and its add, remove and clear controls."""
        section = self._section(rail, "Files")

        holder = tk.Frame(section, bg=theme.LINE, bd=0)
        holder.pack(fill="x")
        self._file_list = tk.Listbox(
            holder,
            height=4,
            bg=theme.SURFACE_2,
            fg=theme.TEXT,
            font=self._fonts.body,
            selectbackground=theme.ACCENT,
            selectforeground=theme.INK,
            highlightthickness=0,
            bd=0,
            activestyle="none",
        )
        self._file_list.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        self._file_list.bind("<Double-Button-1>", lambda _e: self._on_draw())
        scroll = ttk.Scrollbar(
            holder,
            orient="vertical",
            command=self._file_list.yview,
            style="Studio.Vertical.TScrollbar",
        )
        scroll.pack(side="right", fill="y")
        self._file_list.configure(yscrollcommand=scroll.set)

        row = tk.Frame(section, bg=theme.SURFACE)
        row.pack(fill="x", pady=(8, 0))
        self._ghost_button(row, "Add SVG", self._on_add).pack(side="left")
        self._ghost_button(row, "Remove", self._on_remove).pack(side="left", padx=6)
        self._ghost_button(row, "Clear", self._on_clear_files).pack(side="left")

    def _build_tool_section(self, rail: tk.Frame) -> None:
        """Build the pencil and brush toggle and the relevant width slider."""
        section = self._section(rail, "Tool")

        toggle = tk.Frame(section, bg=theme.SURFACE_2)
        toggle.pack(fill="x")
        self._tool_buttons: dict[str, tk.Label] = {}
        for value, label in (("pencil", "Pencil"), ("brush", "Brush")):
            btn = tk.Label(
                toggle,
                text=label,
                font=self._fonts.button,
                padx=10,
                pady=7,
                cursor="hand2",
            )
            btn.pack(side="left", fill="x", expand=True, padx=1, pady=1)
            btn.bind("<Button-1>", lambda _e, v=value: self._select_tool(v))  # type: ignore[misc]
            self._tool_buttons[value] = btn

        self._pencil_slider = self._slider(
            section, "Pencil width", self.pencil_width, 1, 6, 0.5, "px"
        )
        self._brush_slider = self._slider(section, "Brush width", self.brush_width, 3, 30, 1, "px")

    def _build_timing_section(self, rail: tk.Frame) -> None:
        """Animate toggle, duration and frame rate."""
        section = self._section(rail, "Timing")
        self._check(section, "Animate  (watch it draw)", self.animate, self._sync_tool_controls)
        self._duration_slider = self._slider(section, "Duration", self.duration, 2, 120, 1, "s")
        self._fps_slider = self._slider(section, "Frame rate", self.fps, 10, 60, 1, "fps")

    def _build_appearance_section(self, rail: tk.Frame) -> None:
        """Colours, fill options and the colour mode."""
        section = self._section(rail, "Appearance")

        swatches = tk.Frame(section, bg=theme.SURFACE)
        swatches.pack(fill="x")
        self._background_swatch = self._swatch(
            swatches, "Background", self.background, self._on_background
        )
        self._ink_swatch = self._swatch(swatches, "Ink", self.ink, self._on_ink, allow_auto=True)

        self._check(section, "Stream the fill in", self.fill_flow)
        self._check(section, "Show the drawing cursor", self.show_cursor)
        self._check(section, "Fit to the artwork", self.fit_content)
        self._check(section, "Paint fills", self.paint_fill)
        self._check(section, "Paint outlines", self.paint_stroke)

        mode = tk.Frame(section, bg=theme.SURFACE)
        mode.pack(fill="x", pady=(10, 0))
        tk.Label(mode, text="Colour", bg=theme.SURFACE, fg=theme.MUTED, font=self._fonts.body).pack(
            side="left"
        )
        box = ttk.Combobox(
            mode,
            textvariable=self.color_mode,
            values=("original", "mono", "random"),
            state="readonly",
            style="Studio.TCombobox",
            width=10,
            font=self._fonts.body,
        )
        box.pack(side="right")

    def _build_actions(self, footer: tk.Frame) -> None:
        """Build the pinned Draw and Stop actions and the canvas utilities."""
        actions = tk.Frame(footer, bg=theme.SURFACE)
        actions.pack(side="top", fill="x", padx=18, pady=14)

        self._check(actions, "Clear the canvas first", self.clear_before)

        pair = tk.Frame(actions, bg=theme.SURFACE)
        pair.pack(fill="x", pady=(10, 0))
        self._draw_button = self._primary_button(pair, "Draw", self._on_draw)
        self._draw_button.pack(side="left", fill="x", expand=True)
        self._stop_button = self._danger_button(pair, "Stop", self._on_stop)
        self._stop_button.pack(side="right", padx=(8, 0))

        utils = tk.Frame(actions, bg=theme.SURFACE)
        utils.pack(fill="x", pady=(8, 0))
        self._clear_canvas_button = self._ghost_button(utils, "Clear canvas", self._on_clear_canvas)
        self._clear_canvas_button.pack(side="left")
        self._export_button = self._ghost_button(utils, "Export PNG", self._on_export)
        self._export_button.pack(side="right")

    def _build_statusbar(self) -> None:
        """Build the progress bar and status line along the bottom."""
        tk.Frame(self._root, bg=theme.LINE, height=1).pack(side="bottom", fill="x")
        bar = tk.Frame(self._root, bg=theme.INK, height=40)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)

        self._status = tk.Label(
            bar,
            text="Add an SVG file to begin",
            bg=theme.INK,
            fg=theme.MUTED,
            font=self._fonts.body,
            anchor="w",
        )
        self._status.pack(side="left", padx=18)

        self._progress_value = tk.DoubleVar(value=0.0)
        self._progress = ttk.Progressbar(
            bar,
            style="Studio.Horizontal.TProgressbar",
            variable=self._progress_value,
            maximum=1.0,
            length=220,
        )
        self._progress.pack(side="right", padx=18)
        self._progress_text = tk.Label(
            bar, text="", bg=theme.INK, fg=theme.FAINT, font=self._fonts.data
        )
        self._progress_text.pack(side="right", padx=(0, 10))

    # ------------------------------------------------------------------
    # Styled widget factories
    # ------------------------------------------------------------------

    def _button(
        self, parent: tk.Widget, text: str, command: Any, bg: str, fg: str, active: str
    ) -> tk.Button:
        """Return a flat, coloured button."""
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active,
            activeforeground=fg,
            font=self._fonts.button,
            relief="flat",
            bd=0,
            padx=12,
            pady=9,
            cursor="hand2",
            highlightthickness=0,
        )

    def _primary_button(self, parent: tk.Widget, text: str, command: Any) -> tk.Button:
        """Return a filled accent button for the main action."""
        return self._button(parent, text, command, theme.ACCENT, theme.INK, theme.ACCENT_DIM)

    def _danger_button(self, parent: tk.Widget, text: str, command: Any) -> tk.Button:
        """Return a filled danger button for stopping."""
        return self._button(parent, text, command, theme.DANGER, "#ffffff", theme.DANGER_DIM)

    def _ghost_button(self, parent: tk.Widget, text: str, command: Any) -> tk.Button:
        """Return a quiet, low-emphasis button."""
        btn = self._button(parent, text, command, theme.SURFACE_2, theme.TEXT, theme.LINE)
        btn.configure(padx=10, pady=6, font=self._fonts.body)
        return btn

    def _slider(
        self,
        parent: tk.Frame,
        label: str,
        var: tk.IntVar | tk.DoubleVar,
        from_: float,
        to: float,
        resolution: float,
        unit: str,
    ) -> tk.Frame:
        """Return a labelled slider with a live value readout."""
        row = tk.Frame(parent, bg=theme.SURFACE)
        row.pack(fill="x", pady=(10, 0))
        head = tk.Frame(row, bg=theme.SURFACE)
        head.pack(fill="x")
        tk.Label(head, text=label, bg=theme.SURFACE, fg=theme.MUTED, font=self._fonts.body).pack(
            side="left"
        )
        value = tk.Label(head, text="", bg=theme.SURFACE, fg=theme.TEXT, font=self._fonts.data)
        value.pack(side="right")

        def on_move(_v: str) -> None:
            number = var.get()
            shown = f"{int(number)}" if float(number).is_integer() else f"{number:g}"
            value.configure(text=f"{shown} {unit}")

        scale = tk.Scale(
            row,
            variable=var,
            from_=from_,
            to=to,
            resolution=resolution,
            orient="horizontal",
            showvalue=False,
            command=on_move,
            bg=theme.SURFACE,
            fg=theme.TEXT,
            troughcolor=theme.SURFACE_2,
            activebackground=theme.ACCENT,
            highlightthickness=0,
            bd=0,
            sliderrelief="flat",
            sliderlength=18,
            width=10,
        )
        scale.pack(fill="x")
        on_move("")
        return row

    def _check(
        self, parent: tk.Frame, label: str, var: tk.BooleanVar, command: Any = None
    ) -> tk.Checkbutton:
        """Return a themed checkbox."""
        chk = tk.Checkbutton(
            parent,
            text=label,
            variable=var,
            command=command or (lambda: None),
            bg=theme.SURFACE,
            fg=theme.TEXT,
            selectcolor=theme.SURFACE_2,
            activebackground=theme.SURFACE,
            activeforeground=theme.TEXT,
            font=self._fonts.body,
            anchor="w",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        chk.pack(fill="x", pady=(8, 0))
        return chk

    def _swatch(
        self,
        parent: tk.Frame,
        label: str,
        var: tk.StringVar,
        command: Any,
        allow_auto: bool = False,
    ) -> tk.Label:
        """Return a colour swatch that opens a picker when clicked."""
        col = tk.Frame(parent, bg=theme.SURFACE)
        col.pack(side="left", fill="x", expand=True)
        tk.Label(col, text=label, bg=theme.SURFACE, fg=theme.MUTED, font=self._fonts.body).pack(
            anchor="w"
        )
        chip = tk.Label(
            col,
            text="auto" if (allow_auto and not var.get()) else "",
            bg=var.get() or theme.SURFACE_2,
            fg=theme.MUTED,
            font=self._fonts.data,
            width=8,
            height=1,
            relief="flat",
            bd=1,
            cursor="hand2",
        )
        chip.pack(anchor="w", pady=(4, 0), ipady=4)
        chip.bind("<Button-1>", lambda _e: command())
        return chip

    # ------------------------------------------------------------------
    # File queue
    # ------------------------------------------------------------------

    def _on_add(self) -> None:
        """Prompt for SVG files and add them to the queue."""
        paths = filedialog.askopenfilenames(
            title="Add SVG files", filetypes=[("SVG files", "*.svg"), ("All files", "*.*")]
        )
        for path in paths:
            self._add_file(path)

    def _add_file(self, path: str) -> None:
        """Add one file to the queue if it is not already there."""
        resolved = str(Path(path))
        if resolved in self._files:
            return
        self._files.append(resolved)
        self._file_list.insert("end", Path(resolved).name)
        if self._file_list.size() == 1:
            self._file_list.selection_set(0)
        self._status.configure(text=f"{len(self._files)} file(s) ready")

    def _on_remove(self) -> None:
        """Remove the selected file from the queue."""
        index = self._selected_index()
        if index is None:
            return
        self._file_list.delete(index)
        del self._files[index]

    def _on_clear_files(self) -> None:
        """Empty the queue."""
        self._file_list.delete(0, "end")
        self._files.clear()

    def _selected_index(self) -> int | None:
        """Return the selected file index, or None."""
        selection = self._file_list.curselection()
        return int(selection[0]) if selection else None

    # ------------------------------------------------------------------
    # Tool and colour controls
    # ------------------------------------------------------------------

    def _select_tool(self, value: str) -> None:
        """Switch the active tool and refresh the toggle and sliders."""
        if self._rendering:
            return
        self.tool.set(value)
        self._sync_tool_controls()

    def _sync_tool_controls(self) -> None:
        """Reflect the tool and animate state in the toggle and sliders."""
        for value, btn in self._tool_buttons.items():
            selected = value == self.tool.get()
            btn.configure(
                bg=theme.ACCENT if selected else theme.SURFACE_2,
                fg=theme.INK if selected else theme.MUTED,
            )
        # Show the width slider for the active tool only.
        self._pencil_slider.pack_forget()
        self._brush_slider.pack_forget()
        if self.tool.get() == "brush":
            self._brush_slider.pack(fill="x", pady=(10, 0))
        else:
            self._pencil_slider.pack(fill="x", pady=(10, 0))

    def _on_background(self) -> None:
        """Pick the page colour."""
        chosen = colorchooser.askcolor(color=self.background.get() or "#ffffff", title="Background")
        if chosen and chosen[1]:
            self.background.set(chosen[1])
            self._background_swatch.configure(bg=chosen[1], text="")
            if self._canvas is not None:
                resolved = parse_color(chosen[1]) or WHITE
                self._canvas.set_background(resolved)

    def _on_ink(self) -> None:
        """Pick the drawing ink, or reset it to each shape's own colour."""
        chosen = colorchooser.askcolor(color=self.ink.get() or "#333333", title="Ink")
        if chosen and chosen[1]:
            self.ink.set(chosen[1])
            self._ink_swatch.configure(bg=chosen[1], text="")

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _ensure_canvas(self) -> EmbeddedTurtleCanvas:
        """Attach the embedded canvas on first use."""
        if self._canvas is None:
            self._canvas_widget.update_idletasks()
            background = parse_color(self.background.get()) or WHITE
            self._canvas = EmbeddedTurtleCanvas(self._canvas_widget, background)
            self._canvas.open()
        return self._canvas

    def _build_config(self, input_path: str) -> RenderConfig:
        """Assemble a RenderConfig from the current control values."""
        width, height = self._canvas_size()
        sketching = self.animate.get()
        return RenderConfig(
            input_path=input_path,
            canvas_width=width,
            canvas_height=height,
            background=self.background.get() or "white",
            sketch=sketching,
            sketch_tool="brush" if self.tool.get() == "brush" else "pencil",
            duration=self.duration.get() if sketching else None,
            fps=int(self.fps.get()),
            pencil_width=self.pencil_width.get(),
            brush_width=self.brush_width.get(),
            pencil_color=self.ink.get() or None,
            fill_flow=self.fill_flow.get(),
            show_pencil=self.show_cursor.get(),
            fit="content" if self.fit_content.get() else "viewbox",
            fill=self.paint_fill.get(),
            stroke=self.paint_stroke.get(),
            color_mode=_color_mode(self.color_mode.get()),
            keep_open=False,
            show_progress=False,
        )

    def _canvas_size(self) -> tuple[int, int]:
        """Return the canvas widget's current size, clamped for validation."""
        self._canvas_widget.update_idletasks()
        width = max(self._canvas_widget.winfo_width(), 100)
        height = max(self._canvas_widget.winfo_height(), 100)
        return width, height

    def _on_draw(self) -> None:
        """Render the selected file onto the canvas."""
        if self._rendering:
            return
        index = self._selected_index()
        if index is None:
            if not self._files:
                messagebox.showinfo("SVG Turtle Studio", "Add an SVG file first.")
                return
            index = 0
            self._file_list.selection_set(0)

        path = self._files[index]
        try:
            config = self._build_config(path)
        except SVGTurtleError as exc:
            messagebox.showerror("Cannot draw", str(exc))
            return

        canvas = self._ensure_canvas()
        if self.clear_before.get():
            canvas.clear()

        self._set_running(True)
        self._stop_requested = False
        self._status.configure(text=f"Drawing {Path(path).name}", fg=theme.TEXT)

        try:
            stats, stopped = run_render(
                config,
                canvas,
                present=canvas.frame,
                pump=self._root.update,
                should_stop=lambda: self._stop_requested,
                report=self._report_progress,
            )
        except SVGTurtleError as exc:
            self._status.configure(text=f"Failed: {exc}", fg=theme.DANGER)
            logger.error("Render failed: %s", exc)
            return
        except tk.TclError:
            # The window was closed mid-render; nothing more to do.
            return
        finally:
            self._set_running(False)

        self._report_done(Path(path).name, stats, stopped)

    def _on_stop(self) -> None:
        """Ask the running render to stop at the next frame."""
        if self._rendering:
            self._stop_requested = True
            self._status.configure(text="Stopping", fg=theme.MUTED)

    def _on_clear_canvas(self) -> None:
        """Wipe the canvas."""
        if self._rendering or self._canvas is None:
            return
        self._canvas.clear()
        self._progress_value.set(0.0)
        self._progress_text.configure(text="")
        self._status.configure(text="Canvas cleared", fg=theme.MUTED)

    def _on_export(self) -> None:
        """Save the current canvas to a PNG."""
        if self._rendering or self._canvas is None:
            messagebox.showinfo("SVG Turtle Studio", "Draw something first.")
            return
        path = filedialog.asksaveasfilename(
            title="Export PNG", defaultextension=".png", filetypes=[("PNG image", "*.png")]
        )
        if not path:
            return
        try:
            written = self._canvas.export(path)
        except SVGTurtleError as exc:
            messagebox.showerror("Export failed", str(exc))
            return
        self._status.configure(text=f"Exported {Path(written).name}", fg=theme.GOOD)

    # ------------------------------------------------------------------
    # Progress and status
    # ------------------------------------------------------------------

    def _report_progress(self, done: float, total: float, unit: str) -> None:
        """Paint the progress bar; called from inside the render."""
        self._progress.configure(maximum=total)
        self._progress_value.set(done)
        if unit == "px":
            self._progress_text.configure(text=f"{done / 1000:.1f}k / {total / 1000:.1f}k px")
        else:
            self._progress_text.configure(text=f"{int(done)} / {int(total)} {unit}")

    def _report_done(self, name: str, stats: Any, stopped: bool) -> None:
        """Show the final status once a render finishes."""
        if stopped:
            self._status.configure(text=f"Stopped {name}", fg=theme.MUTED)
            return
        self._progress_value.set(self._progress["maximum"])
        detail = (
            f"{stats.shape_count:,} shapes, "
            f"{stats.vertex_count:,} vertices, "
            f"{format_duration(stats.render_seconds)}"
        )
        self._status.configure(text=f"Drew {name} — {detail}", fg=theme.GOOD)

    def _set_running(self, running: bool) -> None:
        """Enable or disable controls for the duration of a render."""
        self._rendering = running
        self._draw_button.configure(state="disabled" if running else "normal")
        self._stop_button.configure(state="normal" if running else "disabled")
        for button in (self._clear_canvas_button, self._export_button):
            button.configure(state="disabled" if running else "normal")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        """Stop any render, then close the window."""
        self._stop_requested = True
        if self._canvas is not None:
            self._canvas.close()
        self._root.destroy()

    def run(self) -> None:
        """Show the window and enter the event loop."""
        self._root.update_idletasks()
        self._root.geometry(f"{_RAIL_WIDTH + _CANVAS_MIN[0] + 40}x{_CANVAS_MIN[1] + 120}")
        self._root.mainloop()


def launch(initial_files: list[str] | None = None) -> int:
    """Open the dashboard. Returns a process exit code."""
    try:
        dashboard = Dashboard(initial_files)
    except tk.TclError as exc:
        logger.error("Could not open the dashboard: %s", exc)
        return 1
    dashboard.run()
    return 0
