"""Finish quality: supersampling, corner-aware smoothing, straightening."""

from __future__ import annotations

import cv2
import ezdxf
import numpy as np
import pytest

from img2dxf.arcfit import circle_points, flatten_ring
from img2dxf.detail import MAX_FACTOR, resolve_detail
from img2dxf.dxfwrite import write_dxf
from img2dxf.params import TraceParams
from img2dxf.pipeline import run
from img2dxf.straighten import (
    effective_tolerance,
    straighten_ring,
    turn_coherence,
)
from img2dxf.trace import find_corners, smooth_ring

# --- supersampling ---------------------------------------------------------


@pytest.mark.parametrize(
    "width,height,expected",
    [(155, 50, 4), (620, 200, 3), (1500, 500, 1), (3000, 2000, 1), (40, 40, 4)],
)
def test_auto_detail_scales_small_images_only(width, height, expected):
    assert resolve_detail(width, height, 0) == expected


def test_explicit_detail_overrides_auto():
    assert resolve_detail(155, 50, 2) == 2
    assert resolve_detail(3000, 2000, 3) == 3


def test_detail_is_capped():
    assert resolve_detail(10, 10, 0) == MAX_FACTOR
    assert resolve_detail(10, 10, 99) == MAX_FACTOR


def test_supersampling_does_not_change_the_physical_size(square_image):
    """px_per_mm comes from the enlarged image, so millimetres are unaffected."""
    plain = run(square_image, TraceParams(width_mm=200.0, detail=1))
    fine = run(square_image, TraceParams(width_mm=200.0, detail=4))

    assert fine.detail_factor == 4
    assert fine.image_size_px[0] == plain.image_size_px[0] * 4
    assert fine.bounds.width == pytest.approx(plain.bounds.width, abs=1.0)


def test_supersampled_circle_is_still_recognised(tmp_path):
    """The arc tolerance floor must be measured in source pixels, not upscaled
    ones, or a supersampled circle stops being detected as a circle."""
    image = np.full((300, 300, 3), 255, np.uint8)
    cv2.circle(image, (150, 150), 100, (0, 0, 0), -1)

    params = TraceParams(width_mm=300.0, min_area_mm2=0.1, detail=4)
    result = run(image, params)
    doc = ezdxf.readfile(write_dxf(result.paths, tmp_path / "c.dxf", params))

    circles = doc.modelspace().query("CIRCLE")
    assert len(circles) == 1
    assert circles[0].dxf.radius == pytest.approx(100.0, abs=1.5)


# --- the measurement that justifies the whole exercise ---------------------


def logo_image(scale: int, aa: bool = True) -> np.ndarray:
    height, width = 200 * scale, 620 * scale
    image = np.full((height, width, 3), 255, np.uint8)
    cv2.putText(
        image, "LOGO", (20 * scale, 150 * scale), cv2.FONT_HERSHEY_DUPLEX,
        4.0 * scale, (0, 0, 0), 10 * scale,
        lineType=cv2.LINE_AA if aa else cv2.LINE_8,
    )
    return image


def outline_of(result) -> list[np.ndarray]:
    """Every ring as a dense polyline, with fitted arcs expanded."""
    rings = []
    for path in result.paths:
        for index, ring in enumerate(path.rings()):
            circle = path.circles.get(index)
            if circle is not None:
                rings.append(circle_points(circle, 360))
            else:
                rings.append(flatten_ring(ring, path.bulges.get(index), 48))
    return rings


def distance_to_outline(points: np.ndarray, rings: list[np.ndarray]) -> np.ndarray:
    """Point-to-segment distance, not point-to-vertex.

    Measuring to the nearest vertex would punish the very thing this change
    achieves — describing the same edge with fewer, better placed points.
    """
    best = np.full(len(points), np.inf)
    for ring in rings:
        start = ring
        end = np.roll(ring, -1, axis=0)
        edge = end - start
        length2 = (edge ** 2).sum(axis=1)
        length2[length2 == 0] = 1e-12
        offset = points[:, None, :] - start[None, :, :]
        t = np.clip((offset * edge[None]).sum(axis=2) / length2[None], 0, 1)
        closest = start[None] + t[:, :, None] * edge[None]
        best = np.minimum(
            best, np.linalg.norm(points[:, None, :] - closest, axis=2).min(axis=1)
        )
    return best


