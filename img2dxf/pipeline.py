"""Joins preprocessing, tracing and scaling into one call."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path as FsPath

import numpy as np

from .arcfit import fit_bulges, fit_circle
from .geometry import Bounds, Path, bounds_of, pixels_per_mm, to_millimetres
from .kerf import offset_paths
from .params import TraceParams
from .preprocess import binarize, load_image, prepare, to_grayscale
from .tile import tile_paths
from .trace import trace_mask
from .transform import apply_transform


@dataclass(slots=True)
class TraceResult:
    """Everything the GUI, the CLI and the DXF writer need from one run."""

    paths: list[Path]
    """Outlines in millimetre space, ready to write."""

    masks: list[np.ndarray]
    """The binary masks that produced them, for the preview."""

    discarded: list[Path]
    """Contours dropped by the minimum-area filter, in millimetres."""

    image_rgb: np.ndarray
    """The rotated and cropped image the trace actually ran on."""

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

    fits_bed: bool = True
    """Whether the finished job fits the configured machine bed."""

    bed_size_mm: tuple[float, float] | None = None
    """The bed it was checked against, or ``None`` if none is configured."""

    tabbed: bool = False
    """Whether tabs will be cut into these paths on export."""

    @property
    def arc_count(self) -> int:
        """Arcs and whole circles recovered by the fitter."""
        return sum(
            int(np.count_nonzero(b)) for p in self.paths for b in p.bulges.values()
        ) + sum(len(p.circles) for p in self.paths)

    def summary(self) -> str:
        """One-line status text: the sanity check before hitting Export."""
        if self.bounds is None:
            return "No paths found — try adjusting the threshold or mode."
        text = (
            f"{self.path_count} paths | {self.vertex_count} vertices | "
            f"{self.bounds.width:.1f} x {self.bounds.height:.1f} mm"
        )
        if self.tabbed:
            # Tabs flatten the rings they cut, so claiming arcs here would
            # describe a file the user is not going to get.
            text += " | tabbed"
        elif self.arc_count:
            text += f" | {self.arc_count} arcs"
        if self.discarded:
            text += f" | {len(self.discarded)} dropped"
        if not self.fits_bed and self.bed_size_mm:
            bed_w, bed_h = self.bed_size_mm
            text += f" | DOES NOT FIT {bed_w:.0f} x {bed_h:.0f} mm bed"
        return text


def run(image_rgb: np.ndarray, params: TraceParams) -> TraceResult:
    """Convert an already-loaded RGB image into millimetre-space paths."""
    params = params.normalized()

    # Rotate and crop first: every measurement below, sizing included, should
    # describe the piece the user is actually looking at.
    image_rgb = apply_transform(image_rgb, params)
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
    discarded: list[Path] = []
    for level, mask in enumerate(masks):
        kept, dropped = trace_mask(mask, params, px_per_mm=px_per_mm, level=level)
        paths.extend(kept)
        discarded.extend(dropped)

    def to_mm(items: list[Path]) -> list[Path]:
        return to_millimetres(
            items,
            image_height_px=height_px,
            px_per_mm=px_per_mm,
            origin=params.origin,
        )

    paths = to_mm(paths)
    discarded = to_mm(discarded)

    # Kerf before arcs: the arcs should describe the path the machine will
    # actually follow, not the one before compensation moved it.
    paths = offset_paths(paths, params.kerf_mm, params.kerf_side)
    if params.fit_arcs:
        _fit_arcs(paths, params.simplify_mm, px_per_mm)

    # Tiling last: each shape is fitted once and then copied, rather than
    # paying for the arc fit on every tile.
    paths = tile_paths(paths, params.copies_x, params.copies_y, params.tile_gap_mm)

    bounds = bounds_of(paths)
    bed = (params.bed_width_mm, params.bed_height_mm) if params.has_bed else None

    return TraceResult(
        paths=paths,
        masks=masks,
        discarded=discarded,
        image_rgb=image_rgb,
        gray=gray,
        px_per_mm=px_per_mm,
        image_size_px=(width_px, height_px),
        bounds=bounds,
        fits_bed=_fits(bounds, bed),
        bed_size_mm=bed,
        tabbed=params.tabs_enabled,
    )


def _fits(bounds: Bounds | None, bed: tuple[float, float] | None) -> bool:
    """Whether the job fits the bed.

    Compares extents rather than corner positions: a job placed away from the
    origin still fits if the operator can move it, and warning about placement
    would cry wolf on every centred job.
    """
    if bounds is None or bed is None:
        return True
    return bounds.width <= bed[0] and bounds.height <= bed[1]


def _fit_arcs(paths: list[Path], simplify_mm: float, px_per_mm: float) -> None:
    """Attach arc data to every ring, in place.

    The tolerance is the looser of the simplification tolerance and one source
    pixel. The pixel floor is the important half: a traced circle is a
    staircase of whole pixels, so it departs from any true circle by about
    half a pixel no matter how clean the artwork. Demanding a tighter fit than
    the image can express rejects every real circle.
    """
    tol = max(simplify_mm, 1.0 / px_per_mm if px_per_mm > 0 else 0.0, 0.02)

    for path in paths:
        for index, ring in enumerate(path.rings()):
            circle = fit_circle(ring, tol)
            if circle is not None:
                path.circles[index] = circle
                continue
            fitted = fit_bulges(ring, tol)
            if fitted is None:
                continue
            points, bulges = fitted
            if index == 0:
                path.outer = points
            else:
                path.holes[index - 1] = points
            path.bulges[index] = bulges


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
