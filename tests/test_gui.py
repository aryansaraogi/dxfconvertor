"""Headless GUI checks: build the widgets, drive one trace, never mainloop."""

from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")


@pytest.fixture
def root():
    try:
        window = tk.Tk()
    except tk.TclError as exc:  # no display available
        pytest.skip(f"Tk unavailable: {exc}")
    window.withdraw()
    yield window
    window.destroy()


def test_controls_round_trip_every_preset(root):
    from img2dxf.gui.controls import ControlPanel
    from img2dxf.params import PRESETS

    panel = ControlPanel(root, lambda: None)
    for name, preset in PRESETS.items():
        panel.apply_preset(name)
        read_back = panel.params()
        assert read_back.mode == preset.mode, name
        assert read_back.levels == preset.levels, name
        assert read_back.simplify_mm == pytest.approx(preset.simplify_mm), name
        assert read_back.keep_holes == preset.keep_holes, name


def test_bad_entry_text_falls_back_instead_of_raising(root):
    from img2dxf.gui.controls import ControlPanel

    panel = ControlPanel(root, lambda: None)
    panel.set_field("width_mm", "not a number")
    panel.set_field("layer_name", "   ")
    params = panel.params()
    assert params.width_mm == 100.0
    assert params.layer_name == "CUT"


def test_mode_change_hides_irrelevant_sliders(root):
    from img2dxf.gui.controls import ControlPanel

    panel = ControlPanel(root, lambda: None)
    panel.set_field("mode", "fixed")
    panel._mode_changed()
    visible = {
        field
        for field, widgets in panel._mode_rows.items()
        if any(w.winfo_manager() for w in widgets)
    }
    assert visible == {"threshold"}


def test_worker_delivers_a_result(root, square_image):
    from img2dxf.gui.worker import TraceWorker
    from img2dxf.params import TraceParams

    delivered = []
    busy = []
    worker = TraceWorker(
        root, lambda r, p: delivered.append(r), delivered.append, busy.append
    )
    worker.request(square_image, TraceParams())

    # Pump the Tk event loop until the background trace lands.
    for _ in range(200):
        root.update()
        if delivered:
            break
        root.after(20, root.quit)
        root.mainloop()

    assert delivered and delivered[0].path_count == 1
    # The progress indicator must be switched on and then off again.
    assert busy == [True, False]


def test_preview_renders_each_view(root, ring_image):
    from img2dxf.gui.preview import VIEWS, ViewState, render
    from img2dxf.params import TraceParams
    from img2dxf.pipeline import run

    result = run(ring_image, TraceParams())
    state = ViewState()
    state.fit(result.image_size_px, (320, 240))
    for view in VIEWS:
        photo = render(view, ring_image, result, state, (320, 240))
        assert photo is not None and photo.width() > 0


def test_preview_draws_discarded_contours(root, square_image):
    from img2dxf.gui.preview import ViewState, render
    from img2dxf.params import TraceParams
    from img2dxf.pipeline import run

    speckled = square_image.copy()
    speckled[5:8, 5:8] = 0
    result = run(speckled, TraceParams(min_area_mm2=5.0))
    assert result.discarded

    state = ViewState()
    state.fit(result.image_size_px, (200, 200))
    assert render(
        "Vectors", speckled, result, state, (200, 200), show_discarded=True
    ) is not None


def test_preview_without_an_image_is_none():
    from img2dxf.gui.preview import ViewState, render

    assert render("Overlay", None, None, ViewState(), (100, 100)) is None


# --- view state ------------------------------------------------------------


def test_canvas_and_image_coordinates_round_trip():
    from img2dxf.gui.preview import ViewState

    state = ViewState()
    state.fit((400, 300), (800, 600))
    state.zoom_at(120.0, 90.0, 2.5)
    state.pan(-33.0, 17.0)

    for point in ((0.0, 0.0), (123.5, 47.25), (399.0, 299.0)):
        back = state.canvas_to_image(*state.image_to_canvas(*point))
        assert back == pytest.approx(point)


