"""Every knob the pipeline understands, in one place.

The GUI, the CLI and the tests all build a :class:`TraceParams` and hand it to
:func:`img2dxf.pipeline.run`, so there is exactly one code path to reason about.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

BinarizeMode = Literal["otsu", "fixed", "adaptive", "posterize", "edges"]
SizeMode = Literal["fit", "dpi"]
Origin = Literal["bottom-left", "center"]

#: DXF flavours offered in the UI, newest first. R12 is the compatibility
#: fallback for older Ruida/RDWorks stacks.
DXF_VERSIONS: tuple[str, ...] = ("R2010", "R2000", "R12")


@dataclass(frozen=True, slots=True)
class TraceParams:
    """Parameters for one image -> DXF conversion.

    Lengths the user types are in millimetres; anything in pixels is internal.
    """

    # --- preprocessing -------------------------------------------------
    invert: bool = False
    """Trace the light regions instead of the dark ones."""

    blur: int = 0
    """Gaussian blur radius in pixels. 0 disables. Rounded up to an odd kernel."""

    denoise: int = 0
    """Median-filter radius in pixels, for scanner grain. 0 disables."""

    # --- binarization --------------------------------------------------
    mode: BinarizeMode = "otsu"
    threshold: int = 128
    """Cut level for ``mode="fixed"``, 0-255."""

    adaptive_block: int = 31
    """Neighbourhood size for ``mode="adaptive"``. Forced odd and >= 3."""

    adaptive_c: int = 5
    """Constant subtracted from the local mean for ``mode="adaptive"``."""

    levels: int = 3
    """Tone-level count for ``mode="posterize"``, 2-8. Each gets its own layer."""

    canny_low: int = 80
    canny_high: int = 160
    edge_dilate: int = 1
    """Pixels of dilation applied to Canny edges before tracing."""

    # --- morphology ----------------------------------------------------
    close_px: int = 0
    """Morphological closing radius: bridges hairline gaps in the mask."""

    open_px: int = 0
    """Morphological opening radius: removes isolated specks from the mask."""

    # --- vectorization -------------------------------------------------
    simplify_mm: float = 0.05
    """Douglas-Peucker tolerance. Larger = fewer vertices, blockier curves."""

    smooth: int = 0
    """Chaikin corner-rounding passes, 0-3. Softens staircase edges."""

    min_area_mm2: float = 0.5
    """Drop contours smaller than this. The despeckle control."""

    keep_holes: bool = True
    """Emit inner contours, so the counter of an 'O' is not filled in."""

    # --- sizing --------------------------------------------------------
    size_mode: SizeMode = "fit"
    width_mm: float = 100.0
    """Target width for ``size_mode="fit"``. Height follows the aspect ratio."""

    height_mm: float | None = None
    """If set, fit to this height instead and let width follow."""

    dpi: float = 96.0
    """Pixels per inch for ``size_mode="dpi"``."""

    origin: Origin = "bottom-left"

    # --- output --------------------------------------------------------
    dxf_version: str = "R2010"
    layer_name: str = "CUT"

    def normalized(self) -> "TraceParams":
        """Clamp every field into the range the pipeline can actually use.

        Called once at the top of :func:`img2dxf.pipeline.run` so downstream
        code never has to defend against a nonsense slider value.
        """
        return replace(
            self,
            blur=max(0, int(self.blur)),
            denoise=max(0, int(self.denoise)),
            threshold=_clamp(int(self.threshold), 0, 255),
            adaptive_block=_odd_at_least(int(self.adaptive_block), 3),
            adaptive_c=_clamp(int(self.adaptive_c), -50, 50),
            levels=_clamp(int(self.levels), 2, 8),
            canny_low=_clamp(int(self.canny_low), 0, 255),
            canny_high=_clamp(int(self.canny_high), 0, 255),
            edge_dilate=_clamp(int(self.edge_dilate), 0, 20),
            close_px=_clamp(int(self.close_px), 0, 50),
            open_px=_clamp(int(self.open_px), 0, 50),
            simplify_mm=max(0.0, float(self.simplify_mm)),
            smooth=_clamp(int(self.smooth), 0, 3),
            min_area_mm2=max(0.0, float(self.min_area_mm2)),
            width_mm=max(0.1, float(self.width_mm)),
            dpi=max(1.0, float(self.dpi)),
            dxf_version=self.dxf_version if self.dxf_version in DXF_VERSIONS else "R2010",
        )


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _odd_at_least(value: int, floor: int) -> int:
    value = max(floor, value)
    return value if value % 2 == 1 else value + 1


#: Starting points that get a usable result without touching every slider.
PRESETS: dict[str, TraceParams] = {
    "Logo / clipart": TraceParams(
        mode="otsu", simplify_mm=0.05, min_area_mm2=0.5, smooth=0
    ),
    "Photo": TraceParams(
        mode="posterize", levels=3, blur=3, simplify_mm=0.15,
        min_area_mm2=2.0, smooth=1,
    ),
    "Line art / scan": TraceParams(
        mode="adaptive", adaptive_block=31, adaptive_c=7, denoise=3,
        simplify_mm=0.08, min_area_mm2=0.3, close_px=1,
    ),
    "Edge outline": TraceParams(
        mode="edges", canny_low=80, canny_high=160, edge_dilate=1,
        simplify_mm=0.08, min_area_mm2=0.2,
    ),
}

DEFAULT_PRESET = "Logo / clipart"
