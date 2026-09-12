"""Flatten runs that are structurally straight lines.

After Douglas-Peucker every segment between two vertices is already straight,
so a stem that looks wavy is really several kept vertices zig-zagging along it:
the pixel staircase departs from the true edge by more than the user's
tolerance, so simplification is obliged to keep them all.

Recovering the straight line is therefore a separate judgement, made to its own
looser budget: a run that spans a useful distance and never strays far from its
own chord *is* a straight edge, whatever the pixels did. Its interior vertices
are dropped and its endpoints left exactly where they were, so a corner can
never be moved or invented.
"""

from __future__ import annotations

import numpy as np

from .arcfit import chord_and_bow
from .geometry import Path

#: A run needs at least this many vertices before flattening it changes
#: anything — two points are already a straight segment.
_MIN_RUN_POINTS = 3

#: The real discriminator. An absolute bow limit alone is not enough: a gentle
#: arc bows by chord^2 / 8r, so a plain tolerance test would happily flatten a
#: curve into facets. What separates the two is not how far a run strays but
#: *how it strays* — a pixel staircase zig-zags, so its turns cancel, while a
#: curve bends the same way throughout and they accumulate. Comparing the net
#: turn to the total turning makes that a pure shape question: it comes out
#: near 0 for a staircase and 1 for an arc, whatever the radius, the run
#: length or the scale.
_MAX_TURN_COHERENCE = 0.5

#: Below this there is no measurable turning at all, so the run is straight.
_FLAT_DEG = 1e-6

#: Coherence alone is not enough on real traced data. It compares net turning
#: to total turning, and a staircase adds so much total turning that a genuine
#: curve's coherence is diluted below the threshold — which chamfers the
#: shoulders of letters like O and G. Measuring how far the run actually bends
#: catches what coherence misses.
_MAX_BEND_DEG = 8.0


def effective_tolerance(
    straighten_mm: float, px_per_mm: float, detail_factor: int = 1
) -> float:
    """The bow budget actually used, floored at one source pixel.

    The ripple this removes *is* the pixel staircase, so it is about one
    source pixel tall. A budget below that cannot remove it — every run would
    break on the first step — so the floor is not a convenience, it is what
    makes the pass work at all. Supersampled pixels do not count: an
    interpolated pixel carries no information the original did not.
    """
    if px_per_mm <= 0:
        return straighten_mm
    return max(straighten_mm, detail_factor / px_per_mm)


def straighten_paths(
    paths: list[Path],
    straighten_mm: float,
    min_run_mm: float,
    px_per_mm: float = 0.0,
    detail_factor: int = 1,
) -> list[Path]:
    """Flatten the straight runs in every ring, in place.

    Rings carrying fitted arcs are skipped: arc fitting has already decided
    those are curves, and flattening them afterwards would undo it.
    """
    if straighten_mm <= 0 or min_run_mm <= 0:
        return paths

    straighten_mm = effective_tolerance(straighten_mm, px_per_mm, detail_factor)

    for path in paths:
        if path.circles or path.bulges:
            continue
        path.outer = straighten_ring(path.outer, straighten_mm, min_run_mm)
        path.holes = [
            straighten_ring(hole, straighten_mm, min_run_mm) for hole in path.holes
        ]

    return paths


def straighten_ring(
    ring: np.ndarray, straighten_mm: float, min_run_mm: float
) -> np.ndarray:
    """Drop the interior vertices of every straight run in a closed ring."""
    count = len(ring)
    if count < _MIN_RUN_POINTS + 1:
        return ring

    ring = ring.copy()
    keep = np.ones(count, dtype=bool)
    index = 0

    while index < count:
        end = _grow_run(ring, index, straighten_mm, min_run_mm)
        if end - index >= _MIN_RUN_POINTS - 1:
            # Drop the interior, and put the two endpoints on the line fitted
            # through the whole run. Leaving them untouched would be simpler
            # but worse: an endpoint that happens to sit on a peak of the
            # staircase drags the whole flattened edge off to one side, so the
            # result is straight but displaced.
            ring[index], ring[end] = _fit_endpoints(ring[index : end + 1])
            keep[index + 1 : end] = False
            index = end
        else:
            index += 1

    # Never reduce a ring below a closed shape.
    if keep.sum() < 3:
        return ring

    return ring[keep]


