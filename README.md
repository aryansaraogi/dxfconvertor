<div align="center">

# img2dxf

**Turn any PNG or JPEG into a laser-ready DXF — in seconds, at the exact size you need.**

Drop in a logo, a scan or a photo, watch the cut path appear, and export clean outlines
that LightBurn, RDWorks and LaserCAD import at true millimetre scale.

![Platform](https://img.shields.io/badge/platform-Windows-0078D6)
![Output](https://img.shields.io/badge/output-DXF%20%7C%20SVG-2ea44f)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB)
![Version](https://img.shields.io/badge/version-0.1.0-informational)

[**⬇ Download for Windows**](https://github.com/aryansaraogi/dxfconvertor/releases/latest) ·
[Quick start](#quick-start) ·
[Features](#features) ·
[User guide](#user-guide) ·
[Troubleshooting](#troubleshooting)

</div>

---

## Why img2dxf?

Most image-to-vector tools are built for print. A laser cutter needs something different:
closed outlines, holes that stay holes, real millimetres, and paths that account for the
width of the beam. img2dxf is built for exactly that.

- **Accurate to size** — tell it "80 mm wide" and the part comes off the machine 80 mm wide.
- **Clean edges** — letter stems come out straight, curves come out as true arcs, corners
  stay sharp.
- **Machine-aware** — kerf compensation, holding tabs, bed-size checks and optimised
  cut order are built in.
- **Nothing to install** — one `.exe`, no Python, no setup.

## Download

1. Go to the [**latest release**](https://github.com/aryansaraogi/dxfconvertor/releases/latest).
2. Download **`img2dxf.exe`**.
3. Double-click it. That's it.

> **Windows SmartScreen** may warn about an unrecognised app the first time. Click
> **More info → Run anyway**.

Prefer to run from source, or on macOS/Linux? See [Run from source](#run-from-source).

## Quick start

1. **Open an image** — click **Open...**, or drag a PNG/JPEG onto the window.
2. **Pick a preset** — `Logo / clipart`, `Photo`, `Line art / scan` or `Edge outline`.
3. **Set the size** — type the finished width in millimetres.
4. **Check the preview** — switch to *Overlay* to see the cut path over your artwork.
5. **Export** — save as DXF (or SVG) and open it in your laser software.

Not sure what a control does? Hover over it. Press **F1** for a step-by-step walkthrough.

### Before your first real job

Cut the built-in calibration piece once to confirm your machine and settings agree with
the file. It takes a minute and saves material. See [Calibrate your machine](#calibrate-your-machine).

## Features

| | |
|---|---|
| 🎯 **True-size output** | Set width, height or DPI — or measure a feature you know and let it scale the whole job |
| ✨ **Clean finish** | Supersampling, straightening and corner-aware smoothing: 2.2x more accurate with 60% fewer points on a test logo |
| ⭕ **Real arcs and circles** | Curves are written as arcs, not thousands of tiny segments |
| 🔪 **Kerf compensation** | Offset paths by the beam width so parts and holes keep their drawn size |
| 🧷 **Holding tabs** | Leave uncut bridges so small parts don't fall through the bed |
| 🗺️ **Smart cut order** | Holes before outlines, and typically 60% less head travel |
| 🧱 **Sheet layout** | Tile copies on a grid, with a live check against your bed size |
| 🎨 **Photo engraving layers** | Split a photo into tone bands, one colour-coded layer each for power/speed |
| 🖼️ **Framing tools** | Rotate, crop and adjust brightness, contrast and gamma before tracing |
| 💾 **Saved jobs and presets** | Save every setting beside the image and get the same result next time |
| ⌨️ **Command line** | The same engine, scriptable for batch work |

**Works with:** LightBurn · RDWorks · LaserCAD · any software that reads DXF (R12, R2000, R2010) or SVG.

---

# User guide

- [Calibrate your machine](#calibrate-your-machine)
- [Tracing modes](#tracing-modes)
- [Getting a good result](#getting-a-good-result)
- [Finish quality](#finish-quality)
- [Setting the size](#setting-the-size)
- [Image adjustments and framing](#image-adjustments-and-framing)
- [Kerf compensation](#kerf-compensation)
- [Tabs (bridges)](#tabs-bridges)
- [Layout and the bed](#layout-and-the-bed)
- [Cut order](#cut-order)
- [The preview](#the-preview)
- [Saving jobs and presets](#saving-jobs-and-presets)
- [Output formats](#output-formats)
- [Command line](#command-line)

## Calibrate your machine

Every machine and material behaves a little differently, so check the output before you
trust it with material. Generate the calibration piece (from a
[source install](#run-from-source)):

```powershell
python -m img2dxf.calibrate -o calibration.dxf
```

It writes an 80 x 50 mm plate with a large hole, a small hole, a slot and a square
window, and prints what each should measure **as drawn in the file**. Cut it, measure
the part, and compare:

| What you see | What it means |
|---|---|
| Everything off by the same **percentage** | Import scale is wrong — set the import unit to mm |
| Everything off by the same **amount** | That amount is your kerf — enter it under *Kerf* |
| Only the **small** features are off | The kerf is eating them — reduce it or enlarge the artwork |

Kerf is deliberately zero on the test piece, so the error you measure *is* your kerf.

## Tracing modes

| Mode | Use it for |
|---|---|
| `otsu` | Logos, clipart, text — picks the threshold for you |
| `fixed` | When Otsu picks the wrong level; you set 0–255 yourself |
| `adaptive` | Scans and photos of paper with uneven lighting |
| `posterize` | Photographs — splits tones into bands, one DXF layer each |
| `edges` | Outlines only, no solid fills |

The presets set sensible starting values for each.

## Getting a good result

- **Size first.** Set the width in mm before adjusting anything else — tolerance and
  minimum-area are in millimetres, so they change meaning when the scale changes.
- **Watch the vertex count** in the status bar. A few thousand is fine; tens of
  thousands will crawl on the machine. Raise *Tolerance*, or leave arc fitting on — it
  typically halves the count on curved artwork.
- **Rough or rippled edges** on text and logos: leave *Detail* on Auto, or raise it.
  This is the control that matters; tolerance alone cannot fix it.
- **Stems that should be straight but waver**: raise *Straighten*. If curved artwork
  comes out faceted, lower it or set it to 0.
- **Speckles** mean the mask is noisy: raise *Min area* to drop them, or *Remove specks*
  to clean the mask before tracing.
- **Broken thin lines**: raise *Bridge gaps*, or use `adaptive` mode.
- **Photos** rarely work as a single threshold. Use the Photo preset with 3–4 tone
  levels, then give each `CUT_TONE_*` layer its own power and speed.

## Finish quality

Three controls decide how cleanly an edge comes out.

**Detail** is the important one. Thresholding rounds every outline to the pixel grid,
and that — not the tolerance — limits edge quality. Tracing an upscaled copy lifts that
ceiling. *Auto* scales small images up and leaves detailed ones alone, which is right
for almost everything; pin it to 1x–4x when you want to decide.

**Straighten** flattens edges whose wobble is just the pixel staircase, so letter stems
come out dead straight. It tells a staircase from a curve by how the run *bends*, not
how far it strays, so curves of any radius are left alone. Set it to 0 to trace edges
exactly as found.

**Corner angle** marks which turns count as corners. Smoothing never touches them, so
the Smoothing slider is safe on text — it softens the bowl of an O without rounding the
corners of an L.

Together these cut the error against the original artwork by **2.2x while using 60%
fewer vertices** on a test logo. Small logos gain most.

## Setting the size

Type a width or height in millimetres, or size from the image's DPI.

Don't know the overall width? Tick **Measure**, drag across a feature whose real size you
know, press **Set size…** and type that size. The whole job is rescaled so that feature
comes out exactly right.

## Image adjustments and framing

For photos and faint scans that threshold badly:

- **Auto levels** stretches the tonal range to fill 0–255, ignoring stray specks.
- **Brightness**, **Contrast** (pivots about mid-grey) and **Gamma** (midtones).
- **Sharpen** and **Blur** undo one another — use one or the other.

**Rotate** straightens a crooked scan (or use the ±90° buttons). Tick **Crop** and drag
a box on the preview to keep part of the image; crops compose, so you can narrow down in
steps. Both apply first, so "80 mm wide" always means the piece you can see.

## Kerf compensation

A laser removes material as it cuts. Cut exactly on the line and the part comes out a
beam-width undersized, with holes a beam-width oversized. Set **Kerf** to the width your
machine actually cuts (typically 0.1–0.2 mm) and pick a side:

- **Outside** — the *part* keeps its drawn size. The usual choice.
- **Inside** — the *hole* keeps its drawn size. Use when the hole has to fit something.

Outlines and holes are offset in opposite directions automatically. A feature thinner
than the kerf disappears, because the beam would consume it entirely.

## Tabs (bridges)

A closed cut releases the part the moment it finishes: it drops, tilts, and the beam
finishes its pass across whatever is underneath. Set **Tabs per path** to leave uncut
bridges and **Tab width** to size them (0.3–1 mm is typical). Snap the parts out
afterwards.

- Tabbed paths are written as plain polylines; everything else keeps its arcs.
- Rings too small to spare a gap are left closed rather than lost.
- If a path can't afford the requested tabs, it gets fewer.

## Layout and the bed

Enter your machine's **Bed** size and the preview draws it as a dashed outline — red,
along with the status bar, when the job won't fit. Leave it at 0 to turn the check off.

**Copies across/down** tiles the job on a grid to fill a sheet in one run, with **Tile
gap** between copies. The fit check measures the whole tiled layout.

## Cut order

Paths are ordered to minimise head travel, with each shape's holes cut before its
outline (a part that's already free can shift). Tone layers stay grouped, since layers
carry power and speed. Typically 60% less travel on scattered work — the status bar
shows the saving.

## The preview

- Scroll to **zoom**, drag to **pan**, **Fit** (or `F`) to reset.
- **Views:** Original, Mask, Vectors, Overlay.
- **Measure** — drag between two points to read the distance in mm.
- **Show dropped** — highlights in amber what *Min area* removed, so you can tell real
  detail from specks.
- Drag an image onto the window to open it; recent files are in the toolbar.
- Tick **Advanced** for the full set of tuning controls.

## Saving jobs and presets

There are over forty settings, so:

- **Settings → Save settings…** writes them all beside the image.
- **Settings → Load settings…** brings the job back exactly.
- **Save as preset…** adds your tuned settings to the preset list.

## Output formats

**DXF**
- Millimetres, Y up, origin bottom-left (or centred with *Centre output on 0,0*).
- Units are declared, so LightBurn imports at the right scale.
- Circles are written as `CIRCLE` entities and curves as polyline arcs, within one
  source pixel of the traced outline. Turn off arc fitting if your controller dislikes arcs.
- Each photo tone gets its own layer and colour (`CUT_TONE_0`, `CUT_TONE_1`, …).
- **Using R12** for an older RDWorks/LaserCAD setup? R12 can't store units — set the
  import unit to mm yourself.

**SVG**
- Opens at true physical size, keeps circles and arcs, one group per tone.

The GUI picks the format from the file extension you save with.

## Command line

The same engine, for scripts and batch jobs. The command line needs a
[source install](#run-from-source) (`pip install .` adds the `img2dxf` command); the
standalone `.exe` is the desktop app only. `--help` lists every flag, and any flag
overrides the preset or settings file it's combined with.

```powershell
img2dxf logo.png -o logo.dxf --width-mm 80
img2dxf photo.jpg --preset Photo --width-mm 120
img2dxf part.png --width-mm 60 --kerf 0.15
img2dxf scan.png --rotate -2.5 --crop 0.1,0.1,0.9,0.6
img2dxf part.png --width-mm 60 --tabs 4 --tab-mm 0.5
img2dxf part.png --copies 3x2 --bed 400x300
img2dxf logo.png -o logo.svg --width-mm 80
img2dxf tiny.png --width-mm 40 --detail 4
img2dxf art.png --width-mm 80 --no-straighten
```

Save and reuse settings:

```powershell
img2dxf logo.png -o logo.dxf --width-mm 80 --save-settings
img2dxf logo.png -o logo.dxf --settings logo.png.img2dxf.json
img2dxf --list-presets
```

From a source checkout, use `python -m img2dxf.cli` in place of `img2dxf`.

---

# Troubleshooting

| Problem | Fix |
|---|---|
| The export is empty | Try another mode, or tick *Trace light areas instead* if your artwork is light on dark |
| Imported at the wrong size | Set the import unit to mm; avoid R12 if your software supports newer DXF |
| Edges look jagged | Leave *Detail* on Auto or raise it |
| Curves look faceted | Lower *Straighten*, and keep arc fitting on |
| Machine is slow on the file | Raise *Tolerance* — watch the vertex count in the status bar |
| Small parts fall through the bed | Add *Tabs* |
| Parts come out slightly small | Set *Kerf* to *Outside* with your measured beam width |
| Drag-and-drop doesn't work | Use the **Open** button (drag-and-drop needs `tkinterdnd2` when running from source) |

---

# For developers

## Run from source

Requires Python 3.10 or newer.

```powershell
git clone https://github.com/aryansaraogi/dxfconvertor.git
cd dxfconvertor
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install .        # optional: adds the img2dxf command

.\.venv\Scripts\python.exe -m img2dxf          # launch the app
.\.venv\Scripts\python.exe -m img2dxf.cli --help
```

On macOS/Linux use `.venv/bin/python`. Tkinter must be available in your Python.

## Build the Windows executable

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe packaging\build.py     # produces dist\img2dxf.exe
```

## Run the tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```
