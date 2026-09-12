"""SVG export, and above all the Y axis, which points the other way."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import cv2
import ezdxf
import numpy as np
import pytest

from img2dxf.dxfwrite import write_dxf
from img2dxf.params import TraceParams
from img2dxf.pipeline import run
from img2dxf.svgwrite import build_svg, write_svg

SVG_NS = "{http://www.w3.org/2000/svg}"


def parse_points(data: str) -> list[tuple[float, float]]:
    """Read an SVG path's points.

    Written out properly because M/L carry two numbers and A carries seven,
    with the endpoint last — grabbing "the next two numbers" after an A picks
    up the radii instead, which silently passes a sloppy test.
    """
    tokens = re.findall(r"[MLAZ]|-?\d+\.?\d*", data)
    points: list[tuple[float, float]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in "ML":
            points.append((float(tokens[index + 1]), float(tokens[index + 2])))
            index += 3
        elif token == "A":
            points.append((float(tokens[index + 6]), float(tokens[index + 7])))
            index += 8
        else:
            index += 1
    return points


def svg_points(text: str) -> np.ndarray:
    root = ET.fromstring(text)
    points = []
    for element in root.iter(f"{SVG_NS}path"):
        points.extend(parse_points(element.get("d", "")))
    for element in root.iter(f"{SVG_NS}circle"):
        points.append((float(element.get("cx")), float(element.get("cy"))))
    return np.array(points, dtype=float)


def top_left_block() -> np.ndarray:
    """A block in the image's top-left, so orientation errors are visible."""
    image = np.full((200, 200, 3), 255, np.uint8)
    cv2.rectangle(image, (10, 10), (109, 59), (0, 0, 0), -1)
    return image


PARAMS = TraceParams(width_mm=200.0, simplify_mm=0.1, fit_arcs=False)


# --- the Y axis ------------------------------------------------------------


def two_blocks() -> np.ndarray:
    """A narrow block near the top, a wide bar near the bottom.

    Two shapes, not one: with a single shape the bounding box hugs it, so it
    sits near both the top and the bottom of its own box and an unflipped
    export still looks correct. Their *order* is what proves the flip.
    """
    image = np.full((200, 200, 3), 255, np.uint8)
    cv2.rectangle(image, (20, 10), (59, 39), (0, 0, 0), -1)     # narrow, top
    cv2.rectangle(image, (20, 150), (179, 189), (0, 0, 0), -1)  # wide, bottom
    return image


def test_y_axis_is_flipped_relative_to_dxf(tmp_path):
    """The top shape is high in DXF and low in SVG; the order must reverse."""
    result = run(two_blocks(), PARAMS)
    assert result.path_count == 2

    doc = ezdxf.readfile(write_dxf(result.paths, tmp_path / "o.dxf", PARAMS))
    dxf = {}
    for entity in doc.modelspace().query("LWPOLYLINE"):
        points = np.array([(p[0], p[1]) for p in entity.get_points("xy")])
        width = points[:, 0].max() - points[:, 0].min()
        dxf["narrow" if width < 100 else "wide"] = points[:, 1].mean()

    root = ET.fromstring(build_svg(result.paths, PARAMS, result.bounds))
    svg = {}
    for element in root.iter(f"{SVG_NS}path"):
        points = np.array(parse_points(element.get("d", "")))
        width = points[:, 0].max() - points[:, 0].min()
        svg["narrow" if width < 100 else "wide"] = points[:, 1].mean()

    # In DXF the top-of-image shape has the *greater* Y...
    assert dxf["narrow"] > dxf["wide"]
    # ...and in SVG the *lesser*, because SVG Y grows downwards.
    assert svg["narrow"] < svg["wide"]


