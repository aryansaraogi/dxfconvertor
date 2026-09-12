import numpy as np
import pytest

from img2dxf.params import TraceParams
from img2dxf.pipeline import run
from img2dxf.trace import chaikin


def test_square_traces_to_requested_size(square_image):
    # 200 px wide image fitted to 100 mm, with a 100 px square in the middle.
    result = run(square_image, TraceParams(width_mm=100.0, simplify_mm=0.1))
    assert result.path_count == 1
    assert result.bounds.width == pytest.approx(50.0, abs=0.6)
    assert result.bounds.height == pytest.approx(50.0, abs=0.6)


def test_ring_produces_one_path_with_one_hole(ring_image):
    result = run(ring_image, TraceParams(width_mm=100.0, min_area_mm2=0.1))
    assert result.path_count == 1
    assert len(result.paths[0].holes) == 1


def test_holes_can_be_disabled(ring_image):
    result = run(ring_image, TraceParams(width_mm=100.0, keep_holes=False))
    assert result.paths[0].holes == []


def test_min_area_despeckles(square_image):
    speckled = square_image.copy()
    speckled[5:8, 5:8] = 0  # a 3x3 px speck, far below the threshold
    keep_all = run(speckled, TraceParams(width_mm=100.0, min_area_mm2=0.0))
    despeckled = run(speckled, TraceParams(width_mm=100.0, min_area_mm2=5.0))
    assert keep_all.path_count == 2
    assert despeckled.path_count == 1


def test_invert_traces_the_background(square_image):
    normal = run(square_image, TraceParams(mode="fixed", threshold=128))
    inverted = run(square_image, TraceParams(mode="fixed", threshold=128, invert=True))
    # The square is ~25% of the canvas, so its inverse is much larger.
    assert inverted.bounds.width > normal.bounds.width


def test_posterize_emits_one_level_per_tone(gradient_image):
    result = run(gradient_image, TraceParams(mode="posterize", levels=4, min_area_mm2=0.1))
    assert len(result.masks) == 3  # levels - 1: the lightest band is paper
    assert result.level_count == 3


def test_simplify_reduces_vertices(ring_image):
    detailed = run(ring_image, TraceParams(simplify_mm=0.01))
    coarse = run(ring_image, TraceParams(simplify_mm=1.0))
    assert coarse.vertex_count < detailed.vertex_count


def test_smoothing_doubles_vertices_per_pass(square_image):
    plain = run(square_image, TraceParams(simplify_mm=0.5, smooth=0))
    smoothed = run(square_image, TraceParams(simplify_mm=0.5, smooth=2))
    assert smoothed.vertex_count == plain.vertex_count * 4


def test_edges_mode_finds_outlines(square_image):
    result = run(square_image, TraceParams(mode="edges", min_area_mm2=0.0))
    assert result.path_count >= 1


def test_blank_image_yields_no_paths():
    blank = np.full((100, 100, 3), 255, np.uint8)
    result = run(blank, TraceParams())
    assert result.path_count == 0
    assert result.bounds is None
    assert "No paths" in result.summary()


def test_chaikin_keeps_ring_inside_original():
    ring = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], float)
    out = chaikin(ring)
    assert len(out) == 8
    assert out[:, 0].min() >= 0 and out[:, 0].max() <= 10
