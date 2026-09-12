# img2dxf

Turn a PNG or JPEG into a DXF of contour outlines that a laser cutter/etcher can run.

The image is thresholded into a black-and-white mask, the mask's boundaries are traced
into closed polylines (holes included, so the middle of an "O" stays open), and the
result is written as a DXF scaled to real millimetres.

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
.\.venv\Scripts\python.exe -m img2dxf.cli scan.png --preset "Line art / scan" --dxf-version R12
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

## Getting a good result

- **Size first.** Set the width in mm before fiddling with anything else — the
  tolerance and minimum-area controls are in millimetres, so they shift meaning when
  the scale changes.
- **Watch the vertex count** in the status bar. A few thousand is fine; tens of
  thousands will crawl on the machine. Raise *Tolerance* to cut it down.
- **Speckles** in the output mean the mask is noisy: raise *Min area* to drop them, or
  *Remove specks* to clean the mask before tracing.
- **Broken thin lines**: raise *Bridge gaps*, or use `adaptive` mode.
- **Photos** rarely work as a single threshold. Use the Photo preset and 3–4 tone
  levels, then assign different power/speed to each `CUT_TONE_*` layer.

## Output details

- Coordinates are millimetres, Y pointing up, origin at the bottom-left (or centred
  on 0,0 with *Centre output on 0,0*).
- `$INSUNITS` is set to millimetres so LightBurn imports at the right scale.
- **R12 stores no units.** If you pick R12 for an older RDWorks/LaserCAD setup, set
  the import unit to mm yourself.
- Each posterize tone gets its own layer and colour (`CUT_TONE_0`, `CUT_TONE_1`, …)
  so colour-driven laser software can give each one different settings.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```
