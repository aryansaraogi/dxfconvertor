"""Image loading and everything that happens before contours exist.

The output of this module is always a list of ``uint8`` masks where 255 means
"burn this" and 0 means "leave it". Multi-mask output only happens in
posterize mode, where each mask is one tone level.
"""

from __future__ import annotations

from pathlib import Path as FsPath

import cv2
import numpy as np
from PIL import Image

from .params import TraceParams


def load_image(path: str | FsPath) -> tuple[np.ndarray, float | None]:
    """Load an image as RGB and return it with its embedded DPI if any.

    Pillow is used rather than ``cv2.imread`` because it reads the DPI metadata
    and copes with non-ASCII paths on Windows, which ``imread`` silently fails
    on by returning ``None``.
    """
    with Image.open(path) as img:
        dpi_info = img.info.get("dpi")
        rgb = np.asarray(img.convert("RGB"))

    dpi: float | None = None
    if dpi_info:
        try:
            value = float(dpi_info[0])
            # Some encoders write 0 or 1; neither is a real resolution.
            if value > 1.0:
                dpi = value
        except (TypeError, ValueError, IndexError):
            dpi = None

    return rgb, dpi


def to_grayscale(rgb: np.ndarray) -> np.ndarray:
    if rgb.ndim == 2:
        return rgb
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


def prepare(gray: np.ndarray, params: TraceParams) -> np.ndarray:
    """Denoise and blur, in that order.

    Median first so salt-and-pepper specks are removed outright instead of
    being smeared into grey blobs that then survive thresholding.
    """
    out = gray
    if params.denoise:
        out = cv2.medianBlur(out, _odd(params.denoise))
    if params.blur:
        k = _odd(params.blur)
        out = cv2.GaussianBlur(out, (k, k), 0)
    return out


def binarize(gray: np.ndarray, params: TraceParams) -> list[np.ndarray]:
    """Produce one or more burn masks from a prepared grayscale image.

    Dark pixels become foreground by default, which matches how people read a
    black-on-white logo; ``params.invert`` swaps that.
    """
    mode = params.mode

    if mode == "posterize":
        masks = _posterize(gray, params.levels)
    elif mode == "edges":
        masks = [_edges(gray, params)]
    elif mode == "adaptive":
        masks = [
            cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV, params.adaptive_block, params.adaptive_c,
            )
        ]
    elif mode == "fixed":
        _, mask = cv2.threshold(gray, params.threshold, 255, cv2.THRESH_BINARY_INV)
        masks = [mask]
    else:  # otsu
        _, mask = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
        )
        masks = [mask]

    # Edge masks are already outlines; inverting them would trace the
    # background instead, which is never what the control means.
    if params.invert and mode != "edges":
        masks = [cv2.bitwise_not(m) for m in masks]

    return [_morphology(m, params) for m in masks]


def _posterize(gray: np.ndarray, levels: int) -> list[np.ndarray]:
    """Quantize into ``levels`` tones and return a cumulative mask per tone.

    Masks are cumulative (each darker level includes everything darker still)
    so the tones nest like contour lines on a map rather than meeting at
    hairline seams that the laser would leave as visible gaps.
    """
    edges = np.linspace(0, 255, levels + 1)
    masks = []
    # Skip the lightest band: that is the paper, not a burn.
    for i in range(levels - 1):
        cutoff = edges[i + 1]
        masks.append((gray <= cutoff).astype(np.uint8) * 255)
    return masks


def _edges(gray: np.ndarray, params: TraceParams) -> np.ndarray:
    low, high = sorted((params.canny_low, params.canny_high))
    mask = cv2.Canny(gray, low, max(high, low + 1))
    if params.edge_dilate:
        mask = cv2.dilate(mask, _kernel(params.edge_dilate))
    return mask


def _morphology(mask: np.ndarray, params: TraceParams) -> np.ndarray:
    """Close hairline gaps, then remove specks.

    Closing runs first: doing it the other way round would delete thin
    features that closing was about to repair.
    """
    if params.close_px:
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, _kernel(params.close_px))
    if params.open_px:
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, _kernel(params.open_px))
    return mask


def _kernel(radius: int) -> np.ndarray:
    size = _odd(radius)
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))


def _odd(radius: int) -> int:
    size = max(1, int(radius))
    return size if size % 2 == 1 else size + 1
