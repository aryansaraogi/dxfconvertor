"""Kerf compensation: the sign convention is what these tests pin down."""

from __future__ import annotations

import ezdxf
import pytest

from img2dxf.dxfwrite import write_dxf
from img2dxf.params import TraceParams
from img2dxf.pipeline import run

# The square fixture is 100 px inside a 200 px canvas; fitting to 200 mm makes
# one pixel one millimetre, so traced sizes are readable straight off.
PIXEL_PER_MM = TraceParams(width_mm=200.0, simplify_mm=0.1, fit_arcs=False)


def traced_width(image, **overrides) -> float:
    from dataclasses import replace

    return run(image, replace(PIXEL_PER_MM, **overrides)).bounds.width


def test_no_kerf_leaves_geometry_alone(square_image):
    plain = traced_width(square_image)
    ignored = traced_width(square_image, kerf_mm=5.0, kerf_side="none")
    assert ignored == pytest.approx(plain)


def test_outside_grows_the_part_by_one_kerf(square_image):
    """Cutting outside the line must leave the part its drawn size."""
    plain = traced_width(square_image)
    grown = traced_width(square_image, kerf_mm=1.0, kerf_side="outside")
    assert grown == pytest.approx(plain + 1.0, abs=0.05)


def test_inside_shrinks_the_part_by_one_kerf(square_image):
    plain = traced_width(square_image)
    shrunk = traced_width(square_image, kerf_mm=1.0, kerf_side="inside")
    assert shrunk == pytest.approx(plain - 1.0, abs=0.05)


def test_hole_moves_opposite_to_its_outline(ring_image):
    """The whole point of kerf: a hole shrinks while its outline grows."""
    params = TraceParams(
        width_mm=200.0, min_area_mm2=0.1, fit_arcs=False, simplify_mm=0.1
    )
    before = run(ring_image, params).paths[0]
    after = run(
        ring_image,
        TraceParams(
            width_mm=200.0, min_area_mm2=0.1, fit_arcs=False, simplify_mm=0.1,
            kerf_mm=2.0, kerf_side="outside",
        ),
    ).paths[0]

    def span(ring):
        return ring[:, 0].max() - ring[:, 0].min()

    assert span(after.outer) > span(before.outer)
    assert span(after.holes[0]) < span(before.holes[0])


def test_kerf_survives_export(square_image, tmp_path):
    from dataclasses import replace

    params = replace(PIXEL_PER_MM, kerf_mm=1.0, kerf_side="outside")
    result = run(square_image, params)
    path = write_dxf(result.paths, tmp_path / "kerf.dxf", params)

    doc = ezdxf.readfile(path)
    [entity] = doc.modelspace().query("LWPOLYLINE")
    xs = [p[0] for p in entity.get_points("xy")]
    assert max(xs) - min(xs) == pytest.approx(51.0, abs=0.1)


def test_tone_levels_stay_separate(gradient_image):
    """Offsetting must not merge one tone's geometry onto another's layer."""
    params = TraceParams(
        mode="posterize", levels=4, min_area_mm2=0.1, fit_arcs=False,
        kerf_mm=0.5, kerf_side="outside",
    )
    result = run(gradient_image, params)
    assert result.level_count == 3


def test_sliver_thinner_than_the_kerf_disappears():
    """A feature the beam would consume entirely should not be emitted."""
    import cv2
    import numpy as np

    img = np.full((200, 200, 3), 255, np.uint8)
    cv2.rectangle(img, (20, 99), (180, 100), (0, 0, 0), -1)  # ~1 px tall

    params = TraceParams(width_mm=200.0, min_area_mm2=0.0, fit_arcs=False)
    assert run(img, params).path_count == 1

    eaten = run(
        img,
        TraceParams(
            width_mm=200.0, min_area_mm2=0.0, fit_arcs=False,
            kerf_mm=8.0, kerf_side="inside",
        ),
    )
    assert eaten.path_count == 0
