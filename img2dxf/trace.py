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

        outer = _finish_ring(contour, epsilon_px, params.smooth)
        if outer is None:
            continue

        holes: list[np.ndarray] = []
        if params.keep_holes:
            child = hierarchy[index][2]
            while child != -1:
                if cv2.contourArea(contours[child]) >= min_area_px:
                    ring = _finish_ring(contours[child], epsilon_px, params.smooth)
                    if ring is not None:
                        holes.append(ring)
                child = hierarchy[child][0]

        paths.append(Path(outer, holes, level))

    return paths, discarded


def _finish_ring(
    contour: np.ndarray, epsilon_px: float, smooth_passes: int
) -> np.ndarray | None:
    """Simplify then optionally smooth one contour into an ``(N, 2)`` array."""
    if epsilon_px > 0:
        contour = cv2.approxPolyDP(contour, epsilon_px, True)

    ring = contour.reshape(-1, 2).astype(float)
    if len(ring) < _MIN_RING_POINTS:
        return None

    for _ in range(smooth_passes):
        ring = chaikin(ring)

    return ring


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