def test_unflipping_the_svg_reproduces_the_dxf(tmp_path):
    """Undo the flip and every DXF point must land on an SVG point."""
    result = run(top_left_block(), PARAMS)
    doc = ezdxf.readfile(write_dxf(result.paths, tmp_path / "o.dxf", PARAMS))
    text = build_svg(result.paths, PARAMS, result.bounds)

    box = [float(v) for v in ET.fromstring(text).get("viewBox").split()]
    top = box[1] + box[3]

    svg = svg_points(text)
    svg[:, 1] = top - svg[:, 1]

    dxf = np.array(
        [
            (p[0], p[1])
            for entity in doc.modelspace().query("LWPOLYLINE")
            for p in entity.get_points("xy")
        ]
    )
    distances = np.linalg.norm(dxf[:, None, :] - svg[None, :, :], axis=2)
    assert distances.min(axis=1).max() < 0.001


# --- physical size ---------------------------------------------------------


def test_declared_size_is_in_millimetres():
    result = run(top_left_block(), PARAMS)
    root = ET.fromstring(build_svg(result.paths, PARAMS, result.bounds))

    assert root.get("width").endswith("mm")
    assert root.get("height").endswith("mm")
    width = float(root.get("width").removesuffix("mm"))
    # The traced block plus the margin on both sides.
    assert width == pytest.approx(result.bounds.width + 2.0, abs=0.1)


def test_viewbox_matches_the_declared_size():
    """User units must equal millimetres, or it opens at the wrong scale."""
    result = run(top_left_block(), PARAMS)
    root = ET.fromstring(build_svg(result.paths, PARAMS, result.bounds))

    box = [float(v) for v in root.get("viewBox").split()]
    assert box[2] == pytest.approx(float(root.get("width").removesuffix("mm")))
    assert box[3] == pytest.approx(float(root.get("height").removesuffix("mm")))


# --- entities --------------------------------------------------------------


def test_fitted_circles_become_circle_elements(ring_image):
    params = TraceParams(width_mm=100.0, min_area_mm2=0.1)
    result = run(ring_image, params)
    root = ET.fromstring(build_svg(result.paths, params, result.bounds))
    assert len(list(root.iter(f"{SVG_NS}circle"))) == 2


def test_fitted_arcs_become_arc_commands():
    image = np.full((300, 400, 3), 255, np.uint8)
    cv2.ellipse(image, (200, 150), (150, 80), 0, 0, 360, (0, 0, 0), -1)
    params = TraceParams(width_mm=100.0)
    result = run(image, params)

    text = build_svg(result.paths, params, result.bounds)
    assert result.arc_count > 0
    assert " A " in text


def test_tone_levels_become_groups(gradient_image):
    params = TraceParams(mode="posterize", levels=4, min_area_mm2=0.1)
    result = run(gradient_image, params)
    root = ET.fromstring(build_svg(result.paths, params, result.bounds))

    ids = {g.get("id") for g in root.iter(f"{SVG_NS}g")}
    assert ids == {"CUT_TONE_0", "CUT_TONE_1", "CUT_TONE_2"}


def test_tabs_become_open_subpaths(square_image):
    params = TraceParams(width_mm=200.0, simplify_mm=0.1, tab_count=4, tab_mm=1.0)
    result = run(square_image, params)
    root = ET.fromstring(build_svg(result.paths, params, result.bounds))

    paths = list(root.iter(f"{SVG_NS}path"))
    assert len(paths) == 4
    assert not any("Z" in element.get("d", "") for element in paths)


def test_closed_paths_are_closed(square_image):
    result = run(square_image, PARAMS)
    root = ET.fromstring(build_svg(result.paths, PARAMS, result.bounds))
    [element] = list(root.iter(f"{SVG_NS}path"))
    assert element.get("d", "").endswith("Z")


def test_empty_result_still_writes_valid_svg(tmp_path):
    blank = np.full((50, 50, 3), 255, np.uint8)
    result = run(blank, TraceParams())
    path = write_svg(result.paths, tmp_path / "empty.svg", TraceParams(), result.bounds)

    root = ET.parse(path).getroot()
    assert root.tag == f"{SVG_NS}svg"
    assert list(root.iter(f"{SVG_NS}path")) == []