def test_fit_centres_the_image():
    from img2dxf.gui.preview import ViewState

    state = ViewState()
    state.fit((100, 100), (400, 200))
    assert state.scale == pytest.approx(2.0)
    # 100 px at 2x is 200 wide in a 400 wide canvas, so 100 px of margin.
    assert state.offset_x == pytest.approx(100.0)
    assert state.offset_y == pytest.approx(0.0)


def test_zoom_keeps_the_point_under_the_cursor_still():
    from img2dxf.gui.preview import ViewState

    state = ViewState()
    state.fit((200, 200), (400, 400))
    before = state.canvas_to_image(250.0, 150.0)
    state.zoom_at(250.0, 150.0, 3.0)
    assert state.canvas_to_image(250.0, 150.0) == pytest.approx(before)


def test_zoom_is_clamped():
    from img2dxf.gui.preview import MAX_ZOOM, MIN_ZOOM, ViewState

    state = ViewState()
    for _ in range(80):
        state.zoom_at(0.0, 0.0, 2.0)
    assert state.scale == pytest.approx(MAX_ZOOM)
    for _ in range(80):
        state.zoom_at(0.0, 0.0, 0.5)
    assert state.scale == pytest.approx(MIN_ZOOM)


# --- crop composition ------------------------------------------------------


def test_successive_crops_compose_rather_than_reset():
    """A second crop is drawn on the already-cropped image, not the original."""
    from img2dxf.gui.app import _compose_crop

    first = (0.0, 0.0, 0.5, 1.0)
    # The right half of what is now shown is the original 0.25..0.5 band.
    assert _compose_crop(first, (0.5, 0.0, 1.0, 1.0)) == pytest.approx(
        (0.25, 0.0, 0.5, 1.0)
    )


def test_first_crop_passes_through():
    from img2dxf.gui.app import _compose_crop

    box = (0.1, 0.2, 0.8, 0.9)
    assert _compose_crop(None, box) == box


def test_control_panel_reports_and_clears_the_crop(root):
    from img2dxf.gui.controls import ControlPanel

    panel = ControlPanel(root, lambda: None)
    assert panel.crop() is None

    panel.set_field("crop", (0.1, 0.1, 0.6, 0.7))
    assert panel.params().crop == pytest.approx((0.1, 0.1, 0.6, 0.7))

    panel.set_field("crop", None)
    assert panel.params().crop is None


def test_preset_change_keeps_the_user_framing(root):
    """Presets describe tracing, not which part of the photo is wanted."""
    from img2dxf.gui.controls import ControlPanel

    panel = ControlPanel(root, lambda: None)
    panel.set_field("crop", (0.2, 0.2, 0.8, 0.8))
    panel.set_field("rotate_deg", 12.5)

    panel.apply_preset("Photo")

    assert panel.params().crop == pytest.approx((0.2, 0.2, 0.8, 0.8))
    assert panel.params().rotate_deg == pytest.approx(12.5)


def test_ninety_degree_buttons_wrap(root):
    from img2dxf.gui.controls import ControlPanel

    panel = ControlPanel(root, lambda: None)
    for _ in range(3):
        panel._nudge_rotation(90)
    assert panel.params().rotate_deg == pytest.approx(270.0)  # -90 wrapped

    panel._nudge_rotation(None)
    assert panel.params().rotate_deg == pytest.approx(0.0)


def test_recent_files_skip_entries_that_moved(tmp_path, monkeypatch):
    from img2dxf.gui import recent

    store = tmp_path / "recent.json"
    monkeypatch.setattr(recent, "_STORE", store)

    existing = tmp_path / "logo.png"
    existing.write_bytes(b"x")
    recent.remember(existing)
    recent.remember(tmp_path / "gone.png")

    assert recent.load() == [existing]


def test_recent_files_are_newest_first_and_deduplicated(tmp_path, monkeypatch):
    from img2dxf.gui import recent

    monkeypatch.setattr(recent, "_STORE", tmp_path / "recent.json")
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    for item in (first, second):
        item.write_bytes(b"x")

    recent.remember(first)
    recent.remember(second)
    recent.remember(first)

    assert recent.load() == [first, second]
