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
    worker = TraceWorker(root, lambda r, p: delivered.append(r), delivered.append)
    worker.request(square_image, TraceParams())

    # Pump the Tk event loop until the background trace lands.
    for _ in range(200):
        root.update()
        if delivered:
            break
        root.after(20, root.quit)
        root.mainloop()

    assert delivered and delivered[0].path_count == 1


def test_preview_renders_each_view(root, ring_image):
    from img2dxf.gui.preview import VIEWS, render
    from img2dxf.params import TraceParams
    from img2dxf.pipeline import run

    result = run(ring_image, TraceParams())
    for view in VIEWS:
        photo = render(view, ring_image, result, (320, 240))
        assert photo is not None and photo.width() > 0


def test_preview_without_an_image_is_none():
    from img2dxf.gui.preview import render

    assert render("Overlay", None, None, (100, 100)) is None
