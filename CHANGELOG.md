# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Desktop studio** (`python main.py --gui`, or the `svg-turtle-studio` command).
  A tkinter dashboard that queues SVG files and draws them on an embedded turtle
  canvas, with controls for the tool (pencil or brush), width, duration, frame
  rate, colours, fill options and colour mode. The window stays open until it is
  closed deliberately; a finished render never dismisses it. Stop halts a drawing
  at once and keeps what was drawn; Export saves the canvas.
  - `EmbeddedTurtleCanvas` draws into a `TurtleScreen` the dashboard owns,
    reusing every drawing method from the windowed canvas.
  - `GuiClock` paces the render by pumping the Tk event loop instead of sleeping,
    so the controls stay live and Stop responds at once, on one thread and
    without turtle's thread-unsafety.
  - The rail scrolls when its controls do not all fit, with Draw and Stop pinned
    to a footer so they are always in reach.
  - The artwork is centred in the panel with margins on every side. Turtle reads
    a plain canvas widget's default size, not its stretched size, and centred its
    origin on that phantom, so drawings clipped off the top-left; the embedded
    canvas now recentres the scroll region on the widget's real size.
  - Settings use animated toggle switches instead of Tk's near-invisible
    checkboxes, so each one's state reads at a glance and flipping it slides.

- **Brush sketch tool** (`--brush`, or `--sketch-tool brush`). The brush traces
  outlines in thick coloured strokes and paints the fill in visible horizontal
  courses rather than clipped bands. Each row is a wide stroke drawn only across
  the parts of that scanline inside the shape (`geometry/scanline.py`), so holes
  stay open and the rows, spaced closer than the brush is wide, leave no stripes.
  `--brush-width` sets the stroke width. A brush cursor follows the paint.
  - The duration model and progress bar are shared with the pencil, so a brush
    drawing still finishes on time and reports its progress by distance.

- **Streaming fill** for sketch mode (`--fill-flow`, on by default). Instead of a
  fill appearing all at once when its outline finishes, the colour sweeps across
  the shape as a horizontal front. The shape is clipped to a growing band and
  filled strip by strip (`geometry/banding.py`); the strips overlap by half a
  pixel so no seam shows. The banded result is pixel-identical to a single fill,
  verified against an independent nonzero-winding rasteriser. `--no-fill-flow`
  restores the single snap fill.
  - The `--duration` model now folds the fill front's sweep into the total
    distance, so a streamed drawing still finishes on time.
  - The progress bar counts the fill sweep as well as the pencil travel.

- **Pencil sketch mode** (`--sketch`) — draws from a blank canvas, tracing every
  shape's outline with a pencil at a steady hand-speed and then painting it in.
  - Paces by *distance* rather than by vertices (`geometry/polyline.py`), so the
    pencil moves at a constant speed instead of crawling around dense curves and
    jumping across long straight edges.
  - Traces a shape's geometry whether or not it has a stroke, so fill-only
    artwork has an outline to watch being drawn.
  - `--duration` solves for the speed from the total distance, accounting for the
    per-sub-path and per-fill frame overhead, and warns when the requested time
    is below the structural floor of one frame per sub-path.
  - `--pencil-speed`, `--pencil-color`, `--pencil-width`, `--no-show-pencil`.
  - A pencil-shaped cursor follows the line, on its own turtle so it stays
    graphite rather than being repainted in each shape's ink, and points along
    the direction of travel.
- `SketchClock`, which *waits* to hold a frame rate, alongside `FrameClock`, which
  *drops* frames to hold one; both satisfy the new `Clock` protocol.
- `Canvas.show_cursor`, so the cursor is part of the backend contract rather than
  a turtle-only detail.

### Changed

- **The progress bar now counts the work being watched.** Painting counts shapes,
  as before; sketching counts pixels of pencil travel, with a rate and an ETA.
  The renderer reports its own progress through a `Progress` protocol instead of
  being wrapped in a bar from outside, which is what allows the unit to differ.
  This also removes the awkward `render(shapes, progress=<the same shapes>)`
  argument.

### Fixed

- A sketch of a single-path drawing showed `0%| 0/1 shape` for the entire
  drawing and then jumped to 100% — useless exactly where progress matters most,
  since one path can take a minute to sketch.

