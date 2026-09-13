"""The calibration piece: it is only useful if its dimensions are right."""

from __future__ import annotations

import ezdxf
import numpy as np
import pytest

from img2dxf.calibrate import (
    FEATURES,
    PLATE_HEIGHT_MM,
    PLATE_WIDTH_MM,
    build_image,
    calibration_params,
    checklist,
    measure,
    write,
)
from img2dxf.pipeline import run

#: The artwork is anti-aliased, so a traced edge lands on its midpoint rather
#: than exactly on the nominal size. A tenth of a millimetre covers that.
TOLERANCE_MM = 0.15


@pytest.fixture(scope="module")
def traced():
    return run(build_image(), calibration_params())


def test_the_plate_is_the_size_it_claims(traced):
    assert traced.bounds.width == pytest.approx(PLATE_WIDTH_MM, abs=TOLERANCE_MM)
    assert traced.bounds.height == pytest.approx(PLATE_HEIGHT_MM, abs=TOLERANCE_MM)


def test_the_plate_is_one_part_with_four_openings(traced):
    """One outline to cut out, with holes inside it — the shape of a real job."""
    assert traced.path_count == 1
    assert len(traced.paths[0].holes) == 4


def test_every_advertised_feature_is_actually_there(traced):
    """The checklist must not ask for something the file does not contain."""
    sizes = measure(traced)
    for feature in FEATURES:
        closest = min(sizes.values(), key=lambda v: abs(v - feature.nominal_mm))
        assert closest == pytest.approx(feature.nominal_mm, abs=TOLERANCE_MM), (
            f"{feature.name} ({feature.what_to_measure}) is missing or wrong"
        )


def test_the_round_holes_come_out_as_circles(traced, tmp_path):
    """A calibration hole traced as a polygon would measure differently
    across the flats than across the corners."""
    path, _ = write(tmp_path / "cal.dxf")
    doc = ezdxf.readfile(path)
    diameters = sorted(e.dxf.radius * 2 for e in doc.modelspace().query("CIRCLE"))

    assert len(diameters) == 2
    assert diameters[0] == pytest.approx(6.0, abs=TOLERANCE_MM)
    assert diameters[1] == pytest.approx(20.0, abs=TOLERANCE_MM)


def test_nothing_that_moves_an_edge_is_switched_on():
    """An off-size part must mean the machine, not a finishing pass."""
    params = calibration_params()
    assert params.kerf_mm == 0.0
    assert params.straighten_mm == 0.0
    assert params.smooth == 0
    assert params.auto_levels is False


def test_the_checklist_reports_what_is_in_the_file(traced):
    """Nominal round numbers would be a lie by a few hundredths."""
    text = checklist(traced)
    assert "80.00 mm" not in text  # the plate is 79.97 as drawn
    assert "79.9" in text or "80.0" in text
    for feature in FEATURES:
        assert feature.name in text


def test_the_checklist_works_without_a_trace():
    assert "Outer plate" in checklist()


def test_the_artwork_is_dark_on_white(traced):
    """A plate to cut out, not a white shape on black."""
    image = build_image()
    corner = image[0, 0]
    assert tuple(corner) == (255, 255, 255)
    assert image.mean() < 200  # mostly plate
