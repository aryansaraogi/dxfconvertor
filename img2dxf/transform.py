"""Rotate and crop the source image before anything else looks at it."""

from __future__ import annotations

import cv2
import numpy as np

from .params import TraceParams

#: Rotation exposes new corners; filling them white keeps them out of the burn
#: (the pipeline treats dark as foreground unless `invert` says otherwise).
_FILL = (255, 255, 255)


def apply_transform(rgb: np.ndarray, params: TraceParams) -> np.ndarray:
    """Return ``rgb`` rotated then cropped, per ``params``.

    Rotation comes first so the crop rectangle can be drawn against what the
    user is actually looking at — straighten a scan, then box the part you
    want. Everything downstream, sizing included, sees only the result, so
    "80 mm wide" means the width of the cropped piece.
    """
    out = rotate(rgb, params.rotate_deg)
    return crop(out, params.crop)


def rotate(rgb: np.ndarray, degrees: float) -> np.ndarray:
    """Rotate about the centre, growing the canvas so nothing is clipped."""
    if not degrees % 360:
        return rgb

    height, width = rgb.shape[:2]
    centre = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(centre, degrees, 1.0)

    # Work out the bounding box the rotated image needs, then shift the
    # transform into it; without this the corners are cut off.
    cos = abs(matrix[0, 0])
    sin = abs(matrix[0, 1])
    new_width = int(round(height * sin + width * cos))
    new_height = int(round(height * cos + width * sin))
    matrix[0, 2] += new_width / 2.0 - centre[0]
    matrix[1, 2] += new_height / 2.0 - centre[1]

    return cv2.warpAffine(
        rgb,
        matrix,
        (new_width, new_height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=_FILL,
    )


def crop(rgb: np.ndarray, box: tuple[float, float, float, float] | None) -> np.ndarray:
    """Crop to ``box``, given as ``(left, top, right, bottom)`` fractions.

    Fractions rather than pixels so a crop stays meaningful if the same
    settings are reused on a different resolution of the same artwork.
    """
    if box is None:
        return rgb

    height, width = rgb.shape[:2]
    left, top, right, bottom = normalize_box(box)

    x0 = int(round(left * width))
    x1 = int(round(right * width))
    y0 = int(round(top * height))
    y1 = int(round(bottom * height))

    # Never hand back an empty array; a degenerate box means "no crop".
    if x1 - x0 < 1 or y1 - y0 < 1:
        return rgb

    return rgb[y0:y1, x0:x1]


def normalize_box(
    box: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Clamp to 0..1 and order the corners, so a backwards drag still works."""
    left, top, right, bottom = (min(max(float(v), 0.0), 1.0) for v in box)
    if left > right:
        left, right = right, left
    if top > bottom:
        top, bottom = bottom, top
    return left, top, right, bottom
