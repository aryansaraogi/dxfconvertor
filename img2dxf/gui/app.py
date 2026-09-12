"""Main window: file handling, preview interaction, and export."""

from __future__ import annotations

import math
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import numpy as np

from ..dxfwrite import units_are_declared, write_dxf
from ..geometry import width_for_reference
from ..params import TraceParams
from ..pipeline import TraceResult
from ..preprocess import load_image
from ..svgwrite import write_svg
from ..transform import normalize_box
from . import recent
from .controls import ControlPanel
from .preview import (
    BED_OK_COLOR,
    BED_OVER_COLOR,
    VIEWS,
    ViewState,
    mm_to_image_px,
    render,
)
from .worker import TraceWorker

try:  # optional: drag-and-drop needs a Tk extension that may not be installed
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:  # pragma: no cover - exercised only on installs without it
    TkinterDnD = None
    DND_FILES = None

IMAGE_TYPES = [
    ("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp"),
    ("All files", "*.*"),
]

EXPORT_TYPES = [("DXF", "*.dxf"), ("SVG", "*.svg")]

#: Redrawing on every pixel of a window resize is wasteful; wait for a pause.
_RESIZE_DEBOUNCE_MS = 120

_ZOOM_STEP = 1.15
_CROP_HANDLE = (60, 140, 255)
_MEASURE_COLOR = "#d03020"


