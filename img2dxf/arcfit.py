"""Recover arcs and circles from traced polylines.

A traced circle arrives as a few hundred short straight segments. Controllers
stutter on those, files bloat, and the burn shows faceting. Fitting true arcs
back onto the points fixes all three.

Arcs are emitted as polyline *bulges* rather than separate ARC entities: a
bulge keeps the ring one closed polyline, so there are no hairline seams
between segments, and both LWPOLYLINE and R12 POLYLINE carry them.
"""

from __future__ import annotations

import math

import numpy as np

#: Shorter runs than this are cheaper and safer to leave as straight lines.
_MIN_ARC_POINTS = 5

#: A circle fit is meaningless once the radius approaches infinity; beyond
#: this multiple of the ring's own size the points are effectively collinear.
_MAX_RADIUS_FACTOR = 1000.0


def fit_circle(points: np.ndarray, tol: float) -> tuple[float, float, float] | None:
    """Fit a circle through a closed ring, or return ``None``.

    Succeeds only when every point lies within ``tol`` of the fitted circle
    *and* the ring actually closes a full turn — an arc-shaped ring must not be
    mistaken for a complete circle.
    """
    fit = _algebraic_circle(points)
    if fit is None:
        return None

    cx, cy, radius = fit
    if radius <= 0:
        return None

    deviation = np.abs(np.hypot(points[:, 0] - cx, points[:, 1] - cy) - radius)
    if deviation.max() > tol:
        return None

    angles = np.arctan2(points[:, 1] - cy, points[:, 0] - cx)
    if _total_sweep(angles) < 2 * math.pi - 0.2:
        return None

    return cx, cy, radius


def fit_bulges(
    points: np.ndarray, tol: float
) -> tuple[np.ndarray, np.ndarray] | None:
    """Fit arcs along a closed ring.

    Returns ``(vertices, bulges)`` where each bulge describes the segment
    leaving its vertex — 0 for a straight line — and the vertices an arc
    replaced have been dropped. Returns ``None`` when nothing was curved
    enough to be worth an arc, so the caller keeps the plain polyline.
    """
    count = len(points)
    if count < _MIN_ARC_POINTS:
        return None

    vertices: list[np.ndarray] = []
    bulges: list[float] = []
    index = 0
    found = False

    while index < count:
        end = _grow_arc(points, index, tol)
        bulge = (
            _arc_bulge(points, index, end, tol)
            if end - index >= _MIN_ARC_POINTS - 1
            else None
        )
        vertices.append(points[index])
        if bulge is None:
            bulges.append(0.0)
            index += 1
        else:
            # Everything between index and end is described by the arc now.
            bulges.append(bulge)
            found = True
            index = end

    if not found:
        return None

    return np.array(vertices, dtype=float), np.array(bulges, dtype=float)


def _grow_arc(points: np.ndarray, start: int, tol: float) -> int:
    """Extend a run from ``start`` while a single circle still fits it."""
    count = len(points)
    end = min(start + _MIN_ARC_POINTS - 1, count - 1)
    best = start

    while end < count:
        if _fits_circle(points[start : end + 1], tol):
            best = end
            end += 1
        else:
            break

    return best


def _fits_circle(window: np.ndarray, tol: float) -> bool:
    fit = _algebraic_circle(window)
    if fit is None:
        return False
    cx, cy, radius = fit

    extent = max(
        window[:, 0].max() - window[:, 0].min(),
        window[:, 1].max() - window[:, 1].min(),
    )
    # An enormous radius means "straight line"; a bulge would add nothing.
    if radius <= 0 or radius > max(extent, tol) * _MAX_RADIUS_FACTOR:
        return False

    deviation = np.abs(np.hypot(window[:, 0] - cx, window[:, 1] - cy) - radius)
    return bool(deviation.max() <= tol)


def _arc_bulge(
    points: np.ndarray, start: int, end: int, tol: float
) -> float | None:
    """The bulge for the arc spanning ``start..end``, or ``None`` if unusable."""
    fit = _algebraic_circle(points[start : end + 1])
    if fit is None:
        return None
    cx, cy, radius = fit
    if radius <= 0:
        return None

    first = points[start]
    last = points[end]
    chord = math.hypot(last[0] - first[0], last[1] - first[1])
    if chord < tol:
        return None

    mid = points[(start + end) // 2]
    sweep = _sweep_through(
        math.atan2(first[1] - cy, first[0] - cx),
        math.atan2(mid[1] - cy, mid[0] - cx),
        math.atan2(last[1] - cy, last[0] - cx),
    )
    if abs(sweep) < 1e-6 or abs(sweep) >= 2 * math.pi:
        return None

    # bulge = tan(sweep / 4) is the DXF definition; the sign carries the
    # direction, positive being counter-clockwise.
    return math.tan(sweep / 4.0)


def _sweep_through(start: float, middle: float, end: float) -> float:
    """Signed sweep from ``start`` to ``end`` passing through ``middle``."""
    forward = _normalize(end - start)
    to_mid = _normalize(middle - start)
    if to_mid <= forward:
        return forward
    return forward - 2 * math.pi


def _normalize(angle: float) -> float:
    """Wrap an angle into ``[0, 2pi)``."""
    return angle % (2 * math.pi)


def _total_sweep(angles: np.ndarray) -> float:
    """Total turning of a sequence of angles, unwrapped."""
    return float(abs(np.sum(np.diff(np.unwrap(angles)))))


def _algebraic_circle(points: np.ndarray) -> tuple[float, float, float] | None:
    """Kasa least-squares circle fit.

    Solves the linear system behind ``x^2 + y^2 + Ax + By + C = 0``, which is
    fast and stable enough for boundary points that are already near-circular.
    """
    if len(points) < 3:
        return None

    x = points[:, 0]
    y = points[:, 1]
    design = np.column_stack([x, y, np.ones(len(points))])
    rhs = x * x + y * y

    try:
        solution, *_ = np.linalg.lstsq(design, rhs, rcond=None)
    except np.linalg.LinAlgError:
        return None

    cx = solution[0] / 2.0
    cy = solution[1] / 2.0
    under_root = solution[2] + cx * cx + cy * cy
    if under_root <= 0 or not np.isfinite(under_root):
        return None

    return float(cx), float(cy), float(math.sqrt(under_root))
