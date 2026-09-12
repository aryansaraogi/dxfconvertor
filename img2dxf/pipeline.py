"""Joins preprocessing, tracing and scaling into one call."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path as FsPath

import numpy as np

from .geometry import Bounds, Path, bounds_of, pixels_per_mm, to_millimetres
from .params import TraceParams
from .preprocess import binarize, load_image, prepare, to_grayscale
from .trace import trace_mask


@dataclass(slots=True)
class TraceResult:
    """Everything the GUI, the CLI and the DXF writer need from one run."""

    paths: list[Path]
    """Outlines in millimetre space, ready to write."""

    masks: list[np.ndarray]
    """The binary masks that produced them, for the preview."""

    gray: np.ndarray
    px_per_mm: float
    image_size_px: tuple[int, int]
    """``(width, height)`` of the source image."""

    bounds: Bounds | None
    """Extents in millimetres, or ``None`` when nothing was traced."""

    @property
    def path_count(self) -> int:
        return len(self.paths)

    @property
    def vertex_count(self) -> int:
        return sum(p.vertex_count for p in self.paths)

    @property
    def level_count(self) -> int:
        return len({p.level for p in self.paths})

    def summary(self) -> str:
        """One-line status text: the sanity check before hitting Export."""
        if self.bounds is None:
            return "No paths found — try adjusting the threshold or mode."
        return (
            f"{self.path_count} paths | {self.vertex_count} vertices | "
            f"{self.bounds.width:.1f} x {self.bounds.height:.1f} mm"
        )


def run(image_rgb: np.ndarray, params: TraceParams) -> TraceResult:
    """Convert an already-loaded RGB image into millimetre-space paths."""
    params = params.normalized()

    height_px, width_px = image_rgb.shape[:2]
    px_per_mm = pixels_per_mm(
        width_px, height_px,
        size_mode=params.size_mode,
        width_mm=params.width_mm,
        height_mm=params.height_mm,
        dpi=params.dpi,
    )

    gray = prepare(to_grayscale(image_rgb), params)
    masks = binarize(gray, params)

    paths: list[Path] = []
    for level, mask in enumerate(masks):
        paths.extend(trace_mask(mask, params, px_per_mm=px_per_mm, level=level))

    paths = to_millimetres(
        paths,
        image_height_px=height_px,
        px_per_mm=px_per_mm,
        origin=params.origin,
    )

    return TraceResult(
        paths=paths,
        masks=masks,
        gray=gray,
        px_per_mm=px_per_mm,
        image_size_px=(width_px, height_px),
        bounds=bounds_of(paths),
    )


def run_file(path: str | FsPath, params: TraceParams) -> TraceResult:
    """Load an image from disk and trace it.

    When the file carries a DPI and the caller has not overridden it, that
    value is adopted so ``size_mode="dpi"`` reproduces the intended physical
    size rather than assuming 96.
    """
    rgb, file_dpi = load_image(path)
    if params.size_mode == "dpi" and file_dpi:
        from dataclasses import replace

        params = replace(params, dpi=file_dpi)
    return run(rgb, params)
