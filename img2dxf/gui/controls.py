"""The parameter panel: Tk variables in, :class:`TraceParams` out."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from .. import settings as settings_io
from . import tooltips
from ..params import DEFAULT_PRESET, DXF_VERSIONS, PRESETS, TraceParams

MODES = ("otsu", "fixed", "adaptive", "posterize", "edges")

_MODE_HELP = {
    "otsu": "Automatic threshold. Best for logos, clipart and text.",
    "fixed": "Manual threshold. Use when Otsu picks the wrong level.",
    "adaptive": "Local threshold. For scans with uneven lighting.",
    "posterize": "Tone bands, one layer each. For photographs.",
    "edges": "Canny edge outlines. Detail without solid fills.",
}

#: Which controls matter for each mode, so the panel only ever offers sliders
#: that actually do something.
_MODE_FIELDS = {
    "otsu": (),
    "fixed": ("threshold",),
    "adaptive": ("adaptive_block", "adaptive_c"),
    "posterize": ("levels",),
    "edges": ("canny_low", "canny_high", "edge_dilate"),
}

_HINT_COLOR = "#555555"

#: Sections folded away unless Advanced is ticked. What stays visible is
#: what a job needs to be correct — what it is, how big, and where it goes.
#: The rest is tuning, and nine sections at once is too many to scan.
_ADVANCED_SECTIONS = ("Adjustments", "Cleanup", "Vectors", "Machine", "Layout")

#: Fields a preset must not touch: they describe the user's photo and their
#: machine, not the tracing style being chosen.
_NOT_FROM_PRESETS = frozenset(
    {
        "rotate_deg",
        "detail",
        "copies_x",
        "copies_y",
        "tile_gap_mm",
        "bed_width_mm",
        "bed_height_mm",
        "tab_count",
        "tab_mm",
        "kerf_mm",
        "kerf_side",
    }
)


class ControlPanel(ttk.Frame):
    """Left-hand column of parameter widgets."""

    def __init__(self, master, on_change: Callable[[], None]) -> None:
        super().__init__(master, padding=(10, 8))
        self._on_change = on_change
        self._suspend = False
        self._vars: dict[str, tk.Variable] = {}
        self._mode_rows: dict[str, list[tk.Widget]] = {}
        self._sections: dict[str, ttk.LabelFrame] = {}
        self._user_presets: dict[str, TraceParams] = {}
        # The crop box is set by dragging on the preview, not by a widget, so
        # it lives here rather than in a Tk variable.
        self._crop: tuple[float, float, float, float] | None = None

        self._build()
        self.apply_preset(DEFAULT_PRESET)
        self._apply_advanced()

    # -- construction ---------------------------------------------------

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)

        self.preset_var = tk.StringVar(value=DEFAULT_PRESET)
        preset_box = ttk.Frame(self)
        preset_box.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        preset_box.columnconfigure(1, weight=1)
        ttk.Label(preset_box, text="Preset").grid(row=0, column=0, padx=(0, 6))
        combo = ttk.Combobox(
            preset_box,
            textvariable=self.preset_var,
            values=sorted(PRESETS),
            state="readonly",
        )
        combo.grid(row=0, column=1, sticky="ew")
        combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self.apply_preset(self.preset_var.get()),
        )
        self._preset_combo = combo
        self.refresh_presets()
        tooltips.attach(combo, tooltips.TOOLBAR_HELP["preset"])

        self._advanced_var = tk.BooleanVar(value=False)
        advanced = ttk.Checkbutton(
            preset_box, text="Advanced", variable=self._advanced_var,
            command=self._apply_advanced,
        )
        advanced.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        tooltips.attach(advanced, tooltips.TOOLBAR_HELP["advanced"])

        self._image_section(1)
        self._adjust_section(2)
        self._trace_section(3)
        self._cleanup_section(4)
        self._vector_section(5)
        self._machine_section(6)
        self._layout_section(7)
        self._size_section(8)
        self._output_section(9)

    def _image_section(self, row: int) -> None:
        frame = self._section("Image", row)

        self._slider(frame, 0, "rotate_deg", "Rotate", -180, 180, decimals=1)
        self._detail_row(frame, 4)

        buttons = ttk.Frame(frame)
        buttons.grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 0))
        tooltips.attach(
            buttons, "Turn the image a quarter turn at a time, or back upright."
        )
        for label, delta in (("-90", -90), ("0", None), ("+90", 90)):
            ttk.Button(
                buttons, text=label, width=5,
                command=lambda d=delta: self._nudge_rotation(d),
            ).pack(side="left", padx=(0, 4))

        self._crop_label = ttk.Label(frame, text="", foreground=_HINT_COLOR)
        self._crop_label.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
        tooltips.attach_field(self._crop_label, "crop")
        ttk.Label(
            frame,
            text="Drag on the preview with Crop enabled to frame the artwork.",
            wraplength=240, foreground=_HINT_COLOR,
        ).grid(row=3, column=0, columnspan=3, sticky="w")

    def _detail_row(self, frame, row: int) -> None:
        """Supersampling. Auto is the default and suits almost everything."""
        self._vars["detail"] = tk.IntVar(value=0)
        ttk.Label(frame, text="Detail").grid(row=row, column=0, sticky="w")

        box = ttk.Frame(frame)
        box.grid(row=row, column=1, columnspan=2, sticky="w", pady=2)
        for label, value in (("Auto", 0), ("1x", 1), ("2x", 2), ("3x", 3), ("4x", 4)):
            ttk.Radiobutton(
                box, text=label, value=value,
                variable=self._vars["detail"], command=self._changed,
            ).pack(side="left")
        tooltips.attach_children(box, tooltips.HELP["detail"])

        ttk.Label(
            frame,
            text=(
                "Traces an upscaled copy. Thresholding is what limits edge "
                "quality, and this is the only control that lifts it."
            ),
            wraplength=240, foreground=_HINT_COLOR,
        ).grid(row=row + 1, column=0, columnspan=3, sticky="w")

    def _nudge_rotation(self, delta: float | None) -> None:
        """Step by 90 degrees, or reset to upright when ``delta`` is None."""
        var = self._vars["rotate_deg"]
        value = 0.0 if delta is None else _wrap_degrees(var.get() + delta)
        var.set(value)
        self._changed()

    def _adjust_section(self, row: int) -> None:
        frame = self._section("Adjustments", row)
        self._checkbox(frame, 0, "auto_levels", "Auto levels")
        self._slider(frame, 1, "brightness", "Brightness", -100, 100)
        self._slider(frame, 2, "contrast", "Contrast", 0.1, 3.0, decimals=2)
        self._slider(frame, 3, "gamma", "Gamma", 0.1, 3.0, decimals=2)
        self._slider(frame, 4, "sharpen", "Sharpen", 0.0, 3.0, decimals=1)
        ttk.Label(
            frame,
            text="Sharpen and Blur undo each other - use one or the other.",
            wraplength=240, foreground=_HINT_COLOR,
        ).grid(row=5, column=0, columnspan=3, sticky="w")

    def _layout_section(self, row: int) -> None:
        frame = self._section("Layout", row)

        self._slider(frame, 0, "copies_x", "Copies across", 1, 12)
        self._slider(frame, 1, "copies_y", "Copies down", 1, 12)
        self._slider(frame, 2, "tile_gap_mm", "Tile gap (mm)", 0.0, 20.0, decimals=1)

        bed = ttk.Frame(frame)
        bed.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(bed, text="Bed (mm)").pack(side="left", padx=(0, 6))
        self._vars["bed_width_mm"] = tk.StringVar(value="0")
        self._vars["bed_height_mm"] = tk.StringVar(value="0")
        for field in ("bed_width_mm", "bed_height_mm"):
            entry = ttk.Entry(bed, textvariable=self._vars[field], width=6)
            entry.pack(side="left", padx=(0, 4))
            entry.bind("<Return>", lambda _e: self._changed())
            entry.bind("<FocusOut>", lambda _e: self._changed())
            tooltips.attach_field(entry, "bed_width_mm")
        tooltips.attach(bed, tooltips.HELP["bed_width_mm"])

        ttk.Label(
            frame,
            text="Set your machine's bed to get a fit warning. 0 disables it.",
            wraplength=240, foreground=_HINT_COLOR,
        ).grid(row=4, column=0, columnspan=3, sticky="w")

    def _machine_section(self, row: int) -> None:
        frame = self._section("Machine", row)

        self._slider(frame, 0, "kerf_mm", "Kerf (mm)", 0.0, 1.0, decimals=2)

        self._vars["kerf_side"] = tk.StringVar(value="none")
        ttk.Label(frame, text="Cut side").grid(row=1, column=0, sticky="w")
        side = ttk.Combobox(
            frame, textvariable=self._vars["kerf_side"],
            values=["none", "outside", "inside"], state="readonly", width=10,
        )
        side.grid(row=1, column=1, sticky="w", pady=2)
        side.bind("<<ComboboxSelected>>", lambda _e: self._changed())
        tooltips.attach_field(side, "kerf_side")

        ttk.Label(
            frame,
            text=(
                "outside keeps the part's size, inside keeps the hole's. "
                "Set the beam width your machine actually cuts."
            ),
            wraplength=240, foreground=_HINT_COLOR,
        ).grid(row=2, column=0, columnspan=3, sticky="w")

        self._checkbox(
            frame, 3, "fit_arcs", "Fit arcs and circles", default=True
        )
        self._checkbox(
            frame, 8, "optimize_order", "Shorten head travel", default=True
        )

        self._slider(frame, 4, "tab_count", "Tabs per path", 0, 12)
        self._slider(frame, 5, "tab_mm", "Tab width (mm)", 0.1, 5.0, decimals=2)
        ttk.Label(
            frame,
            text=(
                "Tabs leave the part attached to the sheet so it cannot drop "
                "through. They flatten arcs on the paths they cut."
            ),
            wraplength=240, foreground=_HINT_COLOR,
        ).grid(row=6, column=0, columnspan=3, sticky="w")

    def _trace_section(self, row: int) -> None:
        frame = self._section("Tracing", row)

        self._vars["mode"] = tk.StringVar(value="otsu")
        ttk.Label(frame, text="Mode").grid(row=0, column=0, sticky="w")
        mode_combo = ttk.Combobox(
            frame,
            textvariable=self._vars["mode"],
            values=list(MODES),
            state="readonly",
        )
        mode_combo.grid(row=0, column=1, columnspan=2, sticky="ew", pady=2)
        mode_combo.bind("<<ComboboxSelected>>", lambda _e: self._mode_changed())
        tooltips.attach_field(mode_combo, "mode")

        self._mode_hint = ttk.Label(
            frame, text="", wraplength=230, foreground=_HINT_COLOR
        )
        self._mode_hint.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 4))

        mode_sliders = (
            (2, "threshold", "Threshold", 0, 255, 0, 1),
            (3, "adaptive_block", "Block size", 3, 101, 0, 2),
            (4, "adaptive_c", "Bias", -20, 20, 0, 1),
            (5, "levels", "Tone levels", 2, 8, 0, 1),
            (6, "canny_low", "Edge low", 0, 255, 0, 1),
            (7, "canny_high", "Edge high", 0, 255, 0, 1),
            (8, "edge_dilate", "Edge width", 0, 10, 0, 1),
        )
        for slider_row, field, label, low, high, decimals, step in mode_sliders:
            self._slider(
                frame, slider_row, field, label, low, high,
                decimals=decimals, step=step,
            )
            self._mode_rows[field] = list(frame.grid_slaves(row=slider_row))

        self._checkbox(frame, 9, "invert", "Trace light areas instead")

    def _cleanup_section(self, row: int) -> None:
        frame = self._section("Cleanup", row)
        self._slider(frame, 0, "denoise", "Denoise", 0, 15)
        self._slider(frame, 1, "blur", "Blur", 0, 25)
        self._slider(frame, 2, "close_px", "Bridge gaps", 0, 15)
        self._slider(frame, 3, "open_px", "Remove specks", 0, 15)

    def _vector_section(self, row: int) -> None:
        frame = self._section("Vectors", row)
        self._slider(frame, 0, "simplify_mm", "Tolerance (mm)", 0.0, 1.0, decimals=2)
        self._slider(frame, 1, "min_area_mm2", "Min area (mm2)", 0.0, 25.0, decimals=1)
        self._slider(frame, 2, "smooth", "Smoothing", 0, 3)
        self._slider(frame, 3, "corner_deg", "Corner angle", 0, 90, decimals=0)
        self._slider(
            frame, 4, "straighten_mm", "Straighten (mm)", 0.0, 1.0, decimals=2
        )
        self._slider(frame, 5, "min_run_mm", "Min run (mm)", 0.0, 20.0, decimals=1)
        self._checkbox(
            frame, 6, "keep_holes", "Keep holes (inner outlines)", default=True
        )
        ttk.Label(
            frame,
            text=(
                "Straighten flattens edges whose wobble is pixel noise, and "
                "leaves anything that curves. Turns sharper than the corner "
                "angle are never smoothed."
            ),
            wraplength=240, foreground=_HINT_COLOR,
        ).grid(row=7, column=0, columnspan=3, sticky="w")

    def _size_section(self, row: int) -> None:
        frame = self._section("Size", row)

        self._vars["size_mode"] = tk.StringVar(value="fit")
        for column, (label, value) in enumerate(
            (("Fit to width", "fit"), ("Use image DPI", "dpi"))
        ):
            button = ttk.Radiobutton(
                frame,
                text=label,
                value=value,
                variable=self._vars["size_mode"],
                command=self._changed,
            )
            button.grid(row=0, column=column, sticky="w", pady=2)
            tooltips.attach_field(button, "size_mode")

        self._entry(frame, 1, "width_mm", "Width (mm)", "100")
        self._entry(frame, 2, "dpi", "DPI", "96")

        self._vars["origin"] = tk.StringVar(value="bottom-left")
        centre = ttk.Checkbutton(
            frame,
            text="Centre output on 0,0",
            variable=self._vars["origin"],
            onvalue="center",
            offvalue="bottom-left",
            command=self._changed,
        )
        centre.grid(row=3, column=0, columnspan=3, sticky="w", pady=2)
        tooltips.attach_field(centre, "origin")

    def _output_section(self, row: int) -> None:
        frame = self._section("Output", row)

        self._vars["dxf_version"] = tk.StringVar(value="R2010")
        ttk.Label(frame, text="DXF version").grid(row=0, column=0, sticky="w")
        version = ttk.Combobox(
            frame,
            textvariable=self._vars["dxf_version"],
            values=list(DXF_VERSIONS),
            state="readonly",
            width=10,
        )
        version.grid(row=0, column=1, sticky="w", pady=2)
        version.bind("<<ComboboxSelected>>", lambda _e: self._changed())
        tooltips.attach_field(version, "dxf_version")

        self._entry(frame, 1, "layer_name", "Layer", "CUT")
        ttk.Label(
            frame,
            text="R12 for older RDWorks/LaserCAD; R2010 for LightBurn.",
            wraplength=230,
            foreground=_HINT_COLOR,
        ).grid(row=2, column=0, columnspan=3, sticky="w")

    # -- widget helpers -------------------------------------------------

    def _section(self, title: str, row: int) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(self, text=title, padding=(8, 4))
        frame.grid(row=row, column=0, sticky="ew", pady=4)
        frame.columnconfigure(1, weight=1)
        self._sections[title] = frame
        return frame

    def _apply_advanced(self) -> None:
        """Show or hide the tuning sections."""
        show = bool(self._advanced_var.get())
        for title in _ADVANCED_SECTIONS:
            frame = self._sections.get(title)
            if frame is None:
                continue
            if show:
                frame.grid()
            else:
                frame.grid_remove()

    def _slider(
        self, parent, row, field, label, low, high, *, decimals=0, step=1
    ) -> None:
        is_float = decimals > 0
        var: tk.Variable = tk.DoubleVar() if is_float else tk.IntVar()
        self._vars[field] = var
        readout = tk.StringVar()

        def on_move(_value=None) -> None:
            raw = var.get()
            if not is_float:
                snapped = int(round(raw / step) * step)
                if snapped != raw:
                    var.set(snapped)
                raw = snapped
            readout.set(f"{raw:.{decimals}f}")
            self._changed()

        name = ttk.Label(parent, text=label)
        name.grid(row=row, column=0, sticky="w")

        scale = ttk.Scale(
            parent,
            from_=low,
            to=high,
            variable=var,
            orient="horizontal",
            command=on_move,
        )
        scale.grid(row=row, column=1, sticky="ew", padx=4, pady=1)

        value = ttk.Label(parent, textvariable=readout, width=5, anchor="e")
        value.grid(row=row, column=2, sticky="e")

        # The label is the easiest thing to hover, so it gets help too.
        for widget in (name, scale, value):
            tooltips.attach_field(widget, field)

    def _checkbox(self, parent, row, field, label, *, default=False) -> None:
        var = tk.BooleanVar(value=default)
        self._vars[field] = var
        box = ttk.Checkbutton(
            parent, text=label, variable=var, command=self._changed
        )
        box.grid(row=row, column=0, columnspan=3, sticky="w", pady=2)
        tooltips.attach_field(box, field)

    def _entry(self, parent, row, field, label, default) -> None:
        var = tk.StringVar(value=default)
        self._vars[field] = var
        name = ttk.Label(parent, text=label)
        name.grid(row=row, column=0, sticky="w")
        entry = ttk.Entry(parent, textvariable=var, width=10)
        entry.grid(row=row, column=1, sticky="w", pady=2)
        for widget in (name, entry):
            tooltips.attach_field(widget, field)
        # Retrace on Enter or focus-out rather than per keystroke, so a
        # half-typed "1" in "100" never triggers a run at 1 mm.
        entry.bind("<Return>", lambda _e: self._changed())
        entry.bind("<FocusOut>", lambda _e: self._changed())

    # -- state ----------------------------------------------------------

    def _mode_changed(self) -> None:
        mode = self._vars["mode"].get()
        self._mode_hint.configure(text=_MODE_HELP.get(mode, ""))
        visible = _MODE_FIELDS.get(mode, ())
        for field, widgets in self._mode_rows.items():
            for widget in widgets:
                if field in visible:
                    widget.grid()
                else:
                    widget.grid_remove()
        self._changed()

    def _changed(self) -> None:
        if not self._suspend:
            self._on_change()

    def refresh_presets(self, select: str | None = None) -> None:
        """Reload the user's presets into the dropdown."""
        self._user_presets = settings_io.load_presets()
        names = sorted({**PRESETS, **self._user_presets})
        self._preset_combo.configure(values=names)
        if select is not None and select in names:
            self.preset_var.set(select)

    def presets(self) -> dict[str, TraceParams]:
        """Built-in presets plus the user's own, which win on a name clash."""
        return {**PRESETS, **self._user_presets}

    def apply_preset(self, name: str) -> None:
        """Load a preset into the widgets, re-tracing once at the end."""
        params = self.presets().get(name)
        if params is not None:
            self.set_params(params)

    def set_params(self, params: TraceParams, *, framing: bool = False) -> None:
        """Load a whole parameter set into the widgets.

        ``framing`` decides whether the fields in `_NOT_FROM_PRESETS` come
        along. A preset must leave them alone — rotation and crop describe the
        photo in front of the user, and kerf and bed describe their machine.
        Restoring a saved job is the opposite case: it is supposed to bring
        back everything, framing included.
        """
        self._suspend = True
        try:
            for field, var in self._vars.items():
                if not framing and field in _NOT_FROM_PRESETS:
                    continue
                value = getattr(params, field, None)
                if value is not None:
                    var.set(value)
            if framing:
                self._crop = params.crop
                self._crop_label.configure(text=_describe_crop(params.crop))
        finally:
            self._suspend = False
        self._mode_changed()

    def crop(self) -> tuple[float, float, float, float] | None:
        """The crop box currently applied, in fractions of the source image."""
        return self._crop

    def set_field(self, field: str, value) -> None:
        """Set one control without triggering a re-trace."""
        if field == "crop":
            self._crop = value
            self._crop_label.configure(text=_describe_crop(value))
            return

        var = self._vars.get(field)
        if var is None:
            return
        self._suspend = True
        try:
            var.set(value)
        finally:
            self._suspend = False

    def params(self) -> TraceParams:
        """Read the widgets back into a :class:`TraceParams`."""
        values = {field: var.get() for field, var in self._vars.items()}
        return TraceParams(
            optimize_order=bool(values["optimize_order"]),
            detail=int(values["detail"]),
            corner_deg=float(values["corner_deg"]),
            straighten_mm=float(values["straighten_mm"]),
            min_run_mm=float(values["min_run_mm"]),
            auto_levels=bool(values["auto_levels"]),
            brightness=int(values["brightness"]),
            contrast=float(values["contrast"]),
            gamma=float(values["gamma"]),
            sharpen=float(values["sharpen"]),
            tab_count=int(values["tab_count"]),
            tab_mm=float(values["tab_mm"]),
            copies_x=int(values["copies_x"]),
            copies_y=int(values["copies_y"]),
            tile_gap_mm=float(values["tile_gap_mm"]),
            bed_width_mm=_number(values["bed_width_mm"], 0.0, allow_zero=True),
            bed_height_mm=_number(values["bed_height_mm"], 0.0, allow_zero=True),
            rotate_deg=float(values["rotate_deg"]),
            crop=self._crop,
            kerf_mm=float(values["kerf_mm"]),
            kerf_side=values["kerf_side"],
            fit_arcs=bool(values["fit_arcs"]),
            invert=bool(values["invert"]),
            blur=int(values["blur"]),
            denoise=int(values["denoise"]),
            mode=values["mode"],
            threshold=int(values["threshold"]),
            adaptive_block=int(values["adaptive_block"]),
            adaptive_c=int(values["adaptive_c"]),
            levels=int(values["levels"]),
            canny_low=int(values["canny_low"]),
            canny_high=int(values["canny_high"]),
            edge_dilate=int(values["edge_dilate"]),
            close_px=int(values["close_px"]),
            open_px=int(values["open_px"]),
            simplify_mm=float(values["simplify_mm"]),
            smooth=int(values["smooth"]),
            min_area_mm2=float(values["min_area_mm2"]),
            keep_holes=bool(values["keep_holes"]),
            size_mode=values["size_mode"],
            width_mm=_number(values["width_mm"], 100.0),
            dpi=_number(values["dpi"], 96.0),
            origin=values["origin"],
            dxf_version=values["dxf_version"],
            layer_name=str(values["layer_name"]).strip() or "CUT",
        ).normalized()


def _wrap_degrees(value: float) -> float:
    """Keep rotation in -180..180 so the slider handle stays where expected."""
    wrapped = (float(value) + 180.0) % 360.0 - 180.0
    return round(wrapped, 1)


def _describe_crop(box) -> str:
    if box is None:
        return "Crop: whole image"
    left, top, right, bottom = box
    return f"Crop: {(right - left) * 100:.0f}% x {(bottom - top) * 100:.0f}%"


def _number(raw, fallback: float, *, allow_zero: bool = False) -> float:
    """Parse a text entry, falling back rather than throwing mid-edit.

    ``allow_zero`` is for fields where zero means "off" rather than "invalid",
    such as the bed size.
    """
    try:
        value = float(str(raw).replace(",", "."))
    except (TypeError, ValueError):
        return fallback
    if value > 0 or (allow_zero and value == 0):
        return value
    return fallback
