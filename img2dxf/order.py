"""Order the cut so the head travels less between paths.

Nothing about the geometry changes — only the sequence the entities are
written in, which is the order most controllers follow. Two rules do the work:
cut a shape's holes before its outline, and always move to whichever path
starts nearest to where the last one finished.
"""

from __future__ import annotations

import numpy as np

from .geometry import Path


def order_paths(paths: list[Path]) -> list[Path]:
    """Reorder ``paths`` to shorten the head's travel between cuts.

    Tone levels are kept together and in order. Mixing them would scatter one
    layer's geometry through another's, and layers are how the operator
    assigns power and speed — a shorter path is not worth shuffling that.
    """
    if len(paths) < 3:
        return paths

    ordered: list[Path] = []
    position = np.zeros(2)

    for level in sorted({path.level for path in paths}):
        group = [path for path in paths if path.level == level]
        arranged, position = _nearest_first(group, position)
        ordered.extend(arranged)

    return ordered


def _nearest_first(
    paths: list[Path], position: np.ndarray
) -> tuple[list[Path], np.ndarray]:
    """Greedy nearest-neighbour over one level's paths."""
    remaining = list(paths)
    ordered: list[Path] = []

    while remaining:
        index = min(
            range(len(remaining)),
            key=lambda i: _distance2(position, _entry_point(remaining[i])),
        )
        chosen = remaining.pop(index)
        ordered.append(chosen)
        position = _exit_point(chosen)

    return ordered, position


def _entry_point(path: Path) -> np.ndarray:
    """Where cutting this path begins.

    A path's holes are cut first — a part that is already free can shift, and
    a hole cut afterwards would be out of place — so the first hole, if there
    is one, is where the head actually arrives.
    """
    ring = path.holes[0] if path.holes else path.outer
    return ring[0] if len(ring) else np.zeros(2)


def _exit_point(path: Path) -> np.ndarray:
    """Where cutting this path ends: the outline, cut last, closes on itself."""
    ring = path.outer
    return ring[0] if len(ring) else np.zeros(2)


def _distance2(a: np.ndarray, b: np.ndarray) -> float:
    difference = a - b
    return float(difference @ difference)


def travel_length(paths: list[Path]) -> float:
    """Total distance travelled between paths, for reporting the improvement."""
    if not paths:
        return 0.0

    total = 0.0
    position = np.zeros(2)
    for path in paths:
        total += float(np.linalg.norm(position - _entry_point(path)))
        position = _exit_point(path)
    return total
