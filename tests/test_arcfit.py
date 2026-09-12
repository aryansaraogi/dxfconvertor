"""Arc and circle fitting: accuracy first, compactness second."""

from __future__ import annotations

import math

import cv2
import ezdxf
import numpy as np
import pytest
from ezdxf.math import bulge_to_arc

from img2dxf.arcfit import fit_bulges, fit_circle
from img2dxf.dxfwrite import write_dxf
from img2dxf.params import TraceParams
from img2dxf.pipeline import run


def sampled_circle(cx=5.0, cy=7.0, radius=10.0, count=200) -> np.ndarray:
    angles = np.linspace(0, 2 * np.pi, count, endpoint=False)
    return np.column_stack([cx + radius * np.cos(angles), cy + radius * np.sin(angles)])


def rounded_rect(width=60.0, height=40.0, radius=10.0, per_corner=40) -> np.ndarray:
    corners = (
        (width - radius, height - radius, 0.0),
        (radius, height - radius, np.pi / 2),
        (radius, radius, np.pi),
        (width - radius, radius, 3 * np.pi / 2),
    )
    points = []
    for cx, cy, start in corners:
        angles = np.linspace(start, start + np.pi / 2, per_corner)
        points.append(
            np.column_stack([cx + radius * np.cos(angles), cy + radius * np.sin(angles)])
        )
    return np.vstack(points)


def expand(vertices: np.ndarray, bulges: np.ndarray, per_arc=120) -> np.ndarray:
    """Flatten a bulge polyline the way a CAD reader would."""
    pieces = []
    for index, bulge in enumerate(bulges):
        start = vertices[index]
        end = vertices[(index + 1) % len(vertices)]
        if not bulge:
            pieces.append(np.array([start, end]))
            continue
        centre, start_angle, end_angle, radius = bulge_to_arc(start, end, bulge)
        if end_angle < start_angle:
            end_angle += 2 * math.pi
        angles = np.linspace(start_angle, end_angle, per_arc)
        pieces.append(
            np.column_stack(
                [centre.x + radius * np.cos(angles), centre.y + radius * np.sin(angles)]
            )
        )
    return np.vstack(pieces)


def max_deviation(original: np.ndarray, curve: np.ndarray) -> float:
    distances = np.linalg.norm(original[:, None, :] - curve[None, :, :], axis=2)
    return float(distances.min(axis=1).max())


# --- circles ---------------------------------------------------------------


def test_circle_is_recognised():
    cx, cy, radius = fit_circle(sampled_circle(), 0.05)
    assert (cx, cy) == pytest.approx((5.0, 7.0))
    assert radius == pytest.approx(10.0)


def test_square_is_not_a_circle():
    """Every regular polygon has equidistant corners; sides give it away."""
    square = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=float)
    assert fit_circle(square, 1.0) is None


def test_half_arc_is_not_a_full_circle():
    assert fit_circle(sampled_circle()[:100], 0.05) is None


def test_traced_circle_exports_as_a_circle_entity(tmp_path):
    image = np.full((300, 300, 3), 255, np.uint8)
    cv2.circle(image, (150, 150), 100, (0, 0, 0), -1)

    params = TraceParams(width_mm=300.0, min_area_mm2=0.1)
    result = run(image, params)
    doc = ezdxf.readfile(write_dxf(result.paths, tmp_path / "circle.dxf", params))

    circles = doc.modelspace().query("CIRCLE")
    assert len(circles) == 1
    assert circles[0].dxf.radius == pytest.approx(100.0, abs=1.0)
    assert doc.modelspace().query("LWPOLYLINE POLYLINE").__len__() == 0


# --- arcs ------------------------------------------------------------------


def test_rounded_rectangle_becomes_four_arcs_and_four_lines():
    ring = rounded_rect()
    vertices, bulges = fit_bulges(ring, 0.05)
    assert len(vertices) == 8
    assert np.count_nonzero(bulges) == 4


def test_fitted_arcs_stay_within_tolerance():
    ring = rounded_rect()
    tol = 0.05
    vertices, bulges = fit_bulges(ring, tol)
    assert max_deviation(ring, expand(vertices, bulges)) <= tol * 1.05


def test_fitting_works_in_both_windings():
    """Contour winding flips with the Y axis, so direction must not matter."""
    for ring in (rounded_rect(), rounded_rect()[::-1]):
        vertices, bulges = fit_bulges(ring, 0.05)
        radii = []
        for index, bulge in enumerate(bulges):
            if bulge:
                *_, radius = bulge_to_arc(
                    vertices[index], vertices[(index + 1) % len(vertices)], bulge
                )
                radii.append(radius)
        assert radii == pytest.approx([10.0] * 4, abs=0.01)


def test_straight_polygon_gains_no_bulges():
    square = np.array(
        [[0, 0], [10, 0], [20, 0], [20, 10], [20, 20], [10, 20], [0, 20], [0, 10]],
        dtype=float,
    )
    assert fit_bulges(square, 0.05) is None


# --- end to end ------------------------------------------------------------


def test_arcs_cut_vertex_count_without_distorting(ring_image):
    plain = run(ring_image, TraceParams(width_mm=100.0, fit_arcs=False))
    fitted = run(ring_image, TraceParams(width_mm=100.0, fit_arcs=True))
    assert fitted.vertex_count < plain.vertex_count
    assert fitted.bounds.width == pytest.approx(plain.bounds.width, abs=0.5)


def test_fit_arcs_can_be_switched_off(ring_image):
    result = run(ring_image, TraceParams(fit_arcs=False))
    assert all(not p.circles and not p.bulges for p in result.paths)
