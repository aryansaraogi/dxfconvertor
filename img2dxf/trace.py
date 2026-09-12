"""Mask -> vector paths: contour extraction, hole nesting, simplification."""

from __future__ import annotations

import cv2
import numpy as np

from .geometry import Path
from .params import TraceParams

#: Below this a "ring" is a degenerate sliver, not a shape the laser can cut.
_MIN_RING_POINTS = 3


def trace_mask(
    mask: np.ndarray,
    params: TraceParams,
    *,
    px_per_mm: float,
    level: int = 0,
) -> tuple[list[Path], list[Path]]:
    """Extract simplified outlines from a single binary mask.

    Returns ``(kept, discarded)``. The discarded list holds contours dropped
    by the minimum-area filter, so the UI can show what the despeckle control
    is actually removing instead of silently swallowing real detail.

    ``RETR_CCOMP`` gives a two-level hierarchy — outer boundaries at the top,
    their holes as children — which is what lets the counter of an "O" stay
    open instead of being etched solid. ``CHAIN_APPROX_NONE`` keeps every
    boundary pixel so the simplification below is driven purely by the user's
    tolerance rather than by OpenCV's own reduction.
    """
    contours, hierarchy = cv2.findContours(
        mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE
    )
    if hierarchy is None or len(contours) == 0:
        return [], []

    hierarchy = hierarchy[0]
    epsilon_px = params.simplify_mm * px_per_mm
    min_area_px = params.min_area_mm2 * px_per_mm * px_per_mm

    paths: list[Path] = []
    discarded: list[Path] = []
    for index, contour in enumerate(contours):
        # A contour with a parent is a hole; it is collected via its parent.
        if hierarchy[index][3] != -1:
            continue
        if cv2.contourArea(contour) < min_area_px:
            dropped = _finish_ring(contour, epsilon_px, 0)
            if dropped is not None:
                discarded.append(Path(dropped, [], level))
            continue

        outer = _finish_ring(contour, epsilon_px, params.smooth, params.corner_deg)
        if outer is None:
            continue

        holes: list[np.ndarray] = []
        if params.keep_holes:
            child = hierarchy[index][2]
            while child != -1:
                if cv2.contourArea(contours[child]) >= min_area_px:
                    ring = _finish_ring(
                        contours[child], epsilon_px, params.smooth, params.corner_deg
                    )
                    if ring is not None:
                        holes.append(ring)
                child = hierarchy[child][0]

        paths.append(Path(outer, holes, level))

    return paths, discarded


def _finish_ring(
    contour: np.ndarray,
    epsilon_px: float,
    smooth_passes: int,
    corner_deg: float = 40.0,
) -> np.ndarray | None:
    """Simplify then optionally smooth one contour into an ``(N, 2)`` array."""
    if epsilon_px > 0:
        contour = cv2.approxPolyDP(contour, epsilon_px, True)

    ring = contour.reshape(-1, 2).astype(float)
    if len(ring) < _MIN_RING_POINTS:
        return None

    if smooth_passes:
        ring = smooth_ring(ring, smooth_passes, corner_deg)

    return ring


def smooth_ring(ring: np.ndarray, passes: int, corner_deg: float) -> np.ndarray:
    """Soften a ring's curves while holding its corners exactly.

    Chaikin applied to a whole ring cuts every corner equally: one pass pulls a
    true right angle in by a quarter of the adjoining edge, which is what
    destroys the corners of letters like L, T and E. So the sharp turns are
    pinned, and only the runs between them are smoothed.
    """
    corners = find_corners(ring, corner_deg)

    # No corners: it is all curve, so smooth it as one closed loop.
    if not corners.any():
        for _ in range(passes):
            ring = chaikin(ring)
        return ring

    indices = np.flatnonzero(corners)
    pieces = []
    for position, start in enumerate(indices):
        end = indices[(position + 1) % len(indices)]
        run = _slice_ring(ring, start, end)
        for _ in range(passes):
            run = chaikin_open(run)
        # The run ends on the next corner, which the next run re-emits.
        pieces.append(run[:-1])

    return np.vstack(pieces)


def find_corners(ring: np.ndarray, corner_deg: float) -> np.ndarray:
    """Boolean mask of the vertices whose turn is sharper than ``corner_deg``."""
    if corner_deg <= 0:
        return np.ones(len(ring), dtype=bool)

    incoming = ring - np.roll(ring, 1, axis=0)
    outgoing = np.roll(ring, -1, axis=0) - ring

    # Signed turn at each vertex, via the cross and dot products of the
    # incoming and outgoing edges. Zero-length edges give a zero turn, which
    # correctly reads as "not a corner".
    cross = incoming[:, 0] * outgoing[:, 1] - incoming[:, 1] * outgoing[:, 0]
    dot = (incoming * outgoing).sum(axis=1)
    turn = np.degrees(np.abs(np.arctan2(cross, dot)))

    return turn >= corner_deg


def _slice_ring(ring: np.ndarray, start: int, end: int) -> np.ndarray:
    """The run from ``start`` to ``end`` inclusive, wrapping if it has to."""
    if end > start:
        return ring[start : end + 1]
    return np.vstack([ring[start:], ring[: end + 1]])


def chaikin_open(points: np.ndarray) -> np.ndarray:
    """Chaikin over an open run, holding both endpoints exactly.

    The endpoints are the pinned corners, so they are emitted unchanged rather
    than being cut like interior vertices.
    """
    if len(points) < 3:
        return points

    first = points[:-1]
    second = points[1:]
    q = first * 0.75 + second * 0.25
    r = first * 0.25 + second * 0.75

    interleaved = np.empty((len(q) * 2, 2), dtype=float)
    interleaved[0::2] = q
    interleaved[1::2] = r

    return np.vstack([points[:1], interleaved[1:-1], points[-1:]])


def chaikin(ring: np.ndarray) -> np.ndarray:
    """One Chaikin corner-cutting pass over a closed ring.

    Each segment is replaced by its quarter and three-quarter points, which
    rounds off the staircase artefacts left by pixel-aligned contours. Vertex
    count doubles per pass, hence the cap of 3 passes in the UI.
    """
    nxt = np.roll(ring, -1, axis=0)
    q = ring * 0.75 + nxt * 0.25
    r = ring * 0.25 + nxt * 0.75
    out = np.empty((len(ring) * 2, 2), dtype=float)
    out[0::2] = q
    out[1::2] = r
    return out