class App(ttk.Frame):
    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master)
        self.master.title("img2dxf - image to laser DXF")
        self.master.minsize(940, 600)
        _size_to_screen(self.master)

        self._image: np.ndarray | None = None
        self._image_path: Path | None = None
        self._result: TraceResult | None = None
        self._result_params: TraceParams | None = None
        self._photo = None  # kept alive; Tk does not own PhotoImage references
        self._resize_id: str | None = None

        self._view = ViewState()
        self._mode: str | None = None  # None, "crop" or "measure"
        self._drag_start: tuple[float, float] | None = None
        self._drag_now: tuple[float, float] | None = None
        self._pan_from: tuple[float, float] | None = None
        self._measure: tuple[tuple[float, float], tuple[float, float]] | None = None

        self._build()
        self._worker = TraceWorker(self, self._on_result, self._on_error, self._on_busy)
        self._enable_drop()
        self.master.protocol("WM_DELETE_WINDOW", self.close)
        self.pack(fill="both", expand=True)

    def close(self) -> None:
        """Shut down cleanly, so no timer fires against a destroyed widget."""
        self._worker.stop()
        self._progress.stop()
        self.master.destroy()

    # -- layout ---------------------------------------------------------

    def _build(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="ns")
        left.rowconfigure(0, weight=1)

        scroller = _ScrollableColumn(left, width=300)
        scroller.grid(row=0, column=0, sticky="ns")
        self.controls = ControlPanel(scroller.interior, self._retrace)
        self.controls.pack(fill="both", expand=True)

        right = ttk.Frame(self, padding=(8, 8))
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        self._build_toolbar(right)

        self._canvas = tk.Canvas(right, background="#f2f2f2", highlightthickness=0)
        self._canvas.grid(row=1, column=0, sticky="nsew")
        self._bind_canvas()

        self._build_statusbar(right)

        self.master.bind("<Control-o>", lambda _e: self.open_image())
        self.master.bind("<Control-s>", lambda _e: self.export_dxf())
        self.master.bind("<Key-f>", lambda _e: self.fit_view())
        self.master.bind("<Escape>", lambda _e: self._set_mode(None))

    def _build_toolbar(self, parent) -> None:
        bar = ttk.Frame(parent)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        ttk.Button(bar, text="Open...", command=self.open_image).pack(side="left")
        self._recent_button = ttk.Menubutton(bar, text="Recent")
        self._recent_menu = tk.Menu(self._recent_button, tearoff=False)
        self._recent_button.configure(menu=self._recent_menu)
        self._recent_button.pack(side="left", padx=(4, 0))
        self._refresh_recent()

        self._export_button = ttk.Button(
            bar, text="Export DXF...", command=self.export_dxf, state="disabled"
        )
        self._export_button.pack(side="left", padx=6)

        self._view_var = tk.StringVar(value="Overlay")
        ttk.Label(bar, text="View").pack(side="left", padx=(16, 4))
        view = ttk.Combobox(
            bar, textvariable=self._view_var, values=list(VIEWS),
            state="readonly", width=10,
        )
        view.pack(side="left")
        view.bind("<<ComboboxSelected>>", lambda _e: self._redraw())

        self._discard_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            bar, text="Show dropped", variable=self._discard_var,
            command=self._redraw,
        ).pack(side="left", padx=(12, 0))

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)

        self._crop_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            bar, text="Crop", variable=self._crop_var,
            command=lambda: self._set_mode("crop" if self._crop_var.get() else None),
        ).pack(side="left")
        ttk.Button(bar, text="Clear crop", command=self.clear_crop).pack(
            side="left", padx=4
        )

        self._measure_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            bar, text="Measure", variable=self._measure_var,
            command=lambda: self._set_mode(
                "measure" if self._measure_var.get() else None
            ),
        ).pack(side="left", padx=(8, 0))

        self._set_size_button = ttk.Button(
            bar, text="Set size...", command=self.set_size_from_measure,
            state="disabled",
        )
        self._set_size_button.pack(side="left", padx=(4, 0))

        ttk.Button(bar, text="Fit", command=self.fit_view).pack(side="left", padx=(8, 0))

    def _build_statusbar(self, parent) -> None:
        bar = ttk.Frame(parent)
        bar.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        bar.columnconfigure(0, weight=1)

        self._status = tk.StringVar(value="Open a PNG or JPEG to begin.")
        self._status_label = ttk.Label(bar, textvariable=self._status, anchor="w")
        self._status_label.grid(row=0, column=0, sticky="ew")
        self._progress = ttk.Progressbar(bar, mode="indeterminate", length=110)
        # Gridded only while busy, so it does not sit there as dead furniture.

    def _bind_canvas(self) -> None:
        self._canvas.bind("<Configure>", self._on_canvas_resize)
        self._canvas.bind("<MouseWheel>", self._on_wheel)
        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        # Middle-drag pans in every mode, so panning never fights the tools.
        self._canvas.bind("<ButtonPress-2>", self._on_pan_start)
        self._canvas.bind("<B2-Motion>", self._on_pan_move)

    def _enable_drop(self) -> None:
        if TkinterDnD is None or not hasattr(self.master, "drop_target_register"):
            return
        self.master.drop_target_register(DND_FILES)
        self.master.dnd_bind("<<Drop>>", self._on_drop)

    # -- files ----------------------------------------------------------

    def open_image(self, path: str | Path | None = None) -> None:
        if path is None:
            path = filedialog.askopenfilename(title="Open image", filetypes=IMAGE_TYPES)
            if not path:
                return
        try:
            rgb, dpi = load_image(path)
        except Exception as exc:
            messagebox.showerror("Could not open image", str(exc))
            return

        self._image = rgb
        self._image_path = Path(path)
        self._measure = None
        self._set_size_button.configure(state="disabled")
        self.clear_crop(retrace=False)
        self._view.fitted = True

        if dpi:
            # The file knows its own resolution, so offer it rather than 96.
            self.controls.set_field("dpi", f"{dpi:g}")

        self._refresh_recent(recent.remember(self._image_path))
        height, width = rgb.shape[:2]
        self._status.set(
            f"{self._image_path.name} - {width} x {height} px - tracing..."
        )
        self._retrace()

    def _on_drop(self, event) -> None:
        # Tk hands back a brace-quoted list when paths contain spaces.
        paths = self.master.tk.splitlist(event.data)
        if paths:
            self.open_image(paths[0])

    def _refresh_recent(self, entries: list[Path] | None = None) -> None:
        entries = recent.load() if entries is None else entries
        self._recent_menu.delete(0, "end")
        for item in entries:
            self._recent_menu.add_command(
                label=item.name,
                command=lambda p=item: self.open_image(p),
            )
        self._recent_button.configure(state="normal" if entries else "disabled")

    def export_dxf(self) -> None:
        if self._result is None or self._result_params is None:
            return
        if self._result.path_count == 0:
            messagebox.showwarning(
                "Nothing to export",
                "No outlines were found. Try a different mode or threshold.",
            )
            return

        default = (self._image_path or Path("untitled")).with_suffix(".dxf").name
        chosen = filedialog.asksaveasfilename(
            title="Export", defaultextension=".dxf",
            initialfile=default, filetypes=EXPORT_TYPES,
        )
        if not chosen:
            return

        path = Path(chosen)
        is_svg = path.suffix.lower() == ".svg"
        try:
            if is_svg:
                write_svg(
                    self._result.paths, path, self._result_params, self._result.bounds
                )
            else:
                write_dxf(self._result.paths, path, self._result_params)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))
            return

        message = f"Wrote {path.name} - {self._result.summary()}"
        if not is_svg and not units_are_declared(self._result_params.dxf_version):
            # R12 carries no unit, so the operator has to say "mm" on import.
            message += " - R12 stores no units; set mm when importing."
        self._set_status(message, warn=not self._result.fits_bed)

    # -- tracing --------------------------------------------------------

    def _retrace(self) -> None:
        if self._image is None:
            return
        self._worker.request(self._image, self.controls.params())

    def _on_result(self, result: TraceResult, params: TraceParams) -> None:
        self._result = result
        self._result_params = params
        self._export_button.configure(
            state="normal" if result.path_count else "disabled"
        )
        name = self._image_path.name if self._image_path else "image"
        self._set_status(f"{name} - {result.summary()}", warn=not result.fits_bed)
        self._redraw()

    def _on_error(self, error: Exception) -> None:
        self._set_status(f"Trace failed: {error}", warn=True)

    def _set_status(self, text: str, *, warn: bool = False) -> None:
        """Status text, in red when it is a warning the operator must see."""
        self._status.set(text)
        self._status_label.configure(foreground="#c02020" if warn else "")

    def _on_busy(self, busy: bool) -> None:
        if busy:
            self._progress.grid(row=0, column=1, padx=(8, 0))
            self._progress.start(12)
        else:
            self._progress.stop()
            self._progress.grid_remove()

    # -- view interaction -----------------------------------------------

    def _set_mode(self, mode: str | None) -> None:
        self._mode = mode
        self._crop_var.set(mode == "crop")
        self._measure_var.set(mode == "measure")
        self._drag_start = self._drag_now = None
        cursor = {"crop": "crosshair", "measure": "tcross"}.get(mode or "", "")
        self._canvas.configure(cursor=cursor)
        self._redraw()

    def set_size_from_measure(self) -> None:
        """Rescale the job so the measured feature comes out its true size."""
        if self._measure is None or self._result is None:
            return

        (x0, y0), (x1, y1) = self._measure
        measured_px = math.hypot(x1 - x0, y1 - y0)
        if measured_px <= 0:
            return

        current_mm = measured_px / self._result.px_per_mm
        target = simpledialog.askfloat(
            "Set size",
            f"That measures {current_mm:.2f} mm.\nWhat is its real size in mm?",
            parent=self.master,
            initialvalue=round(current_mm, 2),
            minvalue=0.001,
        )
        if not target:
            return

        width_px = self._result.image_size_px[0]
        try:
            width_mm = width_for_reference(width_px, measured_px, target)
        except ValueError as exc:
            messagebox.showerror("Could not set size", str(exc))
            return

        # This is a statement about physical size, so it has to override DPI
        # mode rather than be silently ignored by it.
        self.controls.set_field("size_mode", "fit")
        self.controls.set_field("width_mm", f"{width_mm:.6g}")
        self._set_mode(None)
        self._retrace()

    def fit_view(self) -> None:
        self._view.fit(self._displayed_size(), self._canvas_size())
        self._redraw()

    def clear_crop(self, retrace: bool = True) -> None:
        self.controls.set_field("crop", None)
        self._crop_var.set(False)
        if self._mode == "crop":
            self._set_mode(None)
        if retrace:
            self._retrace()

    def _displayed_size(self) -> tuple[int, int]:
        """Size of the image the canvas shows: rotated and cropped."""
        if self._result is not None:
            return self._result.image_size_px
        if self._image is None:
            return (0, 0)
        height, width = self._image.shape[:2]
        return (width, height)

    def _canvas_size(self) -> tuple[int, int]:
        return (self._canvas.winfo_width(), self._canvas.winfo_height())

    def _on_wheel(self, event) -> None:
        if self._image is None:
            return
        factor = _ZOOM_STEP if event.delta > 0 else 1 / _ZOOM_STEP
        self._view.zoom_at(event.x, event.y, factor)
        self._redraw()

    def _on_press(self, event) -> None:
        if self._mode in ("crop", "measure"):
            self._drag_start = (event.x, event.y)
            self._drag_now = (event.x, event.y)
        else:
            self._pan_from = (event.x, event.y)

    def _on_drag(self, event) -> None:
        if self._mode in ("crop", "measure") and self._drag_start is not None:
            self._drag_now = (event.x, event.y)
            self._redraw()
        elif self._pan_from is not None:
            dx = event.x - self._pan_from[0]
            dy = event.y - self._pan_from[1]
            self._pan_from = (event.x, event.y)
            self._view.pan(dx, dy)
            self._redraw()

    def _on_release(self, event) -> None:
        self._pan_from = None
        if self._drag_start is None:
            return
        start, end = self._drag_start, (event.x, event.y)
        self._drag_start = self._drag_now = None

        if self._mode == "crop":
            self._apply_crop(start, end)
        elif self._mode == "measure":
            self._measure = (
                self._view.canvas_to_image(*start),
                self._view.canvas_to_image(*end),
            )
            self._set_size_button.configure(state="normal")
            self._redraw()

    def _on_pan_start(self, event) -> None:
        self._pan_from = (event.x, event.y)

    def _on_pan_move(self, event) -> None:
        if self._pan_from is None:
            return
        dx = event.x - self._pan_from[0]
        dy = event.y - self._pan_from[1]
        self._pan_from = (event.x, event.y)
        self._view.pan(dx, dy)
        self._redraw()

    def _apply_crop(self, start, end) -> None:
        """Turn a canvas drag into a crop box, in fractions of the image.

        The drag is against the *displayed* image, which is already cropped, so
        a new box is composed onto the existing one — otherwise cropping twice
        would jump back to the full frame.
        """
        width, height = self._displayed_size()
        if width < 1 or height < 1:
            return

        x0, y0 = self._view.canvas_to_image(*start)
        x1, y1 = self._view.canvas_to_image(*end)
        if abs(x1 - x0) < 3 or abs(y1 - y0) < 3:
            return  # a click, not a drag

        box = normalize_box((x0 / width, y0 / height, x1 / width, y1 / height))
        self.controls.set_field("crop", _compose_crop(self.controls.crop(), box))
        self._view.fitted = True
        self._set_mode(None)
        self._retrace()

    # -- drawing --------------------------------------------------------

    def _on_canvas_resize(self, _event=None) -> None:
        if self._resize_id is not None:
            self.after_cancel(self._resize_id)
        self._resize_id = self.after(_RESIZE_DEBOUNCE_MS, self._redraw)

    def _redraw(self) -> None:
        self._resize_id = None
        self._canvas.delete("all")
        if self._image is None:
            return

        canvas_size = self._canvas_size()
        displayed = self._result.image_rgb if self._result is not None else self._image

        if self._view.fitted:
            self._view.fit(self._displayed_size(), canvas_size)

        self._photo = render(
            self._view_var.get(), displayed, self._result, self._view, canvas_size,
            show_discarded=self._discard_var.get(),
            params=self._result_params,
        )
        if self._photo is not None:
            self._canvas.create_image(0, 0, image=self._photo, anchor="nw")

        self._draw_bed()
        self._draw_drag_box()
        self._draw_measure()

    def _draw_bed(self) -> None:
        """Outline the machine bed, in red when the job will not fit.

        Drawn on the canvas rather than into the preview image: the bed is
        normally bigger than the artwork, and the image frame would clip it
        down to a sliver at the edge.
        """
        result = self._result
        if result is None or result.bed_size_mm is None:
            return
        if self._view_var.get() not in ("Vectors", "Overlay"):
            return

        bed_w, bed_h = result.bed_size_mm
        corners = np.array(
            [[0.0, 0.0], [bed_w, 0.0], [bed_w, bed_h], [0.0, bed_h]]
        )
        _, image_height = result.image_size_px
        points = [
            self._view.image_to_canvas(x, y)
            for x, y in mm_to_image_px(corners, result, image_height)
        ]
        flat = [value for point in points for value in point]
        self._canvas.create_polygon(
            flat,
            outline=BED_OK_COLOR if result.fits_bed else BED_OVER_COLOR,
            fill="",
            width=2,
            dash=(6, 4),
        )

    def _draw_drag_box(self) -> None:
        if self._mode != "crop" or self._drag_start is None or self._drag_now is None:
            return
        x0, y0 = self._drag_start
        x1, y1 = self._drag_now
        self._canvas.create_rectangle(
            x0, y0, x1, y1, outline=_CROP_HANDLE, width=2, dash=(4, 3)
        )

    def _draw_measure(self) -> None:
        """Draw the measuring line and label it in millimetres."""
        points = self._measure
        if self._mode == "measure" and self._drag_start and self._drag_now:
            points = (
                self._view.canvas_to_image(*self._drag_start),
                self._view.canvas_to_image(*self._drag_now),
            )
        if points is None or self._result is None:
            return

        (ix0, iy0), (ix1, iy1) = points
        x0, y0 = self._view.image_to_canvas(ix0, iy0)
        x1, y1 = self._view.image_to_canvas(ix1, iy1)
        self._canvas.create_line(x0, y0, x1, y1, fill=_MEASURE_COLOR, width=2)

        distance_mm = math.hypot(ix1 - ix0, iy1 - iy0) / self._result.px_per_mm
        self._canvas.create_text(
            (x0 + x1) / 2,
            (y0 + y1) / 2 - 12,
            text=f"{distance_mm:.2f} mm",
            fill=_MEASURE_COLOR,
            font=("TkDefaultFont", 10, "bold"),
        )


