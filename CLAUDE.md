# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

`img2dxf` converts raster images (PNG/JPEG) into DXF files of **contour outlines** for
laser etching/cutting machines. It is a Tkinter desktop app on top of a headless
pipeline library; a CLI drives the same pipeline.

Deliberately *not* in scope: raster/scan-line engraving and centerline (skeleton)
tracing. The output is always closed boundary polylines, arcs and circles.

## Commands

```powershell
.\.venv\Scripts\python.exe -m pytest                  # full suite
.\.venv\Scripts\python.exe -m pytest tests/test_kerf.py -q
.\.venv\Scripts\python.exe -m img2dxf                 # launch the GUI
.\.venv\Scripts\python.exe -m img2dxf.cli in.png -o out.dxf --width-mm 80
```

The virtualenv is `.venv/`. Use `.\.venv\Scripts\python.exe` — the system Python does
not have the dependencies installed.

## Architecture

One-way data flow; each stage only knows about the one before it.

```
apply_transform ─► prepare ─► binarize ─► trace_mask ─► to_millimetres ─► offset_paths ─► _fit_arcs ─► write_dxf
   transform      preprocess  preprocess    trace          geometry          kerf          pipeline      dxfwrite
                                       └────────── pipeline.run() orchestrates ──────────┘
```

| Module | Responsibility |
|---|---|
| [params.py](img2dxf/params.py) | `TraceParams` — every knob, plus `PRESETS` and `normalized()` clamping |
| [transform.py](img2dxf/transform.py) | rotate (expanding the canvas) then crop, by fractions |
| [preprocess.py](img2dxf/preprocess.py) | load, grayscale, denoise/blur, the five binarize modes, morphology. Always outputs `uint8` masks where 255 = burn |
| [trace.py](img2dxf/trace.py) | `findContours` + hierarchy → `Path` objects, Douglas-Peucker, Chaikin smoothing; returns kept **and** discarded contours |
| [geometry.py](img2dxf/geometry.py) | `Path`/`Bounds`, `pixels_per_mm`, `to_millimetres` (the Y-flip lives here) |
| [kerf.py](img2dxf/kerf.py) | pyclipper polygon offsetting for beam-width compensation |
| [arcfit.py](img2dxf/arcfit.py) | recover circles and arcs from polylines; also flattens them back for drawing |
| [pipeline.py](img2dxf/pipeline.py) | `run()` / `run_file()` → `TraceResult` |
| [dxfwrite.py](img2dxf/dxfwrite.py) | ezdxf export, version handling, layers, bulges |
| [cli.py](img2dxf/cli.py) | argparse front end |
| [gui/](img2dxf/gui/) | Tkinter shell — see below |

### The rules that keep this coherent

**`TraceParams` is the only configuration object.** The GUI, the CLI and the tests all
build one and hand it to `pipeline.run()`. Adding a knob means: a field in
`TraceParams`, clamping in `normalized()`, a widget in `gui/controls.py` (and its entry
in `ControlPanel.params()`), and a flag in `cli.py`. Do not thread ad-hoc arguments
through the pipeline instead.

**User-facing lengths are millimetres; internals are pixels.** `simplify_mm` and
`min_area_mm2` are converted using `px_per_mm` inside `trace_mask`. Never expose a
pixel-valued tolerance in the UI — it means nothing to someone sizing a job.

**Y is flipped exactly once**, in `geometry.to_millimetres`. Image rows run down from
the top-left; DXF Y runs up from the bottom-left. Anything that draws traced paths back
in image space (`gui/preview.py`) has to undo it. If output ever appears mirrored, look
here first.

**Holes come from the contour hierarchy.** `trace_mask` uses `RETR_CCOMP` and attaches
child contours to their parent `Path` as holes. This is what keeps the counter of an
"O" open. `CHAIN_APPROX_NONE` is intentional — simplification is done afterwards with
the user's tolerance, not by OpenCV.

**Posterize masks are cumulative.** Each darker tone's mask includes everything darker
still, so the bands nest like contour lines instead of meeting at hairline seams the
laser would leave as gaps. The lightest band is skipped — that is paper, not a burn.

**Stage order is load-bearing.** Transform first, so every later measurement describes
the piece the user is looking at. Kerf before arc fitting, so arcs describe the path
the machine will actually follow. Kerf after simplification, so Clipper is not paid to
offset thousands of redundant points.

### Kerf (`kerf.py`)

Clipper derives grow-vs-shrink from **winding direction**, so orientation is enforced
rather than assumed: outer rings counter-clockwise, holes clockwise, then one positive
delta grows outlines and shrinks holes together. Offsetting can merge, split, or
dissolve shapes, so outer/hole nesting is rebuilt from the output by orientation and
containment, never carried over. Each tone level is offset separately — merging across
levels would move geometry onto the wrong layer.

`ArcTolerance` must be set explicitly; Clipper's default works out to a quarter of a
micron here and buries a simple outline under thousands of points.

### Arc fitting (`arcfit.py`)

Four guards, each of which was added because its absence produced a visible defect:

