"""Every knob the pipeline understands, in one place.

The GUI, the CLI and the tests all build a :class:`TraceParams` and hand it to
:func:`img2dxf.pipeline.run`, so there is exactly one code path to reason about.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

BinarizeMode = Literal["otsu", "fixed", "adaptive", "posterize", "edges"]
KerfSide = Literal["none", "outside", "inside"]
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

    # --- source framing ------------------------------------------------
    rotate_deg: float = 0.0
    """Rotation applied before anything else. Straightens a crooked scan."""

    crop: tuple[float, float, float, float] | None = None
    """``(left, top, right, bottom)`` as fractions of the rotated image."""

    # --- resolution ----------------------------------------------------
    detail: int = 0
    """Supersampling factor applied before thresholding. 0 picks one.

    Thresholding quantises every outline to the pixel grid, and that — not the
    simplification tolerance — is what limits how clean a traced edge can be.
    Tracing an upscaled image lifts that ceiling: on a small logo it cuts the
    error against the original artwork by roughly five times.
    """

    # --- image adjustments ---------------------------------------------
    auto_levels: bool = False
    """Stretch the tonal range to fill 0-255, ignoring outlier pixels."""

    brightness: int = 0
    """Added to every pixel, -100 to 100."""

    contrast: float = 1.0
    """Multiplier about mid-grey. 1.0 leaves the image alone."""

    gamma: float = 1.0
    """Below 1 darkens midtones, above 1 lightens them."""

    sharpen: float = 0.0
    """Unsharp-mask strength. Pulls against `blur`; use one or the other."""

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
    """Corner-aware smoothing passes, 0-3. Softens staircase edges."""

    corner_deg: float = 40.0
    """Turns sharper than this are corners, and smoothing leaves them alone."""

    straighten_mm: float = 0.15
    """Flatten runs that stray less than this from their own chord. 0 disables.

    Deliberately looser than `simplify_mm`: it is a separate judgement that a
    run is structurally a straight line, not a tighter accuracy budget.
    """

    min_run_mm: float = 2.0
    """Only runs at least this long are considered for straightening."""

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

    # --- machine compensation ------------------------------------------
    kerf_mm: float = 0.0
    """Beam width. Paths are offset by half of it; 0 disables."""

    kerf_side: KerfSide = "none"
    """``outside`` keeps the part's size, ``inside`` keeps the hole's."""

    fit_arcs: bool = True
    """Replace circular runs with true arcs and circles."""

    tab_count: int = 0
    """Uncut bridges left in each closed path, so parts stay in the sheet."""

    tab_mm: float = 0.5
    """Width of each bridge."""

    # --- layout --------------------------------------------------------
    copies_x: int = 1
    copies_y: int = 1
    """Grid of copies to lay out, for filling a sheet in one job."""

    tile_gap_mm: float = 2.0
    """Space between tiled copies."""

    bed_width_mm: float = 0.0
    bed_height_mm: float = 0.0
    """Machine bed size. 0 means no bed configured, so no fit check."""

    # --- output --------------------------------------------------------
    dxf_version: str = "R2010"
    layer_name: str = "CUT"

    @property
    def straighten_enabled(self) -> bool:
        return self.straighten_mm > 0 and self.min_run_mm > 0

    @property
    def tabs_enabled(self) -> bool:
        """Tabs need both a count and a width to do anything."""
        return self.tab_count > 0 and self.tab_mm > 0

    @property
    def has_bed(self) -> bool:
        return self.bed_width_mm > 0 and self.bed_height_mm > 0

    def normalized(self) -> "TraceParams":
        """Clamp every field into the range the pipeline can actually use.

        Called once at the top of :func:`img2dxf.pipeline.run` so downstream
        code never has to defend against a nonsense slider value.
        """
        return replace(
            self,
            rotate_deg=float(self.rotate_deg) % 360.0,
            crop=_clean_box(self.crop),
            kerf_mm=max(0.0, float(self.kerf_mm)),
            brightness=_clamp(int(self.brightness), -100, 100),
            contrast=max(0.1, min(4.0, float(self.contrast))),
            gamma=max(0.1, min(4.0, float(self.gamma))),
            sharpen=max(0.0, min(3.0, float(self.sharpen))),
            tab_count=_clamp(int(self.tab_count), 0, 24),
            tab_mm=max(0.0, float(self.tab_mm)),
            copies_x=_clamp(int(self.copies_x), 1, 50),
            copies_y=_clamp(int(self.copies_y), 1, 50),
            tile_gap_mm=max(0.0, float(self.tile_gap_mm)),
            bed_width_mm=max(0.0, float(self.bed_width_mm)),
            bed_height_mm=max(0.0, float(self.bed_height_mm)),
            kerf_side=self.kerf_side if self.kerf_side in _KERF_SIDES else "none",
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
            detail=_clamp(int(self.detail), 0, 4),
            corner_deg=max(0.0, min(180.0, float(self.corner_deg))),
            straighten_mm=max(0.0, float(self.straighten_mm)),
            min_run_mm=max(0.0, float(self.min_run_mm)),
            simplify_mm=max(0.0, float(self.simplify_mm)),
            smooth=_clamp(int(self.smooth), 0, 3),
            min_area_mm2=max(0.0, float(self.min_area_mm2)),
            width_mm=max(0.1, float(self.width_mm)),
            dpi=max(1.0, float(self.dpi)),
            dxf_version=self.dxf_version if self.dxf_version in DXF_VERSIONS else "R2010",
        )


_KERF_SIDES = ("none", "outside", "inside")


def _clean_box(box) -> tuple[float, float, float, float] | None:
    """Drop a crop that covers everything; it only costs a copy."""
    if box is None:
        return None
    from .transform import normalize_box

    left, top, right, bottom = normalize_box(tuple(box))
    if right - left <= 0 or bottom - top <= 0:
        return None
    if (left, top, right, bottom) == (0.0, 0.0, 1.0, 1.0):
        return None
    return left, top, right, bottom


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _odd_at_least(value: int, floor: int) -> int:
    value = max(floor, value)
    return value if value % 2 == 1 else value + 1


#: Starting points that get a usable result without touching every slider.
PRESETS: dict[str, TraceParams] = {
    "Logo / clipart": TraceParams(
        mode="otsu", simplify_mm=0.05, min_area_mm2=0.5, smooth=0,
        straighten_mm=0.15,
    ),
    "Photo": TraceParams(
        mode="posterize", levels=3, blur=3, simplify_mm=0.15,
        min_area_mm2=2.0, smooth=1,
        # Photographs have no straight edges to recover; forcing runs flat
        # would only flatten tonal boundaries that are genuinely curved.
        straighten_mm=0.0,
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
