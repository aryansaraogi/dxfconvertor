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

#: A run whose radius dwarfs its own chord is a straight line dressed up as a
#: circle; refuse the fit rather than emit a near-zero bulge.
_MAX_RADIUS_FACTOR = 100.0

#: How far short of a full turn a closed ring may fall and still count as a
#: circle (radians). Small, because the ring is measured closed.
_FULL_TURN_SLACK = 0.05


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

    # Probe the polyline, not just its corners. Every regular polygon has its
    # vertices equidistant from its centre, so a square's four corners fit a
    # circle perfectly; only the middles of its sides reveal that it is not
    # one.
    probes = np.vstack([points, (points + np.roll(points, -1, axis=0)) / 2.0])
    deviation = np.abs(np.hypot(probes[:, 0] - cx, probes[:, 1] - cy) - radius)
    if deviation.max() > tol:
        return None

    # Close the ring before measuring, so the step from the last point back
    # to the first is counted. Simplification can leave that final gap large,
    # and without it a genuine circle falls just short of a full turn and gets
    # rejected — then fitted as a 350-degree arc plus a chord instead.
    closed = np.vstack([points, points[:1]])
    angles = np.arctan2(closed[:, 1] - cy, closed[:, 0] - cx)
    if _total_sweep(angles) < 2 * math.pi - _FULL_TURN_SLACK:
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
    """Whether one circle passes within ``tol`` of every point in ``window``.

    Deliberately permissive about how *curved* the run is: the seed window is
    only a few points long, and a genuine arc barely bows over that distance.
    Whether the finished run curves enough to be worth an arc at all is
    decided once, at acceptance, in :func:`_arc_bulge`.
    """
    chord, _ = chord_and_bow(window)
    if chord < tol:
        return False

    fit = _algebraic_circle(window)
    if fit is None:
        return False
    cx, cy, radius = fit
    if radius <= 0 or radius > chord * _MAX_RADIUS_FACTOR:
        return False

    # Test the polyline, not just its corners. Simplification leaves a long
    # straight edge as two points, and a large circle passes through any two
    # points — so checking vertices alone lets an arc swallow a straight side
    # and run on into the next corner. Segment midpoints expose that: the
    # middle of a long chord sits far off the circle it supposedly lies on.
    probes = np.vstack([window, (window[:-1] + window[1:]) / 2.0])
    deviation = np.abs(np.hypot(probes[:, 0] - cx, probes[:, 1] - cy) - radius)
    return bool(deviation.max() <= tol)


def chord_and_bow(window: np.ndarray) -> tuple[float, float]:
    """Length of the run's chord, and how far it bows away from that chord.

    Shared with :mod:`img2dxf.straighten`, which asks the same question of a
    run for a different reason: whether it is straight enough to flatten.
    """
    start = window[0]
    span = window[-1] - start
    chord = float(math.hypot(span[0], span[1]))
    if chord <= 0:
        return 0.0, 0.0
    offsets = window - start
    cross = np.abs(offsets[:, 0] * span[1] - offsets[:, 1] * span[0])
    return chord, float(cross.max() / chord)


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
    chord, bow = chord_and_bow(points[start : end + 1])
    if chord < tol:
        return None

    # A run that barely leaves its own chord is a straight line; an arc here
    # would carry a near-zero bulge and buy nothing.
    if bow <= tol:
        return None

    # Derive the sweep from every point in the run, unwrapped. Judging
    # direction from a single midpoint gets the sign wrong whenever that point
    # is not where it is assumed to be, and an arc with the right endpoints but
    # the wrong direction takes the long way round the circle.
    sweep = _signed_sweep(points[start : end + 1], cx, cy)
    if abs(sweep) < 1e-6 or abs(sweep) >= 2 * math.pi:
        return None

    # bulge = tan(sweep / 4) is the DXF definition; the sign carries the
    # direction, positive being counter-clockwise.
    bulge = math.tan(sweep / 4.0)

    # Final gate: measure against the arc that will actually be written, not
    # against the least-squares circle. DXF rebuilds an arc through its two
    # endpoints, and those endpoints carry their own fitting error, so the
    # realized arc is a slightly different circle from the fitted one — and it
    # is the realized one the machine follows.
    if _arc_error(points[start : end + 1], bulge) > tol:
        return None

    return bulge


