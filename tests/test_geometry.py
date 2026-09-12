import numpy as np
import pytest

from img2dxf.geometry import Path, bounds_of, pixels_per_mm, to_millimetres


def square_path(x0, y0, x1, y1) -> Path:
    return Path(np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=float))


def test_fit_width_sets_scale():
    assert pixels_per_mm(
        200, 100, size_mode="fit", width_mm=50.0, height_mm=None, dpi=96
    ) == pytest.approx(4.0)


def test_explicit_height_wins_over_width():
    assert pixels_per_mm(
        200, 100, size_mode="fit", width_mm=50.0, height_mm=10.0, dpi=96
    ) == pytest.approx(10.0)


def test_dpi_mode_uses_inches():
    assert pixels_per_mm(
        200, 100, size_mode="dpi", width_mm=50.0, height_mm=None, dpi=25.4
    ) == pytest.approx(1.0)


def test_scale_produces_requested_millimetres():
    paths = to_millimetres(
        [square_path(50, 50, 150, 150)], image_height_px=200, px_per_mm=10.0
    )
    box = bounds_of(paths)
    assert box.width == pytest.approx(10.0)
    assert box.height == pytest.approx(10.0)


def test_y_axis_is_flipped():
    """A shape at the top of the image must land at the top in DXF space."""
    paths = to_millimetres(
        [square_path(0, 0, 100, 50)], image_height_px=200, px_per_mm=10.0
    )
    box = bounds_of(paths)
    # Image rows 0-50 are near the top, i.e. high Y once flipped.
    assert box.max_y == pytest.approx(20.0)
    assert box.min_y == pytest.approx(15.0)


def test_center_origin_centres_on_zero():
    paths = to_millimetres(
        [square_path(50, 50, 150, 150)],
        image_height_px=200, px_per_mm=10.0, origin="center",
    )
    box = bounds_of(paths)
    assert (box.min_x + box.max_x) / 2 == pytest.approx(0.0)
    assert (box.min_y + box.max_y) / 2 == pytest.approx(0.0)


def test_holes_are_transformed_too():
    path = square_path(0, 0, 100, 100)
    path.holes.append(np.array([[25, 25], [75, 25], [75, 75], [25, 75]], float))
    [converted] = to_millimetres([path], image_height_px=100, px_per_mm=10.0)
    assert converted.holes[0].max() == pytest.approx(7.5)


def test_bounds_of_empty_is_none():
    assert bounds_of([]) is None


def test_zero_scale_is_rejected():
    with pytest.raises(ValueError):
        to_millimetres([square_path(0, 0, 1, 1)], image_height_px=10, px_per_mm=0)