1. **Probe segment midpoints, not just vertices.** Simplification leaves a long
   straight edge as two points, and a big circle passes through any two points — so a
   vertex-only check lets an arc swallow a straight side and run into the next corner.
   `fit_circle` needs this too: every regular polygon has equidistant corners, so a
   square's four vertices fit a circle perfectly.
2. **Require the run to bow away from its chord** before accepting an arc, or straight
   runs become arcs carrying near-zero bulges. This is checked at *acceptance*, not
   during growth — the seed window is short, and a genuine arc barely bows over it.
3. **Derive sweep from every point, unwrapped.** Judging direction from a single
   midpoint gets the sign wrong, and an arc with the right endpoints but the wrong
   direction takes the long way round the circle.
4. **Gate on the realized arc.** DXF rebuilds an arc through its two *endpoints*, which
   carry their own fitting error, so the arc the machine follows is a slightly
   different circle from the least-squares one. Measure against the former.

The tolerance is the looser of `simplify_mm` and **one source pixel**. The pixel floor
matters: a traced circle is a staircase of whole pixels and departs from any true
circle by about half a pixel, so a tighter demand rejects every real circle.

Arcs are written as polyline **bulges**, not separate ARC entities, so a ring stays one
closed contour with no seams for the controller to lift over.

### GUI layer

| Module | Responsibility |
|---|---|
| [gui/app.py](img2dxf/gui/app.py) | window, files, canvas interaction (zoom/pan/crop/measure), export |
| [gui/controls.py](img2dxf/gui/controls.py) | widgets ⇄ `TraceParams`, presets, per-mode slider visibility |
| [gui/preview.py](img2dxf/gui/preview.py) | `ViewState` + coordinate mapping, and rendering the four views |
| [gui/worker.py](img2dxf/gui/worker.py) | debounced, single-flight background tracing |
| [gui/recent.py](img2dxf/gui/recent.py) | recent-files list in `~/.img2dxf/recent.json` |

**Never run the pipeline on the Tk main thread.** `TraceWorker` debounces by 150 ms,
runs on a background thread, and posts results through a queue that Tk polls. Results
carry a token; anything older than the newest request is discarded so a slow trace
cannot overwrite a newer one. New work goes through `App._retrace()`.

**Coordinate mapping lives in `ViewState`**, not in the window: the crop handles and
the measure tool both need canvas ⇄ image conversion, and two copies would drift.
`ViewState.fitted` records that the view is still auto-fitting, so loading an image or
resizing refits rather than stranding the user at a stale zoom.

**The preview must draw what will be exported.** `_curve_of` expands fitted arcs and
circles via `arcfit.flatten_ring` / `circle_points`; drawing the raw reduced vertices
would show a coarse polygon for a shape that exports as a smooth curve.

`ControlPanel._suspend` guards against re-tracing once per widget while a preset is
loaded. The crop box is **not** a Tk variable (it holds `None` or a tuple) — it lives
in `ControlPanel._crop`, reached via `crop()` and `set_field("crop", ...)`. Presets
deliberately leave rotation and crop alone: those describe the photo in front of the
user, not the tracing style.

## DXF constraints worth remembering

- `$INSUNITS = 4` (mm) is what makes LightBurn import at the right scale.
- **R12 has neither `$INSUNITS` nor `LWPOLYLINE`.** `build_document` writes old-style
  `POLYLINE` for R12 (with bulges set per vertex rather than as a point format) and
  skips the units header; `units_are_declared()` tells the UI to warn the operator.
  `ezdxf.new()` logs a warning about units regardless, which
  `_muted_r12_units_warning` suppresses for R12 since it is expected.
- One layer per posterize tone (`CUT_TONE_0`…), each a different ACI colour, because
  colour is how most laser software assigns power/speed.

## Testing

Fixtures in [tests/conftest.py](tests/conftest.py) are generated in code — a square, a
ring, a gradient — so the repo carries no binary test assets.

These matter more than the rest, because they cover the failure modes that ruin a real
job:

- `test_exported_square_measures_the_requested_size` — a known-size square must come
  back out of the written file at the requested millimetres.
- `test_y_flip_survives_export` — a shape at the top of the image must land at high Y.
- `test_outside_grows_the_part_by_one_kerf` / `test_hole_moves_opposite_to_its_outline`
  — the kerf sign convention, which is silently wrong if inverted.
- `test_fitted_arcs_stay_within_tolerance` and `test_square_is_not_a_circle` — arc
  fitting must not distort or hallucinate curves.

Keep them passing. Tests that assert on vertex counts or polyline structure should set
`fit_arcs=False`, or arc fitting will legitimately change the answer.

GUI tests build widgets on a withdrawn `Tk()` root and never call `mainloop()`; they
skip automatically where Tk is unavailable.

## Conventions

- Comments explain *why* (the laser, DXF, or geometry reason), not what the call does.
- Public functions carry docstrings; dataclass fields are documented with `#:` or
  trailing string literals.
- `from __future__ import annotations` at the top of every module.
- Optional dependencies are imported in `try/except ImportError` with a working
  fallback — see `tkinterdnd2` in `gui/app.py`.
- Keep third-party warning noise out of the user's console — see the ezdxf handling in
  `dxfwrite.py` and the `filterwarnings` entry in `pyproject.toml`.
