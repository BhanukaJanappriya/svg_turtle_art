# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
