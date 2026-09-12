"""Tabs: the cut must stop short by exactly the requested amount."""

from __future__ import annotations

import ezdxf
import numpy as np
import pytest

from img2dxf.dxfwrite import write_dxf
from img2dxf.params import TraceParams
from img2dxf.pipeline import run
from img2dxf.tabs import open_segments, split_ring, total_length

SQUARE = np.array([[0, 0], [40, 0], [40, 40], [0, 40]], dtype=float)
PERIMETER = 160.0


def circle_ring(radius=20.0, count=200) -> np.ndarray:
    angles = np.linspace(0, 2 * np.pi, count, endpoint=False)
    return np.column_stack([radius * np.cos(angles), radius * np.sin(angles)])


def test_cut_length_is_perimeter_minus_the_gaps():
    segments = split_ring(SQUARE, 4, 0.5)
    assert len(segments) == 4
    assert total_length(segments) == pytest.approx(PERIMETER - 4 * 0.5)


@pytest.mark.parametrize("count,gap", [(1, 0.5), (3, 1.0), (8, 2.0)])
def test_cut_length_holds_for_any_count(count, gap):
    segments = split_ring(SQUARE, count, gap)
    assert total_length(segments) == pytest.approx(PERIMETER - count * gap)


def test_gaps_are_spaced_by_arc_length_not_vertex_index():
    """A circle's vertices bunch nowhere, but its segments must still be even."""
    segments = split_ring(circle_ring(), 4, 2.0)
    lengths = [total_length([segment]) for segment in segments]
    assert lengths == pytest.approx([lengths[0]] * 4, rel=0.02)


def test_segments_are_open_not_closed():
    for segment in split_ring(SQUARE, 4, 1.0):
        assert not np.allclose(segment[0], segment[-1])


def test_zero_count_or_width_leaves_the_ring_closed():
    assert split_ring(SQUARE, 0, 1.0) is None
    assert split_ring(SQUARE, 4, 0.0) is None


def test_a_ring_too_small_for_its_tabs_stays_closed():
    """Losing a small part entirely is worse than letting it drop through."""
    tiny = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=float)
    assert split_ring(tiny, 4, 2.0) is None


def test_tab_count_is_reduced_rather_than_refused():
    """A ring that cannot afford 8 tabs should still get the ones it can."""
    small = np.array([[0, 0], [4, 0], [4, 4], [0, 4]], dtype=float)  # perimeter 16
    segments = split_ring(small, 8, 1.0)
    assert segments is not None
    assert 0 < len(segments) < 8


def test_open_segments_flattens_a_fitted_circle():
    """Tabs and arcs cannot coexist on one ring, so the circle is flattened."""
    segments = open_segments(SQUARE, None, (0.0, 0.0, 20.0), 3, 1.0)
    assert len(segments) == 3
    assert total_length(segments) == pytest.approx(2 * np.pi * 20.0 - 3.0, rel=0.01)


# --- end to end ------------------------------------------------------------


def export(image, params, tmp_path):
    result = run(image, params)
    return result, ezdxf.readfile(write_dxf(result.paths, tmp_path / "t.dxf", params))


def test_tabbed_export_writes_open_polylines(square_image, tmp_path):
    params = TraceParams(width_mm=200.0, simplify_mm=0.1, tab_count=4, tab_mm=1.0)
    _, doc = export(square_image, params, tmp_path)

    entities = doc.modelspace().query("LWPOLYLINE")
    assert len(entities) == 4
    assert not any(entity.closed for entity in entities)


def test_untabbed_export_is_still_one_closed_polyline(square_image, tmp_path):
    params = TraceParams(width_mm=200.0, simplify_mm=0.1, fit_arcs=False)
    _, doc = export(square_image, params, tmp_path)

    entities = doc.modelspace().query("LWPOLYLINE")
    assert len(entities) == 1
    assert entities[0].closed


def test_tabbed_circle_is_no_longer_a_circle_entity(ring_image, tmp_path):
    params = TraceParams(width_mm=100.0, min_area_mm2=0.1, tab_count=3, tab_mm=1.0)
    _, doc = export(ring_image, params, tmp_path)

    assert len(doc.modelspace().query("CIRCLE")) == 0
    assert len(doc.modelspace().query("LWPOLYLINE")) == 6  # 3 per ring, two rings


def test_tabs_remove_material_from_the_cut(square_image, tmp_path):
    """The whole point: the tabbed file cuts less than the closed one."""

    def cut_length(params):
        _, doc = export(square_image, params, tmp_path)
        total = 0.0
        for entity in doc.modelspace().query("LWPOLYLINE"):
            points = np.array([(p[0], p[1]) for p in entity.get_points("xy")])
            if entity.closed:
                points = np.vstack([points, points[:1]])
            total += np.linalg.norm(np.diff(points, axis=0), axis=1).sum()
        return total

    plain = cut_length(TraceParams(width_mm=200.0, simplify_mm=0.1, fit_arcs=False))
    tabbed = cut_length(
        TraceParams(width_mm=200.0, simplify_mm=0.1, fit_arcs=False,
                    tab_count=4, tab_mm=2.0)
    )
    assert tabbed == pytest.approx(plain - 8.0, abs=0.05)


def test_summary_does_not_promise_arcs_it_will_not_write(ring_image):
    """Tabs flatten the rings they cut, so the status must not claim arcs."""
    plain = run(ring_image, TraceParams(width_mm=100.0, min_area_mm2=0.1))
    tabbed = run(
        ring_image,
        TraceParams(width_mm=100.0, min_area_mm2=0.1, tab_count=3, tab_mm=1.0),
    )

    assert "arcs" in plain.summary() and not plain.tabbed
    assert tabbed.tabbed
    assert "arcs" not in tabbed.summary()
    assert "tabbed" in tabbed.summary()
