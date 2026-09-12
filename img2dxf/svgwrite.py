"""Write traced paths as SVG, for LightBurn, Glowforge, Inkscape and previews.

The one thing to keep straight here is the Y axis. Image rows run downwards,
DXF runs upwards, and :func:`img2dxf.geometry.to_millimetres` flipped once to
get from the first to the second. SVG runs downwards again, so this module
flips back — otherwise every export comes out mirrored top to bottom, which is
easy to miss on symmetrical artwork and obvious on text.
"""

from __future__ import annotations

import math
from pathlib import Path as FsPath
from xml.sax.saxutils import escape

from .arcfit import realized_arc
from .geometry import Bounds, Path, bounds_of
from .params import TraceParams
from .tabs import open_segments

#: Stroke width in mm. Hairline-ish, so it never reads as a filled shape, and
#: cutters that honour stroke width still treat it as a cut line.
_STROKE_MM = 0.1

#: Same cycle as the DXF layer colours, so the two exports look alike.
_LEVEL_COLORS = (
    "#000000", "#d02020", "#20a020", "#2060d0",
    "#d0a000", "#00a0a0", "#a000a0", "#808080",
)

_MARGIN_MM = 1.0


def write_svg(
    paths: list[Path],
    out_path: str | FsPath,
    params: TraceParams,
    bounds: Bounds | None = None,
) -> FsPath:
    """Write ``paths`` (in millimetres) as an SVG at true physical size."""
    out_path = FsPath(out_path)
    out_path.write_text(build_svg(paths, params, bounds), encoding="utf-8")
    return out_path


def build_svg(
    paths: list[Path], params: TraceParams, bounds: Bounds | None = None
) -> str:
    """Render the SVG document as text. Split out so tests can skip disk."""
    params = params.normalized()
    box = bounds if bounds is not None else bounds_of(paths)

    if box is None:
        width = height = 1.0
        min_x = min_y = 0.0
    else:
        width = box.width + 2 * _MARGIN_MM
        height = box.height + 2 * _MARGIN_MM
        min_x = box.min_x - _MARGIN_MM
        min_y = box.min_y - _MARGIN_MM

    # Y in SVG grows downwards, so a point's distance from the *top* of the
    # bounding box is its Y here.
    def flip(y: float) -> float:
        return (min_y + height) - y

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        # width/height in mm make it open at true size; the viewBox keeps user
        # units equal to millimetres so coordinates read the same in both.
        f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        f'width="{width:.4f}mm" height="{height:.4f}mm" '
        f'viewBox="{min_x:.4f} {min_y:.4f} {width:.4f} {height:.4f}">',
        f"  <title>{escape(_title(params))}</title>",
    ]

    for position, level in enumerate(sorted({p.level for p in paths})):
        colour = _LEVEL_COLORS[position % len(_LEVEL_COLORS)]
        name = _layer_name(params, level, paths)
        lines.append(
            f'  <g id="{escape(name)}" fill="none" stroke="{colour}" '
            f'stroke-width="{_STROKE_MM}">'
        )
        for path in (p for p in paths if p.level == level):
            lines.extend(_render_path(path, params, flip))
        lines.append("  </g>")

    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def _title(params: TraceParams) -> str:
    return f"img2dxf export ({params.layer_name})"


def _layer_name(params: TraceParams, level: int, paths: list[Path]) -> str:
    levels = {p.level for p in paths}
    if len(levels) <= 1:
        return params.layer_name
    return f"{params.layer_name}_TONE_{level}"


def _render_path(path: Path, params: TraceParams, flip) -> list[str]:
    out = []
    for index, ring in enumerate(path.rings()):
        if len(ring) < 3:
            continue
        circle = path.circles.get(index)
        bulges = path.bulges.get(index)

        if params.tabs_enabled:
            segments = open_segments(
                ring, bulges, circle, params.tab_count, params.tab_mm
            )
            if segments is not None:
                out.extend(
                    f"    <path d=\"{_open_data(segment, flip)}\"/>"
                    for segment in segments
                )
                continue

        if circle is not None:
            cx, cy, radius = circle
            out.append(
                f'    <circle cx="{cx:.4f}" cy="{flip(cy):.4f}" r="{radius:.4f}"/>'
            )
            continue

        out.append(f'    <path d="{_closed_data(ring, bulges, flip)}"/>')
    return out


def _open_data(points, flip) -> str:
    parts = [f"M {points[0][0]:.4f} {flip(points[0][1]):.4f}"]
    parts.extend(f"L {x:.4f} {flip(y):.4f}" for x, y in points[1:])
    return " ".join(parts)


def _closed_data(ring, bulges, flip) -> str:
    """One closed subpath, using SVG arc commands where bulges were fitted."""
    has_bulges = bulges is not None and len(bulges) == len(ring)
    parts = [f"M {ring[0][0]:.4f} {flip(ring[0][1]):.4f}"]

    count = len(ring)
    for index in range(count):
        nxt = ring[(index + 1) % count]
        bulge = float(bulges[index]) if has_bulges else 0.0

        if bulge:
            command = _arc_command(ring[index], nxt, bulge, flip)
            if command is not None:
                parts.append(command)
                continue
        parts.append(f"L {nxt[0]:.4f} {flip(nxt[1]):.4f}")

    parts.append("Z")
    return " ".join(parts)


def _arc_command(first, last, bulge: float, flip) -> str | None:
    """An SVG elliptical-arc command matching a DXF bulge."""
    arc = realized_arc(first, last, bulge)
    if arc is None:
        return None
    _, radius, included = arc

    large = 1 if abs(included) > math.pi else 0
    # A counter-clockwise DXF sweep is clockwise once Y is flipped, so the
    # sweep flag is the inverse of the sign of the included angle.
    sweep = 0 if included > 0 else 1
    return (
        f"A {radius:.4f} {radius:.4f} 0 {large} {sweep} "
        f"{last[0]:.4f} {flip(last[1]):.4f}"
    )
