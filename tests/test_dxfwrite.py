import ezdxf
import pytest

from img2dxf.dxfwrite import INSUNITS_MM, write_dxf
from img2dxf.params import TraceParams
from img2dxf.pipeline import run


def export(image, params, tmp_path, name="out.dxf"):
    result = run(image, params)
    path = write_dxf(result.paths, tmp_path / name, params)
    return result, ezdxf.readfile(path)


def polylines(doc):
    return list(doc.modelspace().query("LWPOLYLINE POLYLINE"))


def test_file_declares_millimetres(square_image, tmp_path):
    _, doc = export(square_image, TraceParams(), tmp_path)
    assert doc.header["$INSUNITS"] == INSUNITS_MM


@pytest.mark.parametrize(
    "version,expected", [("R2010", "LWPOLYLINE"), ("R2000", "LWPOLYLINE"), ("R12", "POLYLINE")]
)
def test_entity_type_matches_dxf_version(square_image, tmp_path, version, expected):
    params = TraceParams(dxf_version=version)
    _, doc = export(square_image, params, tmp_path, f"{version}.dxf")
    entities = polylines(doc)
    assert entities and all(e.dxftype() == expected for e in entities)


def test_exported_square_measures_the_requested_size(square_image, tmp_path):
    """The end-to-end scale check: 100 px square, 200 px image, fitted to 100 mm."""
    _, doc = export(square_image, TraceParams(width_mm=100.0, simplify_mm=0.1), tmp_path)
    [entity] = polylines(doc)
    points = [(p[0], p[1]) for p in entity.get_points("xy")]
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    assert max(xs) - min(xs) == pytest.approx(50.0, abs=0.6)
    assert max(ys) - min(ys) == pytest.approx(50.0, abs=0.6)


def test_y_flip_survives_export(offset_square_image, tmp_path):
    """A shape at the image top must sit at high Y in the DXF, not low Y."""
    params = TraceParams(width_mm=200.0, mode="fixed", threshold=128)
    _, doc = export(offset_square_image, params, tmp_path)
    [entity] = polylines(doc)
    ys = [p[1] for p in entity.get_points("xy")]
    # Image is 200 px = 200 mm tall; the square occupies the top 50 px.
    assert max(ys) == pytest.approx(200.0, abs=1.0)
    assert min(ys) == pytest.approx(150.0, abs=1.0)


def test_ring_writes_outer_and_hole_as_closed_polylines(ring_image, tmp_path):
    _, doc = export(ring_image, TraceParams(min_area_mm2=0.1), tmp_path)
    entities = polylines(doc)
    assert len(entities) == 2
    assert all(e.closed if e.dxftype() == "LWPOLYLINE" else e.is_closed for e in entities)


def test_single_level_uses_one_named_layer(square_image, tmp_path):
    params = TraceParams(layer_name="ETCH")
    _, doc = export(square_image, params, tmp_path)
    assert {e.dxf.layer for e in polylines(doc)} == {"ETCH"}


def test_posterize_splits_tones_across_layers(gradient_image, tmp_path):
    params = TraceParams(mode="posterize", levels=4, min_area_mm2=0.1)
    _, doc = export(gradient_image, params, tmp_path)
    layers = {e.dxf.layer for e in polylines(doc)}
    assert layers == {"CUT_TONE_0", "CUT_TONE_1", "CUT_TONE_2"}
    # Distinct colours so colour-driven laser software can separate them.
    colors = {doc.layers.get(name).color for name in layers}
    assert len(colors) == len(layers)


def test_empty_result_still_writes_a_valid_file(tmp_path):
    import numpy as np

    blank = np.full((50, 50, 3), 255, np.uint8)
    result, doc = export(blank, TraceParams(), tmp_path)
    assert result.path_count == 0
    assert polylines(doc) == []
    assert "CUT" in doc.layers


def test_r12_omits_unsupported_units_header(square_image, tmp_path):
    """R12 has no $INSUNITS; writing it anyway makes ezdxf complain."""
    from img2dxf.dxfwrite import units_are_declared

    _, doc = export(square_image, TraceParams(dxf_version="R12"), tmp_path, "r12.dxf")
    assert "$INSUNITS" not in doc.header
    assert units_are_declared("R12") is False
    assert units_are_declared("R2010") is True
