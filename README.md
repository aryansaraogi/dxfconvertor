# img2dxf

Turn a PNG or JPEG into a DXF of contour outlines that a laser cutter/etcher can run.

The image is thresholded into a black-and-white mask, the mask's boundaries are traced
into closed polylines (holes included, so the middle of an "O" stays open), circular
runs are fitted back to true arcs, and the result is written as a DXF scaled to real
millimetres — optionally offset to compensate for the width of your beam.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Use it

**GUI** — load an image, adjust, watch the preview, export:

```powershell
.\.venv\Scripts\python.exe -m img2dxf
```

**Command line** — same engine, scriptable:

```powershell
.\.venv\Scripts\python.exe -m img2dxf.cli logo.png -o logo.dxf --width-mm 80
.\.venv\Scripts\python.exe -m img2dxf.cli photo.jpg --preset Photo --width-mm 120
.\.venv\Scripts\python.exe -m img2dxf.cli part.png --width-mm 60 --kerf 0.15
.\.venv\Scripts\python.exe -m img2dxf.cli scan.png --rotate -2.5 --crop 0.1,0.1,0.9,0.6
.\.venv\Scripts\python.exe -m img2dxf.cli part.png --width-mm 60 --tabs 4 --tab-mm 0.5
.\.venv\Scripts\python.exe -m img2dxf.cli part.png --copies 3x2 --bed 400x300
.\.venv\Scripts\python.exe -m img2dxf.cli logo.png -o logo.svg --width-mm 80
```

`--help` lists every flag. Any flag overrides the preset it is combined with.

## Tracing modes

| Mode | Use it for |
|---|---|
| `otsu` | logos, clipart, text — picks the threshold for you |
| `fixed` | when Otsu picks the wrong level; you set 0–255 yourself |
| `adaptive` | scans and photos of paper with uneven lighting |
| `posterize` | photographs — splits tones into bands, one DXF layer each |
| `edges` | outlines only, no solid fills |

Presets (`Logo / clipart`, `Photo`, `Line art / scan`, `Edge outline`) set sensible
starting values for each.

## Kerf compensation

A laser removes material as it cuts. Cut exactly on the line and the part comes out a
beam-width undersized, with holes a beam-width oversized. Set **Kerf** to the width your
machine actually cuts (typically 0.1–0.2 mm) and pick a side:

- **outside** — cut outside the line, so the *part* keeps its drawn size. The usual
  choice when the piece you keep is the one being cut out.
- **inside** — cut inside the line, so the *hole* keeps its drawn size. Use when the
  hole is the feature that has to fit something.

Outlines and holes are offset in opposite directions automatically. A feature thinner
than the kerf disappears, because the beam would consume it entirely.

## Tabs (bridges)

A closed cut releases the part the moment it finishes: it drops, tilts in the slot,
and the beam finishes the pass across whatever is now underneath. Set **Tabs per path**
to leave that many uncut bridges, and **Tab width** to how wide each one is (0.3–1 mm
is typical). Snap the parts out afterwards.

Tabs and arc fitting cannot share a path — a gap partway along an arc cannot be
expressed as a polyline bulge — so tabbed paths are written as plain open polylines.
Everything else keeps its arcs.

Rings too small to give up the material are left closed rather than lost, and a
requested tab count is quietly reduced if the path cannot afford it.

## Layout and the bed

Enter your machine's **Bed** size and the preview draws it as a dashed outline; it
turns red, along with the status bar, when the job will not fit. Leave it at 0 to
disable the check.

**Copies across/down** tiles the job on a grid to fill a sheet in one run, with **Tile
gap** between copies. The fit check measures the tiled result, not one copy.

## Setting the size from something you can measure

Rather than guessing at a width: tick **Measure**, drag across a feature whose real
size you know, then press **Set size…** and type that size. The whole job is rescaled
so the feature comes out exactly right.

## Image adjustments

For photos and faint scans that threshold badly: **Auto levels** stretches the tonal
range to fill 0–255 (ignoring stray specks, so one dust mote cannot define black),
then **Brightness**, **Contrast** (pivoting about mid-grey, so it does not also
brighten) and **Gamma** for the midtones. **Sharpen** and **Blur** undo one another —
use one or the other.

## Framing

**Rotate** straightens a crooked scan (or use the ±90° buttons). Tick **Crop** and drag
a box on the preview to keep just part of the image; crops compose, so you can narrow
down in steps. Both apply before anything else, so "80 mm wide" always means the width
of the piece you can see.

## The preview

- Scroll to **zoom**, drag to **pan**, `Fit` (or `F`) to reset.
- **Measure** — tick it and drag between two points to read the distance in mm. The
  quickest way to check scale before committing a job.
- **Show dropped** — tints the contours the *Min area* filter removed, in amber, so you
  can see whether it is eating real detail or only specks.
- Views: Original, Mask, Vectors, Overlay.
- Drag an image file onto the window to open it (needs `tkinterdnd2`); recent files are
  in the toolbar.

## Getting a good result

- **Size first.** Set the width in mm before fiddling with anything else — the
  tolerance and minimum-area controls are in millimetres, so they shift meaning when
  the scale changes.
- **Watch the vertex count** in the status bar. A few thousand is fine; tens of
  thousands will crawl on the machine. Raise *Tolerance*, or leave arc fitting on —
  it typically halves the count on curved artwork.
- **Speckles** in the output mean the mask is noisy: raise *Min area* to drop them, or
  *Remove specks* to clean the mask before tracing.
- **Broken thin lines**: raise *Bridge gaps*, or use `adaptive` mode.
- **Photos** rarely work as a single threshold. Use the Photo preset and 3–4 tone
  levels, then assign different power/speed to each `CUT_TONE_*` layer.

## Output formats

Export to **DXF** or **SVG** — the GUI picks by the extension you choose, and the CLI
by the output extension or `--format`. The SVG opens at true physical size (mm), keeps
fitted circles and arcs as `<circle>` and arc commands, and puts each tone on its own
`<g>` group.

## Output details

- Coordinates are millimetres, Y pointing up, origin at the bottom-left (or centred
  on 0,0 with *Centre output on 0,0*).
- `$INSUNITS` is set to millimetres so LightBurn imports at the right scale.
- **R12 stores no units.** If you pick R12 for an older RDWorks/LaserCAD setup, set
  the import unit to mm yourself.
- Circular rings are written as `CIRCLE` entities and curved runs as polyline bulges,
  both within one source pixel of the traced outline. Switch it off with `--no-arcs`
  if your controller dislikes arcs.
- Each posterize tone gets its own layer and colour (`CUT_TONE_0`, `CUT_TONE_1`, …)
  so colour-driven laser software can give each one different settings.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```
