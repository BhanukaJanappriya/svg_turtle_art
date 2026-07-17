# Contributing

Thanks for wanting to help. This document covers how to get set up, what the code
expects of you, and the couple of non-obvious things about this project's tests.

## Getting started

```bash
git clone https://github.com/bhanuka/svg-turtle-renderer.git
cd svg-turtle-renderer
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev,export]"
pytest
```

## Testing

```bash
pytest                            # the default suite: 471 tests, ~0.8s, no display
pytest -m display -s              # the window smoke test
python scripts/smoke_render.py    # multi-window end-to-end checks
pytest --cov=svg_turtle_renderer --cov-report=term-missing
```

### Why display tests are separate

Two things about Tk make window tests hostile to a normal pytest run, and both
cost real time to rediscover:

1. **pytest's capture breaks Tcl.** The default `--capture=fd` swaps out file
   descriptors 1 and 2. Tcl consults the standard channels while initialising, so
   with them redirected its setup fails intermittently — reporting a completely
   misleading `Can't find a usable init.tcl`. Hence `-s`.
2. **Tk dislikes many interpreters in one process.** Creating and destroying
   several windows in a single pytest process fails unpredictably, and the
   failure wanders between tests from run to run. A plain script does the same
   work without complaint.

So the window checks are kept to a single test that opens one window, and
anything needing several windows lives in `scripts/smoke_render.py`. If you find
yourself debugging a display test that fails in a different place each run,
suspect the harness before the code.

Everything else is tested headless against the `Canvas` protocol with
`RecordingCanvas`. If you are adding drawing behaviour, test it there — it is
faster, deterministic, and asserts on what would be drawn rather than on pixels.

## Style

- **PEP 8**, 100-column lines, enforced by `ruff check .` and `ruff format .`.
- **Type hints** on every public function. `mypy src` should stay clean.
- **PEP 257** docstrings on every public module, class and function.
- Comments explain *why*, not *what*. If a line needs a comment to say what it
  does, rename something instead.
- Layers depend downward only: `cli → core → {parser, geometry, renderer} → utils`.
  Nothing outside `renderer/turtle_renderer.py` may import `turtle`.

## Adding SVG features

The parser's job is to reduce a document to `Shape` objects with resolved
geometry and paint. When adding support for an element or attribute:

1. Add the parsing to `parser/svg_parser.py`, or a new module if it is
   substantial.
2. Put anything mathematical in `geometry/` as a pure function — no I/O, no
   turtle, no XML. It should be testable on its own.
3. Add tests to the matching `tests/test_*.py`.
4. Update the support table in `README.md`.

**Never guess.** If a construct cannot be honoured, skip it and warn through the
logger. A shape painted the wrong colour is worse than a shape that is visibly
missing, because the user cannot tell it happened.

If you are unsure what the correct behaviour is, the specification usually says
so outright — [SVG 1.1](https://www.w3.org/TR/SVG11/) is precise about path error
recovery, `closepath` semantics, arc parameterisation and fill rules. Quote it in
a comment when the reason is not self-evident.

## Pull requests

- One logical change per PR.
- `pytest` and `ruff check .` must pass; CI runs both.
- Add a `CHANGELOG.md` entry under *Unreleased*.
- Describe what you changed and **why**. If you fixed a rendering bug, a
  before/after image is worth a great deal.

## Reporting rendering bugs

Attach the SVG. Almost every rendering bug is specific to a construct in a
particular file, and without it a report is guesswork. Include:

- the file (or a minimal fragment that reproduces it),
- the command you ran,
- what you expected and what you got — screenshots help,
- `python main.py file.svg --stats -v` output.
