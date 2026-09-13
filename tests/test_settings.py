"""Saving a job's settings, reloading them, and named presets."""

from __future__ import annotations

import json
from dataclasses import fields

import pytest

from img2dxf import settings as settings_io
from img2dxf.order import order_paths, travel_length
from img2dxf.params import TraceParams
from img2dxf.pipeline import run

TUNED = TraceParams(
    width_mm=87.5,
    mode="adaptive",
    crop=(0.1, 0.2, 0.8, 0.9),
    rotate_deg=12.5,
    kerf_mm=0.15,
    kerf_side="outside",
    tab_count=4,
    detail=3,
    bed_width_mm=400.0,
    bed_height_mm=300.0,
    copies_x=2,
).normalized()


@pytest.fixture(autouse=True)
def isolated_presets(tmp_path, monkeypatch):
    """Never touch the real ~/.img2dxf while testing."""
    monkeypatch.setattr(settings_io, "PRESETS_PATH", tmp_path / "presets.json")


# --- round trip ------------------------------------------------------------


def test_every_field_is_persisted():
    """A new parameter must be saved without anyone remembering to add it."""
    saved = settings_io.to_dict(TUNED)
    names = {field.name for field in fields(TraceParams)}
    assert names <= set(saved)


def test_settings_round_trip_exactly(tmp_path):
    path = settings_io.save(TUNED, tmp_path / "job.json")
    assert settings_io.load(path) == TUNED


def test_crop_survives_as_a_tuple(tmp_path):
    """JSON has no tuples, and TraceParams expects one."""
    loaded = settings_io.load(settings_io.save(TUNED, tmp_path / "j.json"))
    assert isinstance(loaded.crop, tuple)
    assert loaded.crop == pytest.approx(TUNED.crop)


def test_a_file_from_a_newer_version_still_loads():
    """Unknown keys are ignored rather than refusing the whole file."""
    data = settings_io.to_dict(TUNED)
    data["some_future_knob"] = 42
    assert settings_io.from_dict(data).width_mm == pytest.approx(87.5)


def test_missing_keys_fall_back_to_defaults():
    assert settings_io.from_dict({"width_mm": 50.0}).mode == TraceParams().mode


def test_loaded_settings_are_normalized():
    """A hand-edited file must not be able to inject a nonsense value."""
    data = settings_io.to_dict(TUNED)
    data["detail"] = 99
    data["gamma"] = -5
    loaded = settings_io.from_dict(data)
    assert loaded.detail == 4
    assert loaded.gamma > 0


def test_a_file_that_is_not_settings_is_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError):
        settings_io.load(path)


def test_companion_path_sits_beside_the_image(tmp_path):
    companion = settings_io.companion_path(tmp_path / "logo.png")
    assert companion.parent == tmp_path
    assert companion.name.startswith("logo.png")
    assert companion.suffix == ".json"


def test_saved_settings_reproduce_the_trace(square_image, tmp_path):
    """The point of the feature: the same file comes back out."""
    first = run(square_image, TUNED)
    reloaded = settings_io.load(settings_io.save(TUNED, tmp_path / "j.json"))
    second = run(square_image, reloaded)

    assert second.path_count == first.path_count
    assert second.vertex_count == first.vertex_count
    assert second.bounds.width == pytest.approx(first.bounds.width)


# --- named presets ---------------------------------------------------------


def test_a_preset_can_be_saved_and_read_back():
    settings_io.save_preset("My logo job", TUNED)
    assert settings_io.load_presets()["My logo job"] == TUNED


def test_presets_can_be_deleted():
    settings_io.save_preset("Temporary", TUNED)
    settings_io.delete_preset("Temporary")
    assert "Temporary" not in settings_io.load_presets()


def test_an_unnamed_preset_is_refused():
    with pytest.raises(ValueError):
        settings_io.save_preset("   ", TUNED)


def test_no_presets_file_is_not_an_error():
    assert settings_io.load_presets() == {}


def test_one_corrupt_preset_does_not_lose_the_others():
    settings_io.save_preset("Good", TUNED)
    raw = json.loads(settings_io.PRESETS_PATH.read_text(encoding="utf-8"))
    raw["Broken"] = "not a settings object"
    settings_io.PRESETS_PATH.write_text(json.dumps(raw), encoding="utf-8")

    presets = settings_io.load_presets()
    assert "Good" in presets
    assert "Broken" not in presets


def test_a_corrupt_presets_file_reads_as_empty():
    settings_io.PRESETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    settings_io.PRESETS_PATH.write_text("{ not json", encoding="utf-8")
    assert settings_io.load_presets() == {}


# --- travel ordering -------------------------------------------------------


def scattered_image(count=20, seed=7):
    import cv2
    import numpy as np

    image = np.full((300, 600, 3), 255, np.uint8)
    rng = np.random.default_rng(seed)
    for _ in range(count):
        x = int(rng.integers(20, 580))
        y = int(rng.integers(20, 280))
        cv2.circle(image, (x, y), 9, (0, 0, 0), -1)
    return image


def test_ordering_shortens_the_travel():
    image = scattered_image()
    plain = run(image, TraceParams(width_mm=200.0, min_area_mm2=0.1,
                                   optimize_order=False))
    ordered = run(image, TraceParams(width_mm=200.0, min_area_mm2=0.1))

    assert ordered.travel_mm < plain.travel_mm / 2
    assert ordered.path_count == plain.path_count


def test_ordering_changes_nothing_but_the_order():
    image = scattered_image()
    plain = run(image, TraceParams(width_mm=200.0, min_area_mm2=0.1,
                                   optimize_order=False))
    ordered = run(image, TraceParams(width_mm=200.0, min_area_mm2=0.1))

    assert ordered.vertex_count == plain.vertex_count
    assert ordered.bounds.width == pytest.approx(plain.bounds.width)
    assert ordered.bounds.height == pytest.approx(plain.bounds.height)


def test_tone_levels_are_not_interleaved(gradient_image):
    """Layers are how power and speed get assigned; shuffling them is worse
    than a longer path."""
    result = run(
        gradient_image,
        TraceParams(mode="posterize", levels=4, min_area_mm2=0.1, width_mm=100.0),
    )
    levels = [path.level for path in result.paths]
    assert levels == sorted(levels)


def test_holes_are_cut_before_their_outline(ring_image):
    """A freed part can shift, so its holes must already be cut."""
    import numpy as np

    from img2dxf.order import _entry_point

    result = run(ring_image, TraceParams(width_mm=100.0, min_area_mm2=0.1))
    path = result.paths[0]
    assert path.holes, "the fixture should produce a ring with a hole"
    assert np.array_equal(_entry_point(path), path.holes[0][0])


def test_travel_of_nothing_is_zero():
    assert travel_length([]) == 0.0


def test_too_few_paths_are_left_alone(square_image):
    """One path cannot be reordered, so it is returned untouched."""
    paths = run(square_image, TraceParams()).paths
    assert len(paths) < 3
    assert order_paths(paths) is paths
