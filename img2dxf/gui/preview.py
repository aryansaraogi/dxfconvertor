"""The preview canvas: original, mask, vectors, or vectors over the image."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageTk

from ..pipeline import TraceResult

VIEWS = ("Original", "Mask", "Vectors", "Overlay")

_OUTER_COLOR = (16, 120, 230)
_HOLE_COLOR = (225, 60, 40)
_OVERLAY_DIM = 0.35


def render(
    view: str,
    image_rgb: np.ndarray | None,
    result: TraceResult | None,
    size: tuple[int, int],
) -> ImageTk.PhotoImage | None:
    """Render one preview frame scaled to fit ``size``.

    Vectors are drawn in *pixel* space rather than millimetre space: the two
    differ only by a uniform scale, and staying in pixels keeps the overlay
    registered with the source image regardless of the sizing controls.
    """
    width, height = size
    if image_rgb is None or width < 2 or height < 2:
        return None

    src_h, src_w = image_rgb.shape[:2]
    scale = min(width / src_w, height / src_h)
    target = (max(1, int(src_w * scale)), max(1, int(src_h * scale)))

    if view == "Mask" and result is not None and result.masks:
        frame = Image.fromarray(_combine_masks(result.masks)).convert("RGB")
    elif view == "Vectors":
        frame = Image.new("RGB", (src_w, src_h), "white")
    elif view == "Overlay":
        frame = Image.blend(
            Image.fromarray(image_rgb),
            Image.new("RGB", (src_w, src_h), "white"),
            _OVERLAY_DIM,
        )
    else:
        frame = Image.fromarray(image_rgb)

    if view in ("Vectors", "Overlay") and result is not None:
        _draw_paths(frame, result)

    return ImageTk.PhotoImage(frame.resize(target, Image.LANCZOS))


def _combine_masks(masks: list[np.ndarray]) -> np.ndarray:
    """Stack tone masks into one greyscale image, darkest tone darkest.

    Each cumulative mask adds another layer of ink, so overlapping levels read
    as deepening grey — the same way the finished etch will.
    """
    if len(masks) == 1:
        return 255 - masks[0]
    stack = np.sum([(m > 0).astype(np.uint16) for m in masks], axis=0)
    return (255 - (stack * (255 // len(masks)))).astype(np.uint8)


def _draw_paths(frame: Image.Image, result: TraceResult) -> None:
    """Draw traced rings, converting millimetre coordinates back to pixels."""
    draw = ImageDraw.Draw(frame)
    scale = result.px_per_mm
    src_h = frame.height
    box = result.bounds

    def to_pixels(ring: np.ndarray) -> list[tuple[float, float]]:
        xs = ring[:, 0]
        ys = ring[:, 1]
        # "center" origin shifts the paths away from image space; undo it so
        # the overlay still lines up with the source pixels.
        if box is not None and box.min_x < 0:
            xs = xs - box.min_x
            ys = ys - box.min_y
        return [(float(x) * scale, src_h - float(y) * scale) for x, y in zip(xs, ys)]

    for path in result.paths:
        draw.line(_closed(to_pixels(path.outer)), fill=_OUTER_COLOR, width=1)
        for hole in path.holes:
            draw.line(_closed(to_pixels(hole)), fill=_HOLE_COLOR, width=1)


def _closed(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    return points + points[:1] if points else points
