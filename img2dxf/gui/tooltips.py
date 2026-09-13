"""Hover help for the controls, and the text that goes in it.

The panel has more than forty knobs. Most are obvious once explained and
baffling until then, so every one carries a sentence saying what it does and,
more usefully, when you would reach for it and what goes wrong if it is set
badly.

The text is kept here rather than beside each widget so it reads as one voice,
and so a control and its explanation cannot drift apart unnoticed.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

#: How long the pointer must rest before help appears. Long enough not to
#: flicker while crossing the panel, short enough not to feel broken.
DELAY_MS = 600

_WRAP_PX = 280
_BACKGROUND = "#ffffe0"
_BORDER = "#9a9a7a"


class Tooltip:
    """A hover label attached to one widget."""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self._widget = widget
        self._text = text
        self._window: tk.Toplevel | None = None
        self._after_id: str | None = None

        # add="+" so this never displaces a binding the widget already has.
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<Destroy>", self._on_destroy, add="+")

    # -- lifecycle ------------------------------------------------------

    def _schedule(self, _event=None) -> None:
        self._cancel()
        self._after_id = self._widget.after(DELAY_MS, self._show)

    def _cancel(self) -> None:
        if self._after_id is None:
            return
        try:
            self._widget.after_cancel(self._after_id)
        except tk.TclError:
            pass  # the widget is already gone
        self._after_id = None

    def _on_destroy(self, _event=None) -> None:
        """Leave nothing scheduled against a widget that no longer exists."""
        self._cancel()
        self._hide()

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self._window is not None:
            try:
                self._window.destroy()
            except tk.TclError:
                pass
            self._window = None

    def _show(self) -> None:
        self._after_id = None
        if self._window is not None or not self._text:
            return
        try:
            x, y = self._position()
        except tk.TclError:
            return  # the widget went away while we waited

        window = tk.Toplevel(self._widget)
        window.wm_overrideredirect(True)  # no title bar or border
        window.wm_geometry(f"+{x}+{y}")
        try:
            window.wm_attributes("-topmost", True)
        except tk.TclError:
            pass

        tk.Label(
            window,
            text=self._text,
            justify="left",
            background=_BACKGROUND,
            foreground="#000000",
            relief="solid",
            borderwidth=1,
            highlightbackground=_BORDER,
            wraplength=_WRAP_PX,
            padx=8,
            pady=5,
        ).pack()

        self._window = window

    def _position(self) -> tuple[int, int]:
        """Just below the control, nudged back on screen if it would overflow."""
        widget = self._widget
        x = widget.winfo_rootx() + 12
        y = widget.winfo_rooty() + widget.winfo_height() + 6

        screen_width = widget.winfo_screenwidth()
        if x + _WRAP_PX + 30 > screen_width:
            x = max(0, screen_width - _WRAP_PX - 30)
        return x, y


def attach(widget: tk.Widget, text: str) -> Tooltip | None:
    """Give ``widget`` hover help, if there is any to give."""
    if not text:
        return None
    return Tooltip(widget, text)


def attach_field(widget: tk.Widget, field: str) -> Tooltip | None:
    """Give ``widget`` the help registered for a parameter."""
    return attach(widget, HELP.get(field, ""))


def attach_children(parent: tk.Widget, text: str) -> None:
    """Give a group of widgets the same help.

    Used for radio-button rows, where the pointer is as likely to rest on one
    of the buttons as on the frame holding them.
    """
    attach(parent, text)
    for child in parent.winfo_children():
        attach(child, text)


#: Help for each parameter, keyed by its `TraceParams` field name. Written for
#: someone at the machine: what it does, when to reach for it, and what going
#: wrong looks like.
HELP: dict[str, str] = {
    # --- framing -------------------------------------------------------
    "rotate_deg": (
        "Turns the image before anything else happens.\n\n"
        "Use it to straighten a crooked scan or photo. The 90 degree buttons "
        "are for artwork that came in sideways."
    ),
    "detail": (
        "Traces an enlarged copy of the image, so edges are not stuck to the "
        "pixel grid.\n\n"
        "This is the control that decides how clean your edges are - the "
        "tolerance settings cannot make up for it. Auto raises small images "
        "and leaves detailed ones alone, which is right for almost everything. "
        "Raise it by hand if a small logo still looks rough; lower it to 1x if "
        "a very large scan feels slow."
    ),
    # --- adjustments ---------------------------------------------------
    "auto_levels": (
        "Stretches the image so its darkest parts are black and its lightest "
        "are white.\n\n"
        "The first thing to try on a faint scan or a flat photo that traces "
        "into nothing. A few stray specks will not throw it off."
    ),
    "brightness": (
        "Lightens or darkens the whole image before thresholding.\n\n"
        "If too much is being traced, darken; if detail is dropping out, "
        "lighten. Usually easier to adjust the Threshold instead."
    ),
    "contrast": (
        "Pushes lights and darks apart, pivoting around mid-grey so the image "
        "does not also get brighter.\n\n"
        "Helps a washed-out photo separate into something a threshold can "
        "find."
    ),
    "gamma": (
        "Adjusts the midtones only, leaving black and white where they are.\n\n"
        "Below 1 darkens them, above 1 lightens them. The gentlest way to "
        "recover detail lost in shadow."
    ),
    "sharpen": (
        "Crispens edges before tracing.\n\n"
        "Useful on a slightly soft photo. It works against Blur, so use one or "
        "the other, and too much will add speckle along every edge."
    ),
    # --- tracing -------------------------------------------------------
    "mode": (
        "How the image is split into 'burn this' and 'leave this'.\n\n"
        "Otsu picks the level for you and suits logos, clipart and text. "
        "Fixed lets you set it. Adaptive handles scans lit unevenly. "
        "Posterize splits a photo into tone bands, one layer each. "
        "Edges outlines detail without filling it in."
    ),
    "threshold": (
        "Everything darker than this is traced; everything lighter is "
        "ignored.\n\n"
        "Lower it if parts of the artwork are being missed, raise it if the "
        "background is being picked up."
    ),
    "adaptive_block": (
        "How large an area Adaptive mode judges each pixel against.\n\n"
        "Larger looks at more of the surroundings, which suits broad shading; "
        "smaller follows fine detail but can turn noisy."
    ),
    "adaptive_c": (
        "Shifts Adaptive mode's decision a little darker or lighter.\n\n"
        "Raise it if background texture is being traced as artwork."
    ),
    "levels": (
        "How many tone bands a photo is split into.\n\n"
        "Each gets its own layer, so you can give the darker ones more power. "
        "Three or four is usually enough; more means a much longer job."
    ),
    "canny_low": (
        "How faint an edge can be and still be traced.\n\n"
        "Lower it to catch more detail, raise it to ignore texture and noise."
    ),
    "canny_high": (
        "How strong an edge must be to definitely count.\n\n"
        "Usually set around twice the low value."
    ),
    "edge_dilate": (
        "Thickens found edges before tracing them.\n\n"
        "Use it when edge outlines come out broken into dashes."
    ),
    "invert": (
        "Traces the light areas instead of the dark ones.\n\n"
        "For artwork that is white on a black background."
    ),
    # --- cleanup -------------------------------------------------------
    "denoise": (
        "Removes isolated speckles from the image before tracing.\n\n"
        "The right tool for a grainy scan or a dusty original."
    ),
    "blur": (
        "Softens the image before thresholding.\n\n"
        "Smooths ragged edges, at the cost of fine detail. Works against "
        "Sharpen, so use one or the other."
    ),
    "close_px": (
        "Bridges small gaps so broken lines join up.\n\n"
        "Use it when thin strokes come out as dashes. Too much will fill in "
        "narrow gaps you wanted to keep."
    ),
    "open_px": (
        "Removes small specks from the traced shape.\n\n"
        "Similar to Min area, but it cleans the image rather than discarding "
        "finished outlines."
    ),
    # --- vectors -------------------------------------------------------
    "simplify_mm": (
        "How far the traced outline may stray from the image, in "
        "millimetres.\n\n"
        "Higher means fewer points and a lighter file, at the cost of "
        "accuracy. If the shape looks faceted, lower it; if the vertex count "
        "is in the tens of thousands, raise it."
    ),
    "min_area_mm2": (
        "Shapes smaller than this are thrown away.\n\n"
        "The despeckle control. Turn on 'Show dropped' in the toolbar to see "
        "in amber exactly what it is removing, so you can tell dust from "
        "detail you wanted."
    ),
    "smooth": (
        "Rounds off the staircase left by the pixel grid.\n\n"
        "Safe on text: sharp corners are held exactly, and only curves are "
        "softened. Raising it adds points."
    ),
    "corner_deg": (
        "How sharp a turn has to be before it counts as a corner.\n\n"
        "Corners are never smoothed. Lower it if smoothing is rounding off "
        "something that should stay crisp."
    ),
    "straighten_mm": (
        "Flattens edges whose waviness is just pixel noise, so stems and "
        "straight sides come out dead straight.\n\n"
        "Curves are left alone whatever their radius. Set it to 0 to trace "
        "edges exactly as found, and lower it if artwork that really is "
        "curved comes out faceted."
    ),
    "min_run_mm": (
        "The shortest stretch of edge worth straightening.\n\n"
        "Raise it to protect small detail from being flattened."
    ),
    "keep_holes": (
        "Cuts the inner outlines of a shape as well as the outer one.\n\n"
        "This is what keeps the middle of an O open. Turn it off only if you "
        "want solid silhouettes."
    ),
    # --- machine -------------------------------------------------------
    "kerf_mm": (
        "The width of material your beam removes, typically 0.1 to 0.2 mm.\n\n"
        "Cut exactly on the line and the part comes out this much undersized "
        "and its holes this much oversized. To find yours, cut the "
        "calibration piece, measure the error, and halve it."
    ),
    "kerf_side": (
        "Which side of the line to cut on.\n\n"
        "Outside keeps the part its drawn size - the usual choice when the "
        "piece you keep is the one being cut out. Inside keeps the hole its "
        "drawn size, for when a hole has to fit something. Holes and outlines "
        "are offset in opposite directions automatically."
    ),
    "fit_arcs": (
        "Writes true circles and arcs instead of many short straight "
        "segments.\n\n"
        "Smaller files and smoother motion. Turn it off only if your "
        "controller dislikes arcs."
    ),
    "tab_count": (
        "Leaves this many uncut bridges in each closed cut, so the part stays "
        "attached to the sheet.\n\n"
        "Without them a part drops the moment it is finished, tilts in the "
        "slot, and the beam finishes the pass across it. Snap the parts out "
        "afterwards. Four is a sensible start."
    ),
    "tab_mm": (
        "How wide each bridge is.\n\n"
        "0.3 to 1 mm is typical: enough to hold the part, small enough to "
        "snap and clean up. Thicker material wants wider tabs."
    ),
    "optimize_order": (
        "Reorders the cut so the head travels less between shapes.\n\n"
        "Nothing about the geometry changes and holes are still cut before "
        "their outlines. Usually well worth it on a sheet of many parts."
    ),
    # --- layout --------------------------------------------------------
    "copies_x": (
        "How many copies to lay out across the sheet.\n\n"
        "Spacing comes from the job's own size plus the tile gap, so copies "
        "never overlap however odd the shape. The bed check measures the "
        "whole grid, not one copy."
    ),
    "copies_y": (
        "How many copies to lay out down the sheet.\n\n"
        "Combined with the across count this fills a sheet in one job, which "
        "is far quicker than running the same file several times."
    ),
    "tile_gap_mm": (
        "The space left between tiled copies.\n\n"
        "Allow at least a couple of millimetres so neighbouring cuts do not "
        "run into each other."
    ),
    "bed_width_mm": (
        "Your machine's bed size, so the app can warn you before you find out "
        "at the machine.\n\n"
        "The preview draws it as a dashed outline, and the status bar turns "
        "red if the job will not fit. Leave both at 0 to switch the check off."
    ),
    # The two bed boxes sit side by side and mean one thing between them.
    "bed_height_mm": (
        "Your machine's bed size, so the app can warn you before you find out "
        "at the machine.\n\n"
        "The preview draws it as a dashed outline, and the status bar turns "
        "red if the job will not fit. Leave both at 0 to switch the check off."
    ),
    "crop": (
        "Which part of the image is traced.\n\n"
        "Set it by ticking Crop in the toolbar and dragging a box on the "
        "preview. Everything is measured on what is left, so the width you "
        "ask for is the width of the cropped piece."
    ),
    # --- size ----------------------------------------------------------
    "size_mode": (
        "How the finished size is decided.\n\n"
        "Fit to width is the straightforward choice: say how wide you want it "
        "and the height follows. Use image DPI instead when the file already "
        "knows its real-world size."
    ),
    "width_mm": (
        "How wide the finished job should be, in millimetres.\n\n"
        "Set this before anything else: the tolerance and minimum-area "
        "controls are in millimetres, so they change meaning when you rescale. "
        "If you know the true size of a feature instead, measure it on the "
        "preview and use 'Set size...'."
    ),
    "dpi": (
        "The image's real-world resolution, used when sizing by DPI.\n\n"
        "Filled in from the file when it says, and 96 when it does not."
    ),
    "height_mm": (
        "Fit the job to this height instead of a width.\n\n"
        "Available from the command line with --height-mm; the panel sizes by "
        "width, and the height follows the artwork's proportions."
    ),
    "origin": (
        "Where the job sits in the file's coordinates.\n\n"
        "Bottom-left corner at zero suits most laser software; centred on "
        "zero suits jigs and rotary setups."
    ),
    # --- output --------------------------------------------------------
    "dxf_version": (
        "Which flavour of DXF to write.\n\n"
        "R2010 for LightBurn and most modern software. R12 for older "
        "RDWorks and LaserCAD - but note R12 files carry no units at all, so "
        "you must tell the importer the file is in millimetres."
    ),
    "layer_name": (
        "What the cut layer is called in the DXF.\n\n"
        "With Posterize each tone gets its own numbered layer, which is how "
        "you give each one a different power and speed."
    ),
}

#: Help for the toolbar and the preview, keyed by a short control name.
TOOLBAR_HELP: dict[str, str] = {
    "open": "Open a PNG or JPEG. You can also drag an image onto the window.",
    "recent": "Images you have opened before.",
    "export": (
        "Write the job out.\n\n"
        "Choose a .dxf or .svg name and the right format is used."
    ),
    "settings": (
        "Save everything on this panel to a file, or bring a saved job back.\n\n"
        "There are over forty settings, so once a job is dialled in, save it "
        "as a preset and it becomes a single choice next time."
    ),
    "view": (
        "What the preview shows.\n\n"
        "Original is the image as loaded. Mask is what will be burned, in "
        "black. Vectors is the traced outline alone. Overlay puts the outline "
        "over a faded image, which is the best way to check the trace is "
        "following the artwork."
    ),
    "dropped": (
        "Shows in amber the small shapes that Min area is throwing away.\n\n"
        "Turn it on to check the despeckle setting is removing dust and not "
        "detail you wanted."
    ),
    "crop": (
        "Tick, then drag a box on the preview to keep only part of the "
        "image.\n\n"
        "Crops build on each other, so you can narrow down in steps."
    ),
    "clear_crop": "Go back to the whole image.",
    "measure": (
        "Tick, then drag between two points to read the distance in "
        "millimetres.\n\n"
        "The quickest way to check the job is the size you think it is before "
        "committing material."
    ),
    "set_size": (
        "Rescales the whole job so the thing you just measured comes out its "
        "true size.\n\n"
        "Measure something whose real size you know, press this, and type "
        "that size. Better than guessing at a width."
    ),
    "fit": "Fit the whole image in the preview again. Keyboard: F.",
    "advanced": (
        "Shows the tuning sections: image adjustments, cleanup, vector "
        "settings, machine compensation and sheet layout.\n\n"
        "The controls left visible are the ones a job needs to be correct."
    ),
    "preset": (
        "A starting point for the tracing settings.\n\n"
        "Logo / clipart suits flat artwork and text, Photo splits a "
        "photograph into tone bands, Line art / scan copes with uneven "
        "lighting, Edge outline traces detail without filling it. Presets "
        "leave your framing, machine and layout settings alone."
    ),
}


def style_hint(widget: ttk.Label) -> None:
    """Mark a label as secondary guidance rather than a control."""
    widget.configure(foreground="#555555")


#: The walkthrough shown by the ? button, as (heading, body) pairs. Ordered as
#: a job actually goes, not as the panel happens to be laid out.
GUIDE: tuple[tuple[str, str], ...] = (
    (
        "",
        "This turns a picture into an outline your laser can follow. It traces "
        "the boundary between dark and light, so it suits logos, text and line "
        "art best.",
    ),
    (
        "1. Open a picture",
        "Use Open, or drag an image onto the window. PNG and JPEG both work. "
        "Clean, high-contrast artwork gives the best result; a photograph "
        "needs the Photo preset.",
    ),
    (
        "2. Set the size first",
        "Type the finished width in millimetres in the Size section. Do this "
        "before anything else: several other settings are measured in "
        "millimetres, so they change meaning if you rescale afterwards.\n"
        "If you do not know the width but you do know the real size of "
        "something in the picture, tick Measure, drag across that thing, and "
        "press 'Set size...'.",
    ),
    (
        "3. Check the trace",
        "Set the view to Overlay. The blue lines are the outlines that will be "
        "cut and the red ones are holes inside them. Scroll to zoom, drag to "
        "pan, press F to fit.\n"
        "If parts of the artwork are missing, or the background is being "
        "picked up, change Mode or Threshold in the Tracing section.",
    ),
    (
        "4. Tell it about your machine",
        "Tick Advanced to reach these.\n"
        "Kerf is the width of material your beam burns away - without it, "
        "parts come out undersized and holes oversized. Tabs leave small uncut "
        "bridges so a finished part cannot drop through the sheet. Bed is your "
        "machine's size, and the app warns you in red if the job will not fit.",
    ),
    (
        "5. Export",
        "Press Export and choose a name ending in .dxf, or .svg if your "
        "software prefers that. Watch the status bar along the bottom: it "
        "shows how many outlines, how many points, the finished size in "
        "millimetres, and how far the head will travel.",
    ),
    (
        "Before you cut anything real",
        "Run the calibration piece. It is a small plate with holes and a slot "
        "whose sizes are known, and cutting it once tells you whether the "
        "scale is right and what your kerf actually is:\n"
        "    python -m img2dxf.calibrate -o calibration.dxf",
    ),
    (
        "Save the job when it works",
        "Settings then Save settings writes every control to a file, so the "
        "same job can be repeated exactly. Save as preset puts it in the "
        "preset list for next time.",
    ),
    (
        "If something looks wrong",
        "Rough or rippled edges: raise Detail in the Image section. That is "
        "the setting that decides edge quality.\n"
        "Speckles everywhere: raise Min area, and tick 'Show dropped' to see "
        "what is being removed.\n"
        "Broken thin lines: raise 'Bridge gaps', or try Adaptive mode.\n"
        "Far too many points: raise Tolerance.\n"
        "Imported at the wrong size: if you chose R12, that format carries no "
        "units at all, so you must tell your software the file is in "
        "millimetres.",
    ),
    (
        "Hover for help",
        "Every control on the left explains itself if you rest the pointer on "
        "it for a moment.",
    ),
)
