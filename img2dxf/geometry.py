"""Path containers and the pixel -> millimetre transform.

Getting this wrong is the classic way to send a 30 mm logo to the laser as a
3 mm one, so the transform lives alone here and is covered directly by tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

MM_PER_INCH = 25.4


@dataclass(slots=True)
class Path:
    """One closed outline plus the holes punched out of it.

    ``outer`` and each entry of ``holes`` is an ``(N, 2)`` float array. Points
    are in pixel space until :func:`to_millimetres` converts them.
    """

    outer: np.ndarray
    holes: list[np.ndarray] = field(default_factory=list)
    level: int = 0
    """Tone level index, used to pick the DXF layer in posterize mode."""

    def rings(self):
        """Yield the outer ring followed by every hole."""
        yield self.outer
        yield from self.holes

    @property
    def vertex_count(self) -> int:
        return sum(len(ring) for ring in self.rings())


@dataclass(slots=True)
class Bounds:
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y


def bounds_of(paths: list[Path]) -> Bounds | None:
    """Axis-aligned bounding box over every ring, or ``None`` if empty."""
    rings = [ring for path in paths for ring in path.rings() if len(ring)]
    if not rings:
        return None
    stacked = np.concatenate(rings, axis=0)
    return Bounds(
        float(stacked[:, 0].min()), float(stacked[:, 1].min()),
        float(stacked[:, 0].max()), float(stacked[:, 1].max()),
    )


def pixels_per_mm(
    image_width_px: int,
    image_height_px: int,
    *,
    size_mode: str,
    width_mm: float,
    height_mm: float | None,
    dpi: float,
) -> float:
    """Resolve the sizing controls down to a single scale factor.

    In ``"fit"`` mode the image is scaled so it spans ``width_mm`` (or
    ``height_mm`` when that is given, which then wins). In ``"dpi"`` mode the
    scale comes from the image's own resolution.
    """
    if size_mode == "dpi":
        return float(dpi) / MM_PER_INCH
    if height_mm:
        return image_height_px / float(height_mm)
    return image_width_px / float(width_mm)


def to_millimetres(
    paths: list[Path],
    *,
    image_height_px: int,
    px_per_mm: float,
    origin: str = "bottom-left",
) -> list[Path]:
    """Convert pixel-space paths into DXF millimetre space.

    Image rows run downwards from the top-left; DXF Y runs upwards from the
    bottom-left, so Y is flipped here. With ``origin="center"`` the result is
    then recentred on 0,0, which is what most laser beds expect for jigs.
    """
    if px_per_mm <= 0:
        raise ValueError("px_per_mm must be positive")

    def convert(ring: np.ndarray) -> np.ndarray:
        out = np.empty_like(ring, dtype=float)
        out[:, 0] = ring[:, 0] / px_per_mm
        out[:, 1] = (image_height_px - ring[:, 1]) / px_per_mm
        return out

    converted = [
        Path(convert(p.outer), [convert(h) for h in p.holes], p.level)
        for p in paths
    ]

    if origin == "center":
        box = bounds_of(converted)
        if box is not None:
            dx = -(box.min_x + box.max_x) / 2.0
            dy = -(box.min_y + box.max_y) / 2.0
            for path in converted:
                for ring in path.rings():
                    ring[:, 0] += dx
                    ring[:, 1] += dy

    return converted
