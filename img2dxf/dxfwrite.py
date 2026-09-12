"""Write traced paths out as a laser-ready DXF file."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path as FsPath

import ezdxf

from .geometry import Path
from .params import TraceParams
from .tabs import open_segments

#: ``$INSUNITS`` code for millimetres. Without it LightBurn has to guess the
#: unit on import, which is where "my 100 mm logo came in at 4 mm" comes from.
INSUNITS_MM = 4

#: ``$INSUNITS`` only exists from R2000 onwards. R12 files carry no unit at
#: all, so the operator must set millimetres in the importer themselves —
#: :func:`units_are_declared` lets the UI warn about that up front.
_INSUNITS_MIN_VERSION = "AC1015"

#: LWPOLYLINE arrived with R2000; R12 predates it and older Ruida/RDWorks
#: importers reject files that use it.
_LWPOLYLINE_MIN_VERSION = "AC1015"

#: ACI colours cycled across tone layers so colour-driven laser software can
#: map each tone to its own power/speed setting.
_LAYER_COLORS = (7, 1, 3, 5, 2, 4, 6, 8)


def write_dxf(
    paths: list[Path],
    out_path: str | FsPath,
    params: TraceParams,
) -> FsPath:
    """Write ``paths`` (already in millimetres) to ``out_path``.

    Returns the path written, so callers can report it without rebuilding it.
    """
    doc = build_document(paths, params)
    out_path = FsPath(out_path)
    doc.saveas(out_path)
    return out_path


@contextlib.contextmanager
def _muted_r12_units_warning(dxf_version: str):
    if units_are_declared(dxf_version):
        yield
        return
    logger = logging.getLogger("ezdxf")
    previous = logger.disabled
    logger.disabled = True
    try:
        yield
    finally:
        logger.disabled = previous


def units_are_declared(dxf_version: str) -> bool:
    """Whether the chosen DXF flavour can record "millimetres" in the file."""
    return dxf_version != "R12"


def build_document(paths: list[Path], params: TraceParams):
    """Build the in-memory DXF document. Split out so tests can skip disk."""
    params = params.normalized()

    # ezdxf.new() always assigns document units and logs a warning when the
    # target format cannot store them. That is expected for R12, so the noise
    # is muted here; callers learn the same thing from units_are_declared().
    with _muted_r12_units_warning(params.dxf_version):
        doc = ezdxf.new(
            dxfversion=params.dxf_version, setup=True, units=INSUNITS_MM
        )
    doc.header["$MEASUREMENT"] = 1  # metric, for the hatch/linetype tables

    levels = sorted({p.level for p in paths})
    layer_for = _create_layers(doc, levels, params.layer_name)

    msp = doc.modelspace()
    use_lwpolyline = doc.dxfversion >= _LWPOLYLINE_MIN_VERSION

    for path in paths:
        attribs = {"layer": layer_for[path.level]}
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
                    for segment in segments:
                        _add_open(msp, segment, use_lwpolyline, attribs)
                    continue
                # Too small for tabs: fall through and write it closed.

            if circle is not None:
                cx, cy, radius = circle
                msp.add_circle((cx, cy), radius, dxfattribs=attribs)
                continue
            _add_ring(msp, ring, bulges, use_lwpolyline, attribs)

    return doc


def _add_open(msp, points, use_lwpolyline: bool, attribs: dict) -> None:
    """Write one open segment - a cut that stops short, leaving a bridge."""
    if len(points) < 2:
        return
    coords = [(float(x), float(y)) for x, y in points]
    if use_lwpolyline:
        msp.add_lwpolyline(coords, format="xy", close=False, dxfattribs=attribs)
    else:
        msp.add_polyline2d(coords, close=False, dxfattribs=attribs)


def _add_ring(msp, ring, bulges, use_lwpolyline: bool, attribs: dict) -> None:
    """Write one closed ring, carrying bulges when arcs were fitted.

    Bulges ride on the polyline itself rather than becoming separate ARC
    entities, so the ring stays a single closed contour with no seams for the
    controller to lift over between segments.
    """
    has_bulges = bulges is not None and len(bulges) == len(ring)

    if use_lwpolyline:
        if has_bulges:
            points = [
                (float(x), float(y), float(b)) for (x, y), b in zip(ring, bulges)
            ]
            msp.add_lwpolyline(points, format="xyb", close=True, dxfattribs=attribs)
        else:
            points = [(float(x), float(y)) for x, y in ring]
            msp.add_lwpolyline(points, format="xy", close=True, dxfattribs=attribs)
        return

    # R12: bulge is a per-vertex DXF attribute rather than a point format.
    polyline = msp.add_polyline2d(
        [(float(x), float(y)) for x, y in ring], close=True, dxfattribs=attribs
    )
    if has_bulges:
        for vertex, bulge in zip(polyline.vertices, bulges):
            if bulge:
                vertex.dxf.bulge = float(bulge)


def _create_layers(doc, levels: list[int], base_name: str) -> dict[int, str]:
    """One layer per tone level, or a single layer when there is only one.

    Multiple levels only happen in posterize mode, where keeping tones apart
    is the whole point — you want the darkest tone burned hardest.
    """
    mapping: dict[int, str] = {}
    single = len(levels) <= 1

    for position, level in enumerate(levels):
        name = base_name if single else f"{base_name}_TONE_{level}"
        color = _LAYER_COLORS[position % len(_LAYER_COLORS)]
        if name not in doc.layers:
            doc.layers.add(name=name, color=color)
        mapping[level] = name

    # A file with no geometry should still carry the layer, so the operator
    # opens it and sees an empty job rather than a broken one.
    if not mapping and base_name not in doc.layers:
        doc.layers.add(name=base_name, color=_LAYER_COLORS[0])

    return mapping
