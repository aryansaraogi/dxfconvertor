# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

`img2dxf` converts raster images (PNG/JPEG) into DXF files of **contour outlines** for
laser etching/cutting machines. It is a Tkinter desktop app on top of a headless
pipeline library; a CLI drives the same pipeline.

Deliberately *not* in scope: raster/scan-line engraving and centerline (skeleton)
tracing. The output is always closed boundary polylines.

## Commands

```powershell
.\.venv\Scripts\python.exe -m pytest                  # full suite
.\.venv\Scripts\python.exe -m pytest tests/test_geometry.py -q
.\.venv\Scripts\python.exe -m img2dxf                 # launch the GUI
.\.venv\Scripts\python.exe -m img2dxf.cli in.png -o out.dxf --width-mm 80
```

The virtualenv is `.venv/`. Use `.\.venv\Scripts\python.exe` — the system Python does
not have opencv, pillow or ezdxf installed.

## Architecture

One-way data flow; each stage only knows about the one before it.

```
load_image ──► prepare ──► binarize ──► trace_mask ──► to_millimetres ──► write_dxf
 preprocess    preprocess   preprocess     trace         geometry          dxfwrite
                                     └── pipeline.run() orchestrates ──┘
```

| Module | Responsibility |
|---|---|
| [params.py](img2dxf/params.py) | `TraceParams` — every knob, plus `PRESETS` and `normalized()` clamping |
| [preprocess.py](img2dxf/preprocess.py) | load, grayscale, denoise/blur, the five binarize modes, morphology. Always outputs `uint8` masks where 255 = burn |
| [trace.py](img2dxf/trace.py) | `findContours` + hierarchy → `Path` objects, Douglas-Peucker, Chaikin smoothing |
| [geometry.py](img2dxf/geometry.py) | `Path`/`Bounds`, `pixels_per_mm`, `to_millimetres` (the Y-flip lives here) |
| [pipeline.py](img2dxf/pipeline.py) | `run()` / `run_file()` → `TraceResult` |
| [dxfwrite.py](img2dxf/dxfwrite.py) | ezdxf export, version handling, layers |
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

### GUI layer

| Module | Responsibility |
|---|---|
| [gui/app.py](img2dxf/gui/app.py) | window, file open/export, canvas, status bar |
| [gui/controls.py](img2dxf/gui/controls.py) | widgets ⇄ `TraceParams`, preset loading, per-mode slider visibility |
| [gui/preview.py](img2dxf/gui/preview.py) | renders Original / Mask / Vectors / Overlay via PIL |
| [gui/worker.py](img2dxf/gui/worker.py) | debounced, single-flight background tracing |

**Never run the pipeline on the Tk main thread.** `TraceWorker` debounces by 150 ms,
runs on a background thread, and posts results through a queue that Tk polls. Results
carry a token; anything older than the newest request is discarded so a slow trace
cannot overwrite a newer one. New work goes through `App._retrace()`.

`ControlPanel._suspend` guards against re-tracing once per widget while a preset is
being loaded. Set it when writing several variables at once (see `set_params`).

## DXF constraints worth remembering

- `$INSUNITS = 4` (mm) is what makes LightBurn import at the right scale.
- **R12 has neither `$INSUNITS` nor `LWPOLYLINE`.** `build_document` writes old-style
  `POLYLINE` for R12 and skips the units header; `units_are_declared()` tells the UI to
  warn the operator. `ezdxf.new()` logs a warning about units regardless, which
  `_muted_r12_units_warning` suppresses for R12 since it is expected.
- One layer per posterize tone (`CUT_TONE_0`…), each a different ACI colour, because
  colour is how most laser software assigns power/speed.

## Testing

Fixtures in [tests/conftest.py](tests/conftest.py) are generated in code — a square, a
ring, a gradient — so the repo carries no binary test assets.

Two tests matter more than the rest, because they cover the failure modes that ruin a
real job:

- `test_exported_square_measures_the_requested_size` — a known-size square must come
  back out of the written file at the requested millimetres.
- `test_y_flip_survives_export` — a shape at the top of the image must land at high Y.

Keep both passing. GUI tests build widgets on a withdrawn `Tk()` root and never call
`mainloop()`; they skip automatically where Tk is unavailable.

## Conventions

- Comments explain *why* (the laser or DXF reason), not what the call does.
- Public functions carry docstrings; dataclass fields are documented with `#:` or
  trailing string literals.
- `from __future__ import annotations` at the top of every module.
- Keep third-party warning noise out of the user's console — see the ezdxf handling in
  `dxfwrite.py` and the `filterwarnings` entry in `pyproject.toml`.