def _fit_endpoints(run: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The run's endpoints, projected onto the line best fitting all of it.

    A total-least-squares fit, so it behaves the same for a vertical edge as
    for a horizontal one — fitting y against x would blow up on the verticals
    that letter stems are mostly made of.
    """
    centre = run.mean(axis=0)
    centred = run - centre

    # The principal axis is the direction of greatest spread.
    _, _, vectors = np.linalg.svd(centred, full_matrices=False)
    direction = vectors[0]

    projections = centred @ direction
    return (
        centre + direction * projections[0],
        centre + direction * projections[-1],
    )


def _grow_run(
    ring: np.ndarray, start: int, straighten_mm: float, min_run_mm: float
) -> int:
    """The furthest index from ``start`` that still forms one straight run.

    Growth stops at the ring's end rather than wrapping: the seam would
    otherwise be flattened across the join, which is where the first and last
    vertex meet and where a corner most often sits.
    """
    count = len(ring)
    best = start
    end = start + 2

    while end < count:
        run = ring[start : end + 1]
        chord, bow = chord_and_bow(run)

        # Bow ends the run; the turn test only decides whether what has been
        # grown so far counts. Letting the turn test stop growth instead would
        # abort on the first noisy vertex, before the run is long enough to
        # show whether its wobble cancels or accumulates.
        if bow > straighten_mm:
            break
        if chord >= min_run_mm and is_straight(run):
            best = end
        end += 1

    return best


def turn_coherence(run: np.ndarray) -> float:
    """How consistently a run bends: 0 for a zig-zag, 1 for an arc.

    The net turn divided by the total turning. A staircase alternates, so its
    signed turns cancel while their magnitudes add, giving nearly 0. An arc
    turns the same way at every vertex, so the two are equal and it gives 1.
    """
    turns = _signed_turns(run)
    if len(turns) == 0:
        return 0.0

    total = np.abs(turns).sum()
    if total <= _FLAT_DEG:
        return 0.0  # no turning at all: already a straight line
    return float(abs(turns.sum()) / total)


def bend_deg(run: np.ndarray) -> float:
    """How far a run bends, in degrees, measured robustly.

    The angle between straight lines fitted to the run's two halves. Summing
    the per-vertex turns instead would be defeated by a staircase: its turns
    alternate and cancel only when there happens to be an even number of them,
    so an odd one leaves a whole step's worth of phantom bend. Fitting each
    half averages the steps away and asks the only question that matters —
    does the second half point somewhere else?
    """
    if len(run) < 4:
        return 0.0

    middle = len(run) // 2
    first = _direction(run[: middle + 1])
    second = _direction(run[middle:])
    if first is None or second is None:
        return 0.0

    # The fitted axes have no inherent sign, so compare them without one.
    alignment = min(1.0, abs(float(first @ second)))
    return float(np.degrees(np.arccos(alignment)))


def _direction(points: np.ndarray) -> np.ndarray | None:
    """The principal axis of a set of points, as a unit vector."""
    if len(points) < 2:
        return None
    centred = points - points.mean(axis=0)
    if not np.any(centred):
        return None
    _, _, vectors = np.linalg.svd(centred, full_matrices=False)
    return vectors[0]


def _signed_turns(run: np.ndarray) -> np.ndarray:
    """The signed turn at each interior vertex, in radians."""
    if len(run) < 3:
        return np.zeros(0)

    edges = np.diff(run, axis=0)
    incoming = edges[:-1]
    outgoing = edges[1:]

    cross = incoming[:, 0] * outgoing[:, 1] - incoming[:, 1] * outgoing[:, 0]
    dot = (incoming * outgoing).sum(axis=1)
    return np.arctan2(cross, dot)


def is_straight(run: np.ndarray) -> bool:
    """Whether a run wobbles in place rather than heading somewhere.

    Both halves are needed: coherence rejects clean curves of any radius, and
    the net-turn cap rejects noisy ones whose coherence has been diluted.
    """
    return (
        turn_coherence(run) <= _MAX_TURN_COHERENCE
        and bend_deg(run) <= _MAX_BEND_DEG
    )