## [0.1.0] - 2026-07-17

First release.

### Added

- **Rendering engine** — parse, fit, transform, simplify, order, draw, with the
  whole pipeline injectable and runnable headless via the `Canvas` protocol.
- **Path parsing** — the complete command grammar (`M m L l H h V v C c S s Q q
  T t A a Z z`), implicit argument repeats, unseparated arc flags (`a1 1 0 011 1`),
  and specification-conformant truncation at a syntax error.
- **Adaptive curve flattening** — recursive subdivision by flatness for cubics and
  quadratics; endpoint-to-centre parameterisation for elliptical arcs, including
  the out-of-range radius correction.
- **Transforms** — `matrix`, `translate`, `scale`, `rotate`, `skewX`, `skewY`,
  composed through nested groups and baked into geometry. Stroke widths scale by
  `sqrt(|det|)`.
- **Shapes** — `path`, `rect` (with `rx`/`ry`), `circle`, `ellipse`, `line`,
  `polygon`, `polyline`.
- **Structure** — `g`, `svg`, `a`, `defs`, `symbol`, `switch` (first viable child
  only), and `use` with `href`/`xlink:href`, per-instance style and cycle
  detection.
- **Fill rules** — both `nonzero` (SVG's default) and `evenodd`, translated into
  even-odd ring groups the turtle backend can draw.
- **Colour** — hex (3/4/6/8 digit), `rgb()`, `rgba()`, `hsl()`, `hsla()`, modern
  space-separated syntax, percentages, angle units, 147 CSS named colours,
  `currentColor`, `none`/`transparent`.
- **Opacity** — `opacity`, `fill-opacity`, `stroke-opacity`, composited onto the
  page colour.
- **Clipping** — basic `clip-path` support, clipped to the clip path's bounding
  box (Sutherland–Hodgman for polygons, Liang–Barsky for polylines).
- **Framing** — auto-fit with aspect preservation, centring, margins, explicit
  scale, offsets, rotation, mirror, flip, and `--fit content`.
- **Rendering modes** — fill/stroke toggles, wireframe, mono and random colour
  modes, five themes, progressive animation with frame pacing, instant mode.
- **Performance** — Douglas–Peucker simplification, nearest-neighbour path
  ordering, adjustable curve resolution, tqdm progress, statistics reporting.
- **Export** — PNG via Ghostscript, falling back to a DPI-corrected screen grab,
  falling back to EPS.
- **CLI** — full flag set, JSON config files, themes that never override an
  explicit flag, informative errors, meaningful exit codes.
- **Tests** — 471 headless tests plus a display smoke test and
  `scripts/smoke_render.py`; 89% coverage.

### Fixed

These were found while building, and are recorded because each is a trap worth
knowing about:

- **Chequerboarding on compound paths.** Rings were stitched into one Tk polygon
  as a chain (`A → B → C`), so the bridges formed a polygon whose edges flipped
  even-odd parity across the artwork. Rings are now reached by spokes from a hub
  and retraced, so bridges cancel. A two-ring donut hides this bug completely;
  it only appears from three rings up.
- **Nonzero fill treated as even-odd.** SVG's default rule is nonzero, but Tk
  fills even-odd, so overlapping same-direction rings cancelled into holes.
- **`closepath` followed by a draw command** continued the closed subpath instead
  of starting a new one at the initial point.
- **Path errors discarded the whole element** rather than rendering up to the
  offending command.
- **`"" in "Zz"` is `True`.** A substring test meant the initial "no previous
  command" state masqueraded as a closepath, silently inventing a subpath at the
  origin.
- **Stroke-only mode dropped unstroked shapes**, because the fill colour was
  cleared before being checked as a fallback outline.
- **`<switch>` rendered every child** instead of only the first viable one.
- **Reopening a turtle window failed on every second attempt**, because turtle's
  `bye()` leaves `TurtleScreen._RUNNING` false.
- **Screen-grab export captured the wrong region** on scaled displays, since Tk
  reports logical pixels and `ImageGrab` works in physical ones.

[Unreleased]: https://github.com/bhanuka/svg-turtle-renderer/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/bhanuka/svg-turtle-renderer/releases/tag/v0.1.0