def realized_arc(
    first: np.ndarray, last: np.ndarray, bulge: float
) -> tuple[np.ndarray, float, float] | None:
    """Rebuild the arc a DXF reader derives from two points and a bulge."""
    included = 4.0 * math.atan(bulge)
    span = last - first
    chord = float(math.hypot(span[0], span[1]))
    half = math.sin(included / 2.0)
    if chord <= 0 or abs(half) < 1e-12:
        return None

    radius = chord / (2.0 * half)
    direction = span / chord
    normal = np.array([-direction[1], direction[0]])
    centre = (first + last) / 2.0 + normal * (radius * math.cos(included / 2.0))
    return centre, abs(radius), included


def _arc_error(run: np.ndarray, bulge: float) -> float:
    """Greatest distance from any point of ``run`` to the arc replacing it.

    A point whose angle falls within the arc's span is off by its radial
    error; one outside the span is off by its distance to the nearer endpoint,
    because that is where the arc stops.
    """
    arc = realized_arc(run[0], run[-1], bulge)
    if arc is None:
        return float("inf")
    centre, radius, included = arc

    offsets = run - centre
    angles = np.arctan2(offsets[:, 1], offsets[:, 0])
    radial = np.abs(np.hypot(offsets[:, 0], offsets[:, 1]) - radius)

    # Progress of each point around the arc, measured in the sweep direction.
    travelled = ((angles - angles[0]) * (1.0 if included >= 0 else -1.0)) % (
        2 * math.pi
    )
    inside = travelled <= abs(included) + 1e-9

    to_ends = np.minimum(
        np.linalg.norm(run - run[0], axis=1),
        np.linalg.norm(run - run[-1], axis=1),
    )
    return float(np.where(inside, radial, to_ends).max())


def _signed_sweep(run: np.ndarray, cx: float, cy: float) -> float:
    """Angle swept from the first point to the last, about ``(cx, cy)``.

    Positive is counter-clockwise. Unwrapping keeps the result continuous
    across the +/-pi seam, so the magnitude is the true sweep rather than its
    wrapped remainder.
    """
    angles = np.unwrap(np.arctan2(run[:, 1] - cy, run[:, 0] - cx))
    return float(angles[-1] - angles[0])


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


def flatten_ring(
    points: np.ndarray, bulges: np.ndarray | None, per_arc: int = 24
) -> np.ndarray:
    """Expand a bulge polyline into plain points, for drawing.

    The preview has to show the curve a DXF reader will draw, not the handful
    of vertices that encode it, or an arc-fitted shape would appear as a
    coarse polygon on screen while exporting correctly.
    """
    if bulges is None or len(bulges) != len(points):
        return points

    pieces = []
    count = len(points)
    for index, bulge in enumerate(bulges):
        first = points[index]
        last = points[(index + 1) % count]
        if not bulge:
            pieces.append(first[None, :])
            continue
        arc = realized_arc(first, last, float(bulge))
        if arc is None:
            pieces.append(first[None, :])
            continue
        centre, radius, included = arc
        start_angle = math.atan2(first[1] - centre[1], first[0] - centre[0])
        angles = np.linspace(start_angle, start_angle + included, per_arc)
        pieces.append(
            np.column_stack(
                [centre[0] + radius * np.cos(angles), centre[1] + radius * np.sin(angles)]
            )
        )
    return np.vstack(pieces)


def circle_points(circle: tuple[float, float, float], count: int = 96) -> np.ndarray:
    """Sample a fitted circle, for drawing."""
    cx, cy, radius = circle
    angles = np.linspace(0, 2 * math.pi, count, endpoint=False)
    return np.column_stack([cx + radius * np.cos(angles), cy + radius * np.sin(angles)])
