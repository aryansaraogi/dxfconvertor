"""Rotation, cropping, and the discarded-contour reporting."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from img2dxf.params import TraceParams
from img2dxf.pipeline import run
from img2dxf.transform import crop, normalize_box, rotate


def test_rotation_grows_the_canvas_instead_of_clipping():
    image = np.zeros((100, 200, 3), np.uint8)
    turned = rotate(image, 90)
    assert turned.shape[:2] == (200, 100)


def test_rotation_by_a_full_turn_is_a_no_op():
    image = np.zeros((10, 20, 3), np.uint8)
    assert rotate(image, 360) is image


def test_rotation_fills_new_corners_with_white():
    """New corners must be background, or they would be traced as shapes."""
    image = np.zeros((100, 100, 3), np.uint8)
    turned = rotate(image, 45)
    assert tuple(turned[0, 0]) == (255, 255, 255)


def test_crop_takes_fractions_of_the_image():
    image = np.zeros((100, 200, 3), np.uint8)
    assert crop(image, (0.0, 0.0, 0.5, 1.0)).shape[:2] == (100, 100)


def test_degenerate_crop_is_ignored():
    image = np.zeros((100, 100, 3), np.uint8)
    assert crop(image, (0.5, 0.5, 0.5, 0.5)) is image


def test_backwards_drag_still_produces_a_box():
    assert normalize_box((0.8, 0.9, 0.2, 0.1)) == (0.2, 0.1, 0.8, 0.9)


def test_crop_halves_the_traced_width(square_image):
    """Cropping changes what 'fit to width' refers to: the cropped piece."""
    wide = np.full((200, 400, 3), 255, np.uint8)
    wide[:200, :200] = square_image

    full = run(wide, TraceParams(width_mm=400.0, fit_arcs=False))
    left = run(wide, TraceParams(width_mm=400.0, fit_arcs=False, crop=(0, 0, 0.5, 1)))

    # Same shape either way, but the crop is half as wide, so at the same
    # target width every millimetre covers half as many pixels.
    assert left.bounds.width == pytest.approx(full.bounds.width * 2, abs=1.0)


def test_ninety_degree_rotation_swaps_the_bounding_box(square_image):
    tall = np.full((200, 200, 3), 255, np.uint8)
    cv2.rectangle(tall, (60, 20), (139, 179), (0, 0, 0), -1)

    upright = run(tall, TraceParams(width_mm=200.0, fit_arcs=False)).bounds
    turned = run(
        tall, TraceParams(width_mm=200.0, fit_arcs=False, rotate_deg=90)
    ).bounds
    assert turned.width == pytest.approx(upright.height, abs=2.0)
    assert turned.height == pytest.approx(upright.width, abs=2.0)


def test_rotation_widens_the_bounding_box_at_a_fixed_scale(square_image):
    """A square turned 45 degrees spans its diagonal.

    Measured in DPI mode: 'fit to width' would rescale the enlarged canvas and
    hide the effect, since rotation grows the canvas by the same factor.
    """
    fixed = TraceParams(size_mode="dpi", dpi=25.4, fit_arcs=False)
    upright = run(square_image, fixed).bounds
    turned = run(
        square_image,
        TraceParams(size_mode="dpi", dpi=25.4, fit_arcs=False, rotate_deg=45),
    ).bounds
    assert turned.width == pytest.approx(upright.width * np.sqrt(2), rel=0.05)


def test_params_drop_a_crop_that_covers_everything():
    assert TraceParams(crop=(0.0, 0.0, 1.0, 1.0)).normalized().crop is None


# --- discarded contours ----------------------------------------------------


def test_specks_are_reported_not_silently_dropped(square_image):
    speckled = square_image.copy()
    speckled[5:8, 5:8] = 0

    result = run(speckled, TraceParams(width_mm=100.0, min_area_mm2=5.0))
    assert result.path_count == 1
    assert len(result.discarded) == 1
    assert "1 dropped" in result.summary()


def test_nothing_is_discarded_when_the_filter_is_off(square_image):
    result = run(square_image, TraceParams(width_mm=100.0, min_area_mm2=0.0))
    assert result.discarded == []


def test_discarded_contours_are_in_millimetres(square_image):
    """They are drawn alongside the kept paths, so they share a coordinate space."""
    speckled = square_image.copy()
    speckled[5:8, 5:8] = 0

    result = run(speckled, TraceParams(width_mm=100.0, min_area_mm2=5.0))
    speck = result.discarded[0].outer
    # The speck sits near the image's top-left, which is high Y after the flip.
    assert speck[:, 1].max() > result.bounds.max_y
