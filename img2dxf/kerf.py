"""Kerf compensation: offset paths by half the beam width.

A laser removes material as it cuts. Cut exactly on the line and the part comes
out a beam-width undersized and its holes a beam-width oversized. Offsetting
every outline outward by half the kerf — and every hole inward by the same —
makes the finished part measure what was drawn.

Runs in millimetre space, after :func:`img2dxf.geometry.to_millimetres`.
"""

from __future__ import annotations

import numpy as np
import pyclipper

from .geometry import Path

#: Clipper works in integers; 1000 units per mm gives micron precision, which
#: is three orders finer than any laser's positioning accuracy.
_SCALE = 1000.0

#: Rings that survive an offset but enclose less than this are numerical
#: crumbs, not features the machine could cut.
_MIN_AREA_MM2 = 1e-4


def offset_paths(paths: list[Path], kerf_mm: float, side: str) -> list[Path]:
    """Return ``paths`` offset by half of ``kerf_mm``.

    ``side="outside"`` cuts outside the line, so the part keeps its drawn size
    — the usual choice. ``side="inside"`` cuts inside it, so a *hole* keeps its
    drawn size. ``side="none"`` (or a zero kerf) returns the paths untouched.

    Offsetting can merge shapes that grow into each other, split a waisted
    shape in two, or dissolve a sliver thinner than the kerf entirely, so the
    outer/hole nesting is rebuilt from the result rather than carried over.
    """
    if side == "none" or kerf_mm <= 0 or not paths:
        return paths

    delta = (kerf_mm / 2.0) * (-1.0 if side == "inside" else 1.0)

    # Offset each tone level independently: merging across levels would put
    # one shape's geometry on another layer.
    result: list[Path] = []
    for level in sorted({p.level for p in paths}):
        group = [p for p in paths if p.level == level]
        result.extend(_offset_group(group, delta, level))
    return result


def _offset_group(paths: list[Path], delta: float, level: int) -> list[Path]:
    offset = pyclipper.PyclipperOffset()
    added = False

    for path in paths:
        # Clipper derives grow-vs-shrink from winding direction, so the
        # orientation convention has to be enforced rather than assumed:
        # counter-clockwise outlines grow, clockwise holes shrink, both from
        # the same positive delta.
        if _add_ring(offset, path.outer, counter_clockwise=True):
            added = True
        for hole in path.holes:
            _add_ring(offset, hole, counter_clockwise=False)

    if not added:
        return []

    try:
        rings = offset.Execute(delta * _SCALE)
    except pyclipper.ClipperException:
        # A degenerate ring can abort the whole batch; leaving the paths
        # uncompensated is better than dropping the job's geometry.
        return paths

    return _rebuild(rings, level)


def _add_ring(offset, ring: np.ndarray, *, counter_clockwise: bool) -> bool:
    if len(ring) < 3:
        return False
    scaled = [(int(round(x * _SCALE)), int(round(y * _SCALE))) for x, y in ring]
    if pyclipper.Orientation(scaled) != counter_clockwise:
        scaled.reverse()
    offset.AddPath(scaled, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
    return True


def _rebuild(rings: list, level: int) -> list[Path]:
    """Reassemble Clipper's flat output into outlines with their holes.

    Clipper marks outlines counter-clockwise and holes clockwise. Each hole is
    assigned to the smallest outline that contains it, which is the correct
    parent even when shapes nest several deep.
    """
    outers: list[tuple[float, list]] = []
    holes: list[list] = []

    for ring in rings:
        if len(ring) < 3:
            continue
        area = abs(pyclipper.Area(ring)) / (_SCALE * _SCALE)
        if area < _MIN_AREA_MM2:
            continue
        if pyclipper.Orientation(ring):
            outers.append((area, ring))
        else:
            holes.append(ring)

    # Smallest first, so a hole lands in the tightest outline containing it.
    outers.sort(key=lambda item: item[0])
    built = [Path(_to_array(ring), [], level) for _, ring in outers]

    for hole in holes:
        probe = hole[0]
        for index, (_, ring) in enumerate(outers):
            if pyclipper.PointInPolygon(probe, ring) != 0:
                built[index].holes.append(_to_array(hole))
                break

    return built


def _to_array(ring: list) -> np.ndarray:
    return np.array([(x / _SCALE, y / _SCALE) for x, y in ring], dtype=float)