@pytest.fixture(scope="module")
def ground_truth():
    """The artwork traced at 8x, as a stand-in for the true outline."""
    result = run(
        logo_image(8),
        TraceParams(width_mm=620.0, simplify_mm=0.0, fit_arcs=False,
                    min_area_mm2=0.0, detail=1, straighten_mm=0.0),
    )
    return np.vstack([ring for p in result.paths for ring in p.rings()])


def rms_error(image, truth, **kw) -> tuple[float, int]:
    result = run(image, TraceParams(width_mm=620.0, min_area_mm2=0.0, **kw))
    distances = distance_to_outline(truth, outline_of(result))
    return float(np.sqrt((distances ** 2).mean())), result.vertex_count


def test_finishing_is_more_accurate_with_fewer_vertices(ground_truth):
    """The headline claim, measured against the original artwork."""
    work = cv2.resize(logo_image(8), (620, 200), interpolation=cv2.INTER_AREA)

    before, before_verts = rms_error(work, ground_truth, detail=1, straighten_mm=0.0)
    after, after_verts = rms_error(work, ground_truth)

    assert after < before / 1.5, f"{before:.3f} -> {after:.3f} mm"
    assert after_verts < before_verts


def test_small_logos_gain_the_most(ground_truth):
    """The case supersampling exists for: too few pixels to trace cleanly."""
    small = cv2.resize(logo_image(8), (155, 50), interpolation=cv2.INTER_AREA)

    before, _ = rms_error(small, ground_truth, detail=1, straighten_mm=0.0)
    after, _ = rms_error(small, ground_truth)
    assert after < before / 2.0, f"{before:.3f} -> {after:.3f} mm"


# --- corner-aware smoothing ------------------------------------------------


SQUARE = np.array([[0, 0], [100, 0], [100, 100], [0, 100]], dtype=float)


def test_every_corner_of_a_square_is_found():
    assert find_corners(SQUARE, 40.0).all()


def test_a_gentle_curve_has_no_corners():
    angles = np.linspace(0, 2 * np.pi, 60, endpoint=False)
    circle = np.column_stack([50 * np.cos(angles), 50 * np.sin(angles)])
    assert not find_corners(circle, 40.0).any()


@pytest.mark.parametrize("passes", [1, 2, 3])
def test_smoothing_holds_sharp_corners_exactly(passes):
    """Plain Chaikin pulled a right angle in by 25 px on this square."""
    smoothed = smooth_ring(SQUARE.copy(), passes, 40.0)
    moved = np.min(
        np.linalg.norm(SQUARE[:, None, :] - smoothed[None, :, :], axis=2), axis=1
    )
    assert moved.max() < 1e-9


def test_smoothing_still_softens_curves():
    angles = np.linspace(0, 2 * np.pi, 24, endpoint=False)
    circle = np.column_stack([50 * np.cos(angles), 50 * np.sin(angles)])
    smoothed = smooth_ring(circle.copy(), 2, 40.0)
    assert len(smoothed) > len(circle)


def test_smoothing_a_shape_with_both_keeps_the_corner_and_softens_the_rest():
    """A half-disc: the flat edge's two corners hold, the arc smooths."""
    angles = np.linspace(0, np.pi, 40)
    ring = np.vstack([
        np.column_stack([50 * np.cos(angles), 50 * np.sin(angles)]),
    ])
    smoothed = smooth_ring(ring.copy(), 2, 40.0)

    for corner in (ring[0], ring[-1]):
        assert np.linalg.norm(smoothed - corner, axis=1).min() < 1e-9
    assert len(smoothed) > len(ring)


# --- straightening ---------------------------------------------------------


def staircase_edge(length=40.0, count=41, step=0.5, width=10.0) -> np.ndarray:
    """A closed ring of two straight edges, each carrying a pixel staircase."""
    ys = np.linspace(0, length, count)
    wobble = step * ((np.arange(count) % 2) * 2 - 1)
    return np.vstack([
        np.column_stack([wobble, ys]),
        np.column_stack([width + wobble[::-1], ys[::-1]]),
    ])


