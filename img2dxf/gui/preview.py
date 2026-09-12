"""The preview canvas: what to draw, at what zoom, and where it lands.

The coordinate mapping lives here rather than in the window, because the crop
handles and the measure tool both need to convert between canvas pixels and
image pixels, and two copies of that arithmetic would drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageTk

from ..arcfit import circle_points, flatten_ring
from ..pipeline import TraceResult

VIEWS = ("Original", "Mask", "Vectors", "Overlay")

_OUTER_COLOR = (16, 120, 230)
_HOLE_COLOR = (225, 60, 40)
_DISCARDED_COLOR = (235, 150, 20)
_OVERLAY_DIM = 0.35

MIN_ZOOM = 0.05
MAX_ZOOM = 40.0


@dataclass(slots=True)
class ViewState:
    """How the image sits on the canvas.

    ``scale`` is canvas pixels per image pixel, and ``(offset_x, offset_y)`` is
    where the image's top-left corner sits on the canvas. ``fitted`` records
    that the view is still auto-fitting, so a new image or a resize refits
    instead of stranding the user at someone else's zoom.
    """

    scale: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    fitted: bool = True

    def fit(self, image_size: tuple[int, int], canvas_size: tuple[int, int]) -> None:
        width, height = image_size
        canvas_w, canvas_h = canvas_size
        if width <= 0 or height <= 0 or canvas_w <= 1 or canvas_h <= 1:
            return
        self.scale = min(canvas_w / width, canvas_h / height)
        self.offset_x = (canvas_w - width * self.scale) / 2.0
        self.offset_y = (canvas_h - height * self.scale) / 2.0
        self.fitted = True

    def canvas_to_image(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.offset_x) / self.scale, (y - self.offset_y) / self.scale

    def image_to_canvas(self, x: float, y: float) -> tuple[float, float]:
        return x * self.scale + self.offset_x, y * self.scale + self.offset_y

    def zoom_at(self, x: float, y: float, factor: float) -> None:
        """Zoom about a canvas point, keeping what is under it in place."""
        new_scale = max(MIN_ZOOM, min(MAX_ZOOM, self.scale * factor))
        if new_scale == self.scale:
            return
        image_x, image_y = self.canvas_to_image(x, y)
        self.scale = new_scale
        self.offset_x = x - image_x * new_scale
        self.offset_y = y - image_y * new_scale
        self.fitted = False

    def pan(self, dx: float, dy: float) -> None:
        self.offset_x += dx
        self.offset_y += dy
        self.fitted = False


def render(
    view: str,
    image_rgb: np.ndarray | None,
    result: TraceResult | None,
    state: ViewState,
    canvas_size: tuple[int, int],
    *,
    show_discarded: bool = False,
) -> ImageTk.PhotoImage | None:
    """Render one canvas-sized frame at the current zoom and pan.

    The frame is built at image resolution and then resampled once, so vector
    line widths stay one pixel on screen at any zoom instead of thickening
    with it.
    """
    canvas_w, canvas_h = canvas_size
    if image_rgb is None or canvas_w < 2 or canvas_h < 2:
        return None

    source = _compose(view, image_rgb, result)
    if view in ("Vectors", "Overlay") and result is not None:
        _draw_paths(source, result, show_discarded)

    return ImageTk.PhotoImage(_place(source, state, canvas_size))


def _compose(
    view: str, image_rgb: np.ndarray, result: TraceResult | None
) -> Image.Image:
    height, width = image_rgb.shape[:2]

    if view == "Mask" and result is not None and result.masks:
        return Image.fromarray(_combine_masks(result.masks)).convert("RGB")
    if view == "Vectors":
        return Image.new("RGB", (width, height), "white")
    if view == "Overlay":
        return Image.blend(
            Image.fromarray(image_rgb),
            Image.new("RGB", (width, height), "white"),
            _OVERLAY_DIM,
        )
    return Image.fromarray(image_rgb)


def _place(
    source: Image.Image, state: ViewState, canvas_size: tuple[int, int]
) -> Image.Image:
    """Scale and position ``source`` onto a canvas-sized frame.

    Only the visible region is resampled; at high zoom on a large photo,
    scaling the whole image first would cost hundreds of megabytes.
    """
    canvas_w, canvas_h = canvas_size
    frame = Image.new("RGB", (canvas_w, canvas_h), "#f2f2f2")

    left, top = state.canvas_to_image(0, 0)
    right, bottom = state.canvas_to_image(canvas_w, canvas_h)

    crop_left = max(0, int(np.floor(left)))
    crop_top = max(0, int(np.floor(top)))
    crop_right = min(source.width, int(np.ceil(right)) + 1)
    crop_bottom = min(source.height, int(np.ceil(bottom)) + 1)
    if crop_right <= crop_left or crop_bottom <= crop_top:
        return frame

    visible = source.crop((crop_left, crop_top, crop_right, crop_bottom))
    target_w = max(1, int(round(visible.width * state.scale)))
    target_h = max(1, int(round(visible.height * state.scale)))

    # Nearest-neighbour past 1:1 so pixels stay crisp when inspecting detail.
    resample = Image.NEAREST if state.scale > 1.5 else Image.LANCZOS
    visible = visible.resize((target_w, target_h), resample)

    paste_x, paste_y = state.image_to_canvas(crop_left, crop_top)
    frame.paste(visible, (int(round(paste_x)), int(round(paste_y))))
    return frame


def _combine_masks(masks: list[np.ndarray]) -> np.ndarray:
    """Stack tone masks into one greyscale image, darkest tone darkest.

    Each cumulative mask adds another layer of ink, so overlapping levels read
    as deepening grey — the same way the finished etch will.
    """
    if len(masks) == 1:
        return 255 - masks[0]
    stack = np.sum([(m > 0).astype(np.uint16) for m in masks], axis=0)
    return (255 - (stack * (255 // len(masks)))).astype(np.uint8)


def _draw_paths(
    frame: Image.Image, result: TraceResult, show_discarded: bool
) -> None:
    """Draw traced rings, converting millimetre coordinates back to pixels."""
    draw = ImageDraw.Draw(frame)

    if show_discarded:
        for path in result.discarded:
            draw.line(
                _closed(_to_pixels(path.outer, result, frame.height)),
                fill=_DISCARDED_COLOR,
                width=1,
            )

    for path in result.paths:
        for index, ring in enumerate(path.rings()):
            curve = _curve_of(path, index, ring)
            colour = _OUTER_COLOR if index == 0 else _HOLE_COLOR
            draw.line(
                _closed(_to_pixels(curve, result, frame.height)),
                fill=colour,
                width=1,
            )


def _curve_of(path, index: int, ring: np.ndarray) -> np.ndarray:
    """The drawable curve for one ring, honouring fitted arcs and circles."""
    circle = path.circles.get(index)
    if circle is not None:
        return circle_points(circle)
    return flatten_ring(ring, path.bulges.get(index))


def _to_pixels(
    ring: np.ndarray, result: TraceResult, frame_height: int
) -> list[tuple[float, float]]:
    scale = result.px_per_mm
    xs = ring[:, 0]
    ys = ring[:, 1]

    # A centred origin shifts the paths out of image space; undo it so the
    # overlay still lines up with the source pixels.
    box = result.bounds
    if box is not None and box.min_x < 0:
        xs = xs - box.min_x
        ys = ys - box.min_y

    return [
        (float(x) * scale, frame_height - float(y) * scale) for x, y in zip(xs, ys)
    ]


def _closed(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    return points + points[:1] if points else points
