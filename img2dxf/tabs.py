"""Tabs (bridges): small uncut gaps that hold a cut part in the sheet.

Without them a part drops through the moment its outline closes, tilts in the
slot, and the beam finishes the pass across whatever is now underneath. Leaving
a few tenths of a millimetre uncut keeps it in place until it is snapped out.

This is applied when drawing and when writing, not inside the pipeline: a gap
partway along a ring cannot be carried by :class:`~img2dxf.geometry.Path`,
whose rings are closed by definition. Both :mod:`img2dxf.dxfwrite` and
:mod:`img2dxf.gui.preview` call :func:`split_ring`, so the preview shows
exactly the gaps that get written.
"""

from __future__ import annotations

import numpy as np

from .arcfit import circle_points, flatten_ring

#: Each remaining cut segment should be at least this many times the gap
#: width. Below that the "part" is mostly bridge and nothing is really cut.
_MIN_SEGMENT_RATIO = 2.0


def open_segments(
    points: np.ndarray,
    bulges: np.ndarray | None,
    circle: tuple[float, float, float] | None,
    count: int,
    gap_mm: float,
) -> list[np.ndarray] | None:
    """The cut segments for one ring, or ``None`` to leave it closed.

    The single entry point used by both the DXF writer and the preview, so
    what is drawn is exactly what is written.

    Arcs are flattened first. A gap partway along an arc cannot be expressed
    as a polyline bulge without splitting the arc itself, so tabs and arc
    output are mutually exclusive per ring — tabs win, because a part that
    drops through is a ruined job and a slightly heavier file is not.
    """
    if circle is not None:
        points = circle_points(circle)
    elif bulges is not None:
        points = flatten_ring(points, bulges)

    return split_ring(points, count, gap_mm)


def split_ring(
    points: np.ndarray, count: int, gap_mm: float
) -> list[np.ndarray] | None:
    """Cut ``count`` gaps of ``gap_mm`` into a closed ring.

    Returns the open segments that remain, or ``None`` when the ring should be
    left closed — which happens when it is too small to give up the material.
    Losing a small part entirely is worse than letting it drop through.

    Gaps are spaced evenly by **arc length**, not by vertex index: vertices
    bunch up on curves, so index spacing would cluster every tab on the
    fiddliest part of the outline.
    """
    if count < 1 or gap_mm <= 0 or len(points) < 3:
        return None

    closed = np.vstack([points, points[:1]])
    distances = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    cumulative = np.concatenate([[0.0], np.cumsum(distances)])
    perimeter = float(cumulative[-1])

    count = _feasible_count(perimeter, count, gap_mm)
    if count < 1:
        return None

    spacing = perimeter / count
    half = gap_mm / 2.0

    segments = []
    for index in range(count):
        # From the end of this gap to the start of the next one.
        start = index * spacing + half
        end = (index + 1) * spacing - half
        piece = _extract(closed, cumulative, start, end, perimeter)
        if piece is not None:
            segments.append(piece)

    return segments or None


def _feasible_count(perimeter: float, count: int, gap_mm: float) -> int:
    """How many tabs this ring can actually afford.

    Rather than refusing outright, the count is reduced until the segments
    between gaps are still worth cutting.
    """
    if perimeter <= 0:
        return 0
    affordable = int(perimeter // (gap_mm * (1.0 + _MIN_SEGMENT_RATIO)))
    return max(0, min(count, affordable))


def _extract(
    closed: np.ndarray,
    cumulative: np.ndarray,
    start: float,
    end: float,
    perimeter: float,
) -> np.ndarray | None:
    """The polyline running from arc length ``start`` to ``end``.

    Both ends are interpolated onto the exact distance, so a gap lands where
    it was asked for rather than snapping to the nearest vertex.
    """
    if end - start <= 0:
        return None

    points = [_point_at(closed, cumulative, start, perimeter)]

    # Every original vertex strictly inside the span, in order.
    for offset in (0.0, perimeter):
        for index, distance in enumerate(cumulative[:-1]):
            position = distance + offset
            if start < position < end:
                points.append(closed[index])

    points.append(_point_at(closed, cumulative, end, perimeter))
    return np.array(points, dtype=float)


def _point_at(
    closed: np.ndarray, cumulative: np.ndarray, distance: float, perimeter: float
) -> np.ndarray:
    """The point that lies ``distance`` along the ring, wrapping if needed."""
    distance = distance % perimeter
    index = int(np.searchsorted(cumulative, distance, side="right")) - 1
    index = max(0, min(index, len(closed) - 2))

    span = cumulative[index + 1] - cumulative[index]
    if span <= 0:
        return closed[index].astype(float)

    fraction = (distance - cumulative[index]) / span
    return closed[index] + (closed[index + 1] - closed[index]) * fraction


def total_length(segments: list[np.ndarray]) -> float:
    """Combined length of a set of open segments, for cut-length reporting."""
    return float(
        sum(
            np.linalg.norm(np.diff(segment, axis=0), axis=1).sum()
            for segment in segments
            if len(segment) > 1
        )
    )