def _size_to_screen(window: tk.Tk) -> None:
    """Open at a comfortable size that still fits the screen.

    A fixed height taller than the desktop pushes the status bar — which is
    where the path and vertex counts live — under the taskbar.
    """
    margin = 80  # taskbar and window chrome
    width = min(1240, window.winfo_screenwidth() - 60)
    height = min(880, window.winfo_screenheight() - margin)
    window.geometry(f"{max(940, width)}x{max(600, height)}+20+20")


def _compose_crop(existing, box):
    """Express a box drawn on an already-cropped image in original fractions."""
    if existing is None:
        return box
    left, top, right, bottom = existing
    width = right - left
    height = bottom - top
    return (
        left + box[0] * width,
        top + box[1] * height,
        left + box[2] * width,
        top + box[3] * height,
    )


class _ScrollableColumn(ttk.Frame):
    """A vertically scrollable container, since the panel outgrows short screens."""

    def __init__(self, master, width: int) -> None:
        super().__init__(master)
        self._canvas = tk.Canvas(self, width=width, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)

        self._canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.interior = ttk.Frame(self._canvas)
        self._window = self._canvas.create_window(
            (0, 0), window=self.interior, anchor="nw"
        )
        self.interior.bind("<Configure>", self._on_interior_resize)
        self._canvas.bind("<Configure>", self._on_canvas_resize)
        # Bound to this widget, not bind_all: the preview canvas needs the
        # wheel for zooming.
        self._canvas.bind("<MouseWheel>", self._on_wheel)
        self.interior.bind("<MouseWheel>", self._on_wheel)

    def _on_interior_resize(self, _event) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_resize(self, event) -> None:
        self._canvas.itemconfigure(self._window, width=event.width)

    def _on_wheel(self, event) -> None:
        self._canvas.yview_scroll(-int(event.delta / 120), "units")


def launch() -> None:
    root = TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
    try:
        # 'vista' on Windows looks native; ignore where it is unavailable.
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