def test_turn_coherence_separates_a_staircase_from_an_arc():
    angles = np.linspace(0, 2 * np.pi, 200, endpoint=False)
    circle = np.column_stack([50 * np.cos(angles), 50 * np.sin(angles)])

    assert turn_coherence(staircase_edge()[:41]) < 0.1
    assert turn_coherence(circle[:20]) > 0.9


def test_a_staircase_collapses_to_its_line():
    ring = staircase_edge()
    assert len(straighten_ring(ring, 1.0, 2.0)) < len(ring) / 10


@pytest.mark.parametrize("radius", [20.0, 50.0, 200.0, 1000.0])
def test_curves_are_never_flattened(radius):
    """Radius-invariant: an arc of any size bends coherently, so it is spared."""
    angles = np.linspace(0, 2 * np.pi, 200, endpoint=False)
    circle = np.column_stack([radius * np.cos(angles), radius * np.sin(angles)])
    assert len(straighten_ring(circle, 1.0, 2.0)) == len(circle)


def test_straightening_stays_within_its_budget():
    ring = staircase_edge()
    result = straighten_ring(ring, 1.0, 2.0)
    assert distance_to_outline(ring, [result]).max() <= 1.0


def test_runs_shorter_than_the_minimum_are_left_alone():
    # Every run in this ring is 1 mm, including the spans joining the edges.
    ring = staircase_edge(length=1.0, count=21, step=0.05, width=1.0)
    assert len(straighten_ring(ring, 1.0, 5.0)) == len(ring)


def test_straightening_can_be_switched_off():
    ring = staircase_edge()
    assert len(straighten_ring(ring, 0.0, 2.0)) == len(ring)
    assert TraceParams(straighten_mm=0.0).normalized().straighten_enabled is False


def test_tolerance_is_floored_at_one_source_pixel():
    """The ripple being removed is a pixel tall, so a finer budget cannot work."""
    # 4 px per mm, no supersampling: one pixel is 0.25 mm.
    assert effective_tolerance(0.05, 4.0, 1) == pytest.approx(0.25)
    # Supersampled 4x, so px_per_mm is 16 but a source pixel is still 0.25 mm.
    assert effective_tolerance(0.05, 16.0, 4) == pytest.approx(0.25)
    # A user asking for more than the floor gets what they asked for.
    assert effective_tolerance(0.8, 4.0, 1) == pytest.approx(0.8)


def test_a_ring_is_never_reduced_below_a_shape():
    triangle = np.array([[0, 0], [10, 0], [5, 8]], dtype=float)
    assert len(straighten_ring(triangle, 10.0, 0.1)) >= 3


def test_a_noisy_curve_is_not_chamfered():
    """Coherence alone let this through, flattening the shoulders of O and G.

    A staircase laid over a real curve adds so much total turning that the
    coherence ratio drops below its threshold, so the absolute net turn has to
    catch it: a curve still ends up pointing somewhere else.
    """
    angles = np.linspace(0, np.pi / 2, 60)
    curve = np.column_stack([50 * np.cos(angles), 50 * np.sin(angles)])
    noise = 0.4 * ((np.arange(60) % 2) * 2 - 1)
    noisy = curve + np.column_stack([noise * np.cos(angles), noise * np.sin(angles)])

    from img2dxf.straighten import is_straight

    assert not is_straight(noisy)
    # ...while the same noise on an actually straight edge still flattens.
    assert is_straight(staircase_edge()[:41])


def test_bend_ignores_a_staircase_but_sees_an_arc():
    """Summed per-vertex turns cancel only for an even number of steps.

    An odd one left a whole phantom step of bend, so the measure fits a line
    to each half of the run instead and compares their directions.
    """
    from img2dxf.straighten import bend_deg

    for count in (40, 41):  # even and odd, both must read as straight
        ys = np.linspace(0, 40, count)
        wobble = 0.5 * ((np.arange(count) % 2) * 2 - 1)
        assert bend_deg(np.column_stack([wobble, ys])) < 1.0

    quarter = np.linspace(0, np.pi / 2, 40)
    arc = np.column_stack([50 * np.cos(quarter), 50 * np.sin(quarter)])
    assert bend_deg(arc) == pytest.approx(45.0, abs=2.0)
