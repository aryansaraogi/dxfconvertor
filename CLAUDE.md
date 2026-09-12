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
apply_transform ─► supersample ─► prepare ─► binarize ─► trace_mask ─► to_millimetres ─► straighten_paths ─► offset_paths ─► _fit_arcs ─► tile_paths
   transform         detail        preprocess  preprocess    trace          geometry         straighten          kerf          pipeline      tile
                                          └──────────────── pipeline.run() orchestrates ────────────────┘

then, at write/draw time only:   split_ring (tabs) ─► write_dxf / write_svg / preview
```

`prepare` also carries the tone adjustments (auto-levels, brightness, contrast,
gamma, sharpen) ahead of the existing denoise and blur.

| Module | Responsibility |
|---|---|
| [params.py](img2dxf/params.py) | `TraceParams` — every knob, plus `PRESETS` and `normalized()` clamping |
| [transform.py](img2dxf/transform.py) | rotate (expanding the canvas) then crop, by fractions |
| [detail.py](img2dxf/detail.py) | supersampling factor and the upscale itself |
| [straighten.py](img2dxf/straighten.py) | flatten runs that are structurally straight lines |
| [preprocess.py](img2dxf/preprocess.py) | load, grayscale, denoise/blur, the five binarize modes, morphology. Always outputs `uint8` masks where 255 = burn |
| [trace.py](img2dxf/trace.py) | `findContours` + hierarchy → `Path` objects, Douglas-Peucker, Chaikin smoothing; returns kept **and** discarded contours |
| [geometry.py](img2dxf/geometry.py) | `Path`/`Bounds`, `pixels_per_mm`, `to_millimetres` (the Y-flip lives here) |
| [kerf.py](img2dxf/kerf.py) | pyclipper polygon offsetting for beam-width compensation |
| [arcfit.py](img2dxf/arcfit.py) | recover circles and arcs from polylines; also flattens them back for drawing |
| [pipeline.py](img2dxf/pipeline.py) | `run()` / `run_file()` → `TraceResult` |
| [tile.py](img2dxf/tile.py) | repeat the job on a grid to fill a sheet |
| [tabs.py](img2dxf/tabs.py) | cut rings into open segments, leaving uncut bridges |
| [dxfwrite.py](img2dxf/dxfwrite.py) | ezdxf export, version handling, layers, bulges |
| [svgwrite.py](img2dxf/svgwrite.py) | SVG export at true mm size |
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
offset thousands of redundant points. Tiling last, so each shape is arc-fitted once and
then copied.

**Tabs are not a pipeline stage.** A gap partway along a ring cannot be carried by
`Path`, whose rings are closed by definition — splitting rings inside the pipeline
would break `bounds_of`, the kerf nesting rebuild, and the bed check. Instead
`tabs.open_segments` is called at write and draw time by `dxfwrite`, `svgwrite` and
`gui/preview` alike, so the preview shows exactly the gaps that get written. Add a new
output format and it must call the same function.

### Finish quality: why supersampling exists (`detail.py`)

**Binarization is the ceiling on edge quality, not simplification.** Measured against a
high-resolution ground truth, the error is identical at a 0.0 mm tolerance and at
0.3 mm — thresholding quantises every outline to the pixel grid and nothing downstream
recovers it. Tracing an upscaled copy is the only thing that helps, and it helps a lot:
2.2x lower error with 60% fewer vertices on a test logo, 2.3x on a small one.

Supersampling happens immediately after `apply_transform`, before anything reads the
pixels. Because `pixels_per_mm` is then derived from the enlarged image, every
millimetre-based tolerance keeps its exact physical meaning and no other stage needs
adjusting. That is the whole reason it goes there.

The one thing that *does* need the factor: **tolerance floors are measured in source
pixels.** An interpolated pixel carries no information the original did not, so both
`_fit_arcs` and `straighten.effective_tolerance` divide by `detail_factor / px_per_mm`,
not `1 / px_per_mm`. Forget it and a supersampled circle stops being detected as a
circle.

Two approaches were measured and **rejected** — do not revisit them without new
evidence. Moving the threshold to the 50%-coverage midpoint of an anti-aliased edge:
Otsu already lands there (128 vs 128). Sub-pixel contour refinement from the grayscale
gradient: 0.676 to 0.629 RMS, a fraction of supersampling's gain for much more
machinery.

### Straightening (`straighten.py`)

A stem that looks wavy is not a curved segment — after Douglas-Peucker every segment is
straight. It is *several* kept vertices zig-zagging, because the staircase departs from
the true edge by more than the tolerance and simplification is obliged to keep them.

Deciding a run is a straight line is therefore a separate judgement to a looser budget,
and getting the discriminator right took three attempts:

1. **An absolute bow limit alone** flattens curves. A gentle arc bows by `chord² / 8r`,
   so a 7 mm chord on a 50 mm radius strays only 0.15 mm and gets flattened into facets.
2. **Bow relative to length** is length-dependent, so short noisy runs never qualify and
   straightening silently never fired at all on real text.
3. **Turn coherence** (net turning over total turning) is scale- and radius-invariant —
   0 for a staircase, 1 for an arc — but a staircase laid *over* a curve adds so much
   total turning that a real curve's coherence is diluted below the threshold. That
   chamfered the shoulders of O and G, which the numbers did not show and a rendered
   picture did.

What works is both: coherence, plus `bend_deg` — the angle between lines fitted to the
run's two halves. Note it fits halves rather than summing per-vertex turns, because a
staircase's alternating turns cancel only when there is an even number of them; an odd
one leaves a whole phantom step of bend.

Endpoints are projected onto a least-squares line through the whole run, not left where
they were. Leaving them is simpler but worse: an endpoint sitting on a peak of the
staircase drags the flattened edge off to one side, so the result is straight but
displaced — that alone was the difference between straightening making accuracy worse
and making it better.

Rings that arc fitting already claimed are skipped, and a ring is never reduced below
three points.

### Corner-aware smoothing (`trace.py`)

Plain Chaikin cuts every corner equally: one pass pulls a true right angle in by a
quarter of the adjoining edge — 25 px on a 100 px square — which is what destroyed the
corners of L, T and E. `smooth_ring` pins vertices whose turn exceeds `corner_deg`,
splits the ring into runs between them, and smooths each run as an *open* polyline with
fixed endpoints.

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

### Tabs (`tabs.py`)

Gaps are spaced by **arc length**, not vertex index: vertices bunch on curves, so index
spacing would cluster every tab on the fiddliest part of the outline. Both ends of each
gap are interpolated onto the exact distance rather than snapping to a vertex, so the
cut length is exactly `perimeter - count * gap` — which is what the tests assert.

Two refusals are deliberate. A ring that cannot afford the requested tabs gets fewer
rather than none, and a ring too small for even one gap is left closed: losing a small
part entirely is worse than letting it drop through.

Tabs flatten arcs on the rings they cut (`open_segments` expands circles and bulges
first). Tabs and bulges are mutually exclusive per ring, and tabs win.

### Tiling (`tile.py`)

`geometry.translate` must deep-copy. `Path` carries `bulges` and `circles`, and a
fitted circle stores its own centre, so a shallow copy leaves every tile's circles
stacked at the first tile's position — silently, since the ring points do move. There
is a test for exactly this.

### SVG (`svgwrite.py`)

**SVG's Y axis points down**, the opposite of DXF, so `build_svg` flips back what
`to_millimetres` flipped. Two tests guard it, one comparing the vertical *order* of two
shapes (a single shape sits near both the top and bottom of its own bounding box, so an
unflipped export still looks right), and one un-flipping the SVG and matching every DXF
point.

`width`/`height` are in `mm` and the `viewBox` is in the same units, so the file opens
at true size.

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

**The bed is drawn on the Tk canvas, not into the preview image.** The image frame is
clipped to the artwork, and a bed is normally larger than the job, so drawing it there
leaves a sliver at the edge. `App._draw_bed` maps mm through `preview.mm_to_image_px`
and then `ViewState.image_to_canvas`, like the crop box and measure line.

**The preview must draw what will be exported.** `_curve_of` expands fitted arcs and
circles via `arcfit.flatten_ring` / `circle_points`; drawing the raw reduced vertices
would show a coarse polygon for a shape that exports as a smooth curve.

`ControlPanel._suspend` guards against re-tracing once per widget while a preset is
loaded. The crop box is **not** a Tk variable (it holds `None` or a tuple) — it lives
in `ControlPanel._crop`, reached via `crop()` and `set_field("crop", ...)`.

`_NOT_FROM_PRESETS` lists the fields a preset must never touch: framing (rotation,
crop), the machine (kerf, tabs, bed) and layout (copies, gap). Those describe the
user's photo and their machine, not the tracing style being chosen. Add a field of that
kind and it belongs in that set.

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
- `test_cut_length_is_perimeter_minus_the_gaps` — tabs must remove exactly the material
  asked for, no more.
- `test_finishing_is_more_accurate_with_fewer_vertices` — the headline claim, measured
  against the artwork rather than asserted.
- `test_a_noisy_curve_is_not_chamfered` and `test_curves_are_never_flattened` — the two
  ways straightening can eat a curve.
- `test_supersampled_circle_is_still_recognised` — the source-pixel tolerance floor.
- `test_y_axis_is_flipped_relative_to_dxf` and `test_unflipping_the_svg_reproduces_the_dxf`
  — the SVG axis flip.
- `test_reference_scaling_survives_the_whole_pipeline` — declaring a feature's real size
  must make it export at that size.

Keep them passing. Tests that assert on vertex counts or polyline structure should set
`fit_arcs=False`, or arc fitting will legitimately change the answer.

GUI tests build widgets on a withdrawn `Tk()` root and never call `mainloop()`; they
skip automatically where Tk is unavailable. Tests that need a traced result must use
the `pump()` helper, which **sleeps** between `update()` calls — the worker debounces by
150 ms, so spinning on `update()` alone never lets the timer fire, and the test sees no
result. `pump` also settles the busy indicator, so no repeating `after` outlives the
window and errors during teardown.

When you write both the code and its tests, mutate the code and check the test fails.
`test_y_axis_is_flipped_relative_to_dxf` passed against a deliberately broken flip in
its first form, which is how the two-shape version came about.

Numbers are not enough on their own either. The straightener's chamfering of O and G
passed every numeric check — the RMS error barely moved — and was obvious the moment the
outline was rendered. When changing how geometry is traced, draw it and look.

Measuring trace accuracy: compare against the artwork traced at 8x, use point-to-*segment*
distance (point-to-vertex punishes the goal of using fewer, better placed points), and
expand fitted arcs first or the measurement cuts straight chords across curves the file
actually draws correctly. `tests/test_finishing.py` has the harness.

## Conventions

- Comments explain *why* (the laser, DXF, or geometry reason), not what the call does.
- Public functions carry docstrings; dataclass fields are documented with `#:` or
  trailing string literals.
- `from __future__ import annotations` at the top of every module.
- Optional dependencies are imported in `try/except ImportError` with a working
  fallback — see `tkinterdnd2` in `gui/app.py`.
- Keep third-party warning noise out of the user's console — see the ezdxf handling in
  `dxfwrite.py` and the `filterwarnings` entry in `pyproject.toml`.
