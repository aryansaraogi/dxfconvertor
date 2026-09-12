"""Tiling, the bed fit check, and image adjustments."""

from __future__ import annotations

import numpy as np
import pytest

from img2dxf.geometry import Path, bounds_of, translate, width_for_reference
from img2dxf.params import TraceParams
from img2dxf.pipeline import run
from img2dxf.preprocess import auto_levels, prepare
from img2dxf.tile import tile_paths


def unit_square(size: float = 10.0) -> Path:
    path = Path(
        np.array([[0, 0], [size, 0], [size, size], [0, size]], dtype=float)
    )
    path.circles[0] = (size / 2, size / 2, size / 3)
    return path


# --- tiling ----------------------------------------------------------------


def test_grid_produces_one_path_per_cell():
    assert len(tile_paths([unit_square()], 3, 2, 2.0)) == 6


def test_single_copy_is_left_alone():
    paths = [unit_square()]
    assert tile_paths(paths, 1, 1, 5.0) is paths


def test_bounding_box_grows_by_the_pitch():
    box = bounds_of(tile_paths([unit_square(10.0)], 3, 2, 2.0))
    # 3 cells of 10 plus 2 gaps of 2; 2 cells of 10 plus 1 gap of 2.
    assert box.width == pytest.approx(34.0)
    assert box.height == pytest.approx(22.0)


def test_each_copy_gets_its_own_circle_centre():
    """The deep-copy trap: a shallow copy stacks every circle on the first."""
    tiles = tile_paths([unit_square(10.0)], 3, 2, 2.0)
    centres = {tuple(np.round(c[:2], 3)) for p in tiles for c in p.circles.values()}
    assert len(centres) == 6


def test_translate_does_not_disturb_the_original():
    original = unit_square()
    moved = translate(original, 100.0, 50.0)
    assert original.circles[0] == (5.0, 5.0, pytest.approx(10 / 3))
    assert moved.circles[0][0] == pytest.approx(105.0)
    assert moved.outer[0][0] == pytest.approx(100.0)


def test_translate_copies_bulges_rather_than_sharing_them():
    original = unit_square()
    original.bulges[0] = np.array([0.5, 0.0, 0.0, 0.0])
    moved = translate(original, 1.0, 1.0)
    moved.bulges[0][0] = 9.0
    assert original.bulges[0][0] == pytest.approx(0.5)


def test_tiling_runs_end_to_end(square_image):
    one = run(square_image, TraceParams(width_mm=100.0, fit_arcs=False))
    many = run(
        square_image,
        TraceParams(width_mm=100.0, fit_arcs=False, copies_x=2, copies_y=2,
                    tile_gap_mm=5.0),
    )
    assert many.path_count == one.path_count * 4
    assert many.bounds.width == pytest.approx(one.bounds.width * 2 + 5.0, abs=0.1)


# --- bed fit ---------------------------------------------------------------


def test_no_bed_configured_means_no_complaint(square_image):
    result = run(square_image, TraceParams(width_mm=100.0))
    assert result.fits_bed is True
    assert result.bed_size_mm is None
    assert "FIT" not in result.summary()


def test_job_within_the_bed_is_fine(square_image):
    result = run(
        square_image,
        TraceParams(width_mm=100.0, bed_width_mm=400.0, bed_height_mm=300.0),
    )
    assert result.fits_bed is True
    assert result.bed_size_mm == (400.0, 300.0)


def test_oversized_job_is_flagged_in_the_summary(square_image):
    result = run(
        square_image,
        TraceParams(width_mm=500.0, bed_width_mm=100.0, bed_height_mm=100.0),
    )
    assert result.fits_bed is False
    assert "DOES NOT FIT" in result.summary()


def test_tiling_is_measured_against_the_bed(square_image):
    """One copy fits; the grid of them must not silently pass."""
    fits = TraceParams(width_mm=90.0, bed_width_mm=100.0, bed_height_mm=100.0)
    assert run(square_image, fits).fits_bed is True

    tiled = TraceParams(
        width_mm=90.0, bed_width_mm=100.0, bed_height_mm=100.0,
        copies_x=3, copies_y=3,
    )
    assert run(square_image, tiled).fits_bed is False


# --- scale by reference ----------------------------------------------------


def test_reference_width_scales_the_job():
    # 600 px wide image; a feature spanning 300 px is really 25 mm.
    width_mm = width_for_reference(600, 300.0, 25.0)
    assert width_mm == pytest.approx(50.0)


@pytest.mark.parametrize("measured,target", [(0.0, 10.0), (10.0, 0.0), (-5.0, 10.0)])
def test_reference_rejects_impossible_input(measured, target):
    with pytest.raises(ValueError):
        width_for_reference(600, measured, target)


def test_reference_scaling_survives_the_whole_pipeline(square_image):
    """Declare the square's true size, then confirm it exports at that size."""
    first = run(square_image, TraceParams(width_mm=200.0, fit_arcs=False))
    measured_px = first.bounds.width * first.px_per_mm

    width_mm = width_for_reference(first.image_size_px[0], measured_px, 25.0)
    rescaled = run(
        square_image, TraceParams(width_mm=width_mm, fit_arcs=False)
    )
    assert rescaled.bounds.width == pytest.approx(25.0, abs=0.05)


# --- image adjustments -----------------------------------------------------


def ramp(low=80, high=160) -> np.ndarray:
    return np.tile(np.linspace(low, high, 200, dtype=np.uint8), (50, 1))


def test_adjustments_are_off_by_default():
    image = ramp()
    assert np.array_equal(prepare(image, TraceParams().normalized()), image)


def test_auto_levels_widens_a_flat_range():
    stretched = auto_levels(ramp())
    assert stretched.min() < 5 and stretched.max() > 250


def test_auto_levels_ignores_outliers():
    """One stray black pixel must not define the black point."""
    image = ramp(100, 150).copy()
    image[0, 0] = 0
    stretched = auto_levels(image)
    assert stretched.max() > 250


def test_gamma_below_one_darkens():
    image = ramp()
    darker = prepare(image, TraceParams(gamma=0.5).normalized())
    assert darker.mean() < image.mean()


def test_gamma_above_one_lightens():
    image = ramp()
    lighter = prepare(image, TraceParams(gamma=2.0).normalized())
    assert lighter.mean() > image.mean()


def test_brightness_shifts_the_mean():
    image = ramp()
    brighter = prepare(image, TraceParams(brightness=40).normalized())
    assert brighter.mean() == pytest.approx(image.mean() + 40, abs=1.0)


def test_contrast_pivots_about_mid_grey():
    """Raising contrast must not also brighten the whole image."""
    image = ramp(100, 150)
    harder = prepare(image, TraceParams(contrast=2.0).normalized())
    assert harder.max() - harder.min() > int(image.max()) - int(image.min())
    assert harder.mean() == pytest.approx(
        128 + (image.mean() - 128) * 2, abs=2.0
    )


def test_adjustments_can_rescue_a_low_contrast_scan():
    """A faint ramp thresholds into nothing until levels are stretched."""
    faint = np.full((120, 120, 3), 200, np.uint8)
    faint[30:90, 30:90] = 178  # a barely-there square

    plain = run(faint, TraceParams(mode="fixed", threshold=100, width_mm=60.0))
    helped = run(
        faint,
        TraceParams(mode="fixed", threshold=100, width_mm=60.0, auto_levels=True),
    )
    assert plain.path_count == 0
    assert helped.path_count == 1
