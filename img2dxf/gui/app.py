"""Main window: file handling, preview, and export."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np

from ..dxfwrite import units_are_declared, write_dxf
from ..params import TraceParams
from ..pipeline import TraceResult
from ..preprocess import load_image
from .controls import ControlPanel
from .preview import VIEWS, render
from .worker import TraceWorker

IMAGE_TYPES = [
    ("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp"),
    ("All files", "*.*"),
]

#: Redrawing on every pixel of a window resize is wasteful; wait for a pause.
_RESIZE_DEBOUNCE_MS = 120


class App(ttk.Frame):
    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master)
        self.master.title("img2dxf - image to laser DXF")
        self.master.geometry("1180x820")
        self.master.minsize(900, 620)

        self._image: np.ndarray | None = None
        self._image_path: Path | None = None
        self._result: TraceResult | None = None
        self._result_params: TraceParams | None = None
        self._photo = None  # kept alive; Tk does not own PhotoImage references
        self._resize_id: str | None = None

        self._build()
        self._worker = TraceWorker(self, self._on_result, self._on_error)
        self.pack(fill="both", expand=True)

    # -- layout ---------------------------------------------------------

    def _build(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="ns")
        left.rowconfigure(0, weight=1)

        scroller = _ScrollableColumn(left, width=290)
        scroller.grid(row=0, column=0, sticky="ns")
        self.controls = ControlPanel(scroller.interior, self._retrace)
        self.controls.pack(fill="both", expand=True)

        right = ttk.Frame(self, padding=(8, 8))
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(right)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(toolbar, text="Open image...", command=self.open_image).pack(
            side="left"
        )
        self._export_button = ttk.Button(
            toolbar, text="Export DXF...", command=self.export_dxf, state="disabled"
        )
        self._export_button.pack(side="left", padx=6)

        self._view_var = tk.StringVar(value="Overlay")
        ttk.Label(toolbar, text="View").pack(side="left", padx=(16, 4))
        view = ttk.Combobox(
            toolbar,
            textvariable=self._view_var,
            values=list(VIEWS),
            state="readonly",
            width=10,
        )
        view.pack(side="left")
        view.bind("<<ComboboxSelected>>", lambda _e: self._redraw())

        self._canvas = tk.Canvas(right, background="#f2f2f2", highlightthickness=0)
        self._canvas.grid(row=1, column=0, sticky="nsew")
        self._canvas.bind("<Configure>", self._on_canvas_resize)

        self._status = tk.StringVar(value="Open a PNG or JPEG to begin.")
        ttk.Label(right, textvariable=self._status, anchor="w").grid(
            row=2, column=0, sticky="ew", pady=(6, 0)
        )

        self.master.bind("<Control-o>", lambda _e: self.open_image())
        self.master.bind("<Control-s>", lambda _e: self.export_dxf())

    # -- actions --------------------------------------------------------

    def open_image(self) -> None:
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
        height, width = rgb.shape[:2]

        if dpi:
            # The file knows its own resolution, so offer it rather than 96.
            self.controls.set_field("dpi", f"{dpi:g}")

        self._status.set(f"{self._image_path.name} - {width} x {height} px - tracing...")
        self._retrace()

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
        path = filedialog.asksaveasfilename(
            title="Export DXF",
            defaultextension=".dxf",
            initialfile=default,
            filetypes=[("DXF", "*.dxf")],
        )
        if not path:
            return

        try:
            write_dxf(self._result.paths, path, self._result_params)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))
            return

        message = f"Wrote {Path(path).name} - {self._result.summary()}"
        if not units_are_declared(self._result_params.dxf_version):
            # R12 carries no unit, so the operator has to say "mm" on import.
            message += " - R12 stores no units; set mm when importing."
        self._status.set(message)

    def _retrace(self) -> None:
        if self._image is None:
            return
        self._worker.request(self._image, self.controls.params())

    # -- worker callbacks -----------------------------------------------

    def _on_result(self, result: TraceResult, params: TraceParams) -> None:
        self._result = result
        self._result_params = params
        self._export_button.configure(
            state="normal" if result.path_count else "disabled"
        )
        name = self._image_path.name if self._image_path else "image"
        self._status.set(f"{name} - {result.summary()}")
        self._redraw()

    def _on_error(self, error: Exception) -> None:
        self._status.set(f"Trace failed: {error}")

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

        width = self._canvas.winfo_width()
        height = self._canvas.winfo_height()
        self._photo = render(
            self._view_var.get(), self._image, self._result, (width, height)
        )
        if self._photo is not None:
            self._canvas.create_image(
                width // 2, height // 2, image=self._photo, anchor="center"
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
        self._canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _on_interior_resize(self, _event) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_resize(self, event) -> None:
        self._canvas.itemconfigure(self._window, width=event.width)

    def _on_wheel(self, event) -> None:
        self._canvas.yview_scroll(-int(event.delta / 120), "units")


def launch() -> None:
    root = tk.Tk()
    try:
        # 'vista' on Windows looks native; ignore where it is unavailable.
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
