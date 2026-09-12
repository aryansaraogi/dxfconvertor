"""Repeat the traced geometry across a grid, to fill a sheet in one job."""

from __future__ import annotations

from .geometry import Path, bounds_of, translate


def tile_paths(
    paths: list[Path], columns: int, rows: int, gap_mm: float
) -> list[Path]:
    """Lay ``columns`` x ``rows`` copies out on a grid.

    The pitch is the job's own bounding box plus ``gap_mm``, so copies never
    overlap however irregular the artwork is. Copies are laid out to the right
    and *upwards*, keeping the original at the origin corner where the bed
    check expects it.
    """
    if columns <= 1 and rows <= 1:
        return paths

    box = bounds_of(paths)
    if box is None:
        return paths

    pitch_x = box.width + gap_mm
    pitch_y = box.height + gap_mm

    tiled: list[Path] = []
    for row in range(rows):
        for column in range(columns):
            if row == 0 and column == 0:
                tiled.extend(paths)
                continue
            offset_x = column * pitch_x
            offset_y = row * pitch_y
            tiled.extend(translate(path, offset_x, offset_y) for path in paths)

    return tiled
