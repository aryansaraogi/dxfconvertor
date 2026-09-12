"""Headless entry point: ``python -m img2dxf.cli logo.png -o logo.dxf``."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from .dxfwrite import write_dxf
from .params import DXF_VERSIONS, PRESETS, TraceParams
from .pipeline import run_file
from .svgwrite import write_svg


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="img2dxf",
        description="Convert a PNG/JPEG image into a laser-ready DXF outline.",
    )
    parser.add_argument("image", type=Path, help="source PNG/JPEG")
    parser.add_argument(
        "-o", "--output", type=Path,
        help="destination DXF (default: alongside the image)",
    )
    parser.add_argument(
        "--preset", choices=sorted(PRESETS), help="start from a named preset"
    )

    frame = parser.add_argument_group("framing")
    frame.add_argument(
        "--rotate", type=float, dest="rotate_deg",
        help="rotate the image by this many degrees before tracing",
    )
    frame.add_argument(
        "--crop", metavar="L,T,R,B",
        help="crop to these fractions of the image, e.g. 0,0,0.5,1 for the left half",
    )

    tone = parser.add_argument_group("image adjustments")
    tone.add_argument(
        "--auto-levels", action="store_true", help="stretch the tonal range to 0-255"
    )
    tone.add_argument("--brightness", type=int, help="-100 to 100")
    tone.add_argument("--contrast", type=float, help="1.0 leaves the image alone")
    tone.add_argument("--gamma", type=float, help="below 1 darkens midtones")
    tone.add_argument("--sharpen", type=float, help="unsharp strength; opposes --blur")

    shape = parser.add_argument_group("tracing")
    shape.add_argument(
        "--mode",
        choices=["otsu", "fixed", "adaptive", "posterize", "edges"],
        help="binarization strategy",
    )
    shape.add_argument("--threshold", type=int, help="cut level for --mode fixed, 0-255")
    shape.add_argument("--levels", type=int, help="tone levels for --mode posterize, 2-8")
    shape.add_argument("--invert", action="store_true", help="trace light areas instead")
    shape.add_argument("--blur", type=int, help="gaussian blur radius in pixels")
    shape.add_argument("--denoise", type=int, help="median filter radius in pixels")
    shape.add_argument("--close", type=int, dest="close_px", help="bridge gaps, in pixels")
    shape.add_argument("--open", type=int, dest="open_px", help="remove specks, in pixels")
    shape.add_argument("--simplify", type=float, dest="simplify_mm", help="tolerance in mm")
    shape.add_argument("--smooth", type=int, help="corner-rounding passes, 0-3")
    shape.add_argument(
        "--min-area", type=float, dest="min_area_mm2", help="drop shapes below this mm²"
    )
    shape.add_argument(
        "--no-holes", action="store_true", help="ignore inner contours"
    )

    size = parser.add_argument_group("sizing")
    size.add_argument("--width-mm", type=float, help="fit output to this width")
    size.add_argument("--height-mm", type=float, help="fit output to this height instead")
    size.add_argument("--dpi", type=float, help="size from image resolution instead of --width-mm")
    size.add_argument("--center", action="store_true", help="centre the output on 0,0")

    machine = parser.add_argument_group("machine")
    machine.add_argument(
        "--kerf", type=float, dest="kerf_mm",
        help="beam width in mm; paths are offset by half of it",
    )
    machine.add_argument(
        "--kerf-side", choices=["none", "outside", "inside"], dest="kerf_side",
        help="outside keeps the part's size, inside keeps the hole's",
    )
    machine.add_argument(
        "--tabs", type=int, dest="tab_count",
        help="uncut bridges per closed path, so parts stay in the sheet",
    )
    machine.add_argument(
        "--tab-mm", type=float, dest="tab_mm", help="width of each bridge, mm"
    )
    machine.add_argument(
        "--no-arcs", action="store_true",
        help="keep every curve as straight segments instead of fitting arcs",
    )

    layout = parser.add_argument_group("layout")
    layout.add_argument(
        "--copies", metavar="COLSxROWS", help="tile a grid of copies, e.g. 3x2"
    )
    layout.add_argument(
        "--tile-gap", type=float, dest="tile_gap_mm", help="space between copies, mm"
    )
    layout.add_argument(
        "--bed", metavar="WxH", help="machine bed in mm, e.g. 400x300; warns if it will not fit"
    )

    out = parser.add_argument_group("output")
    out.add_argument(
        "--format", choices=["dxf", "svg"],
        help="output format (default: from the output file's extension)",
    )
    out.add_argument("--dxf-version", choices=DXF_VERSIONS, help="DXF flavour to write")
    out.add_argument("--layer", dest="layer_name", help="base layer name")
    return parser


def params_from_args(args: argparse.Namespace) -> TraceParams:
    """Fold CLI flags onto the chosen preset, leaving unset flags alone."""
    params = PRESETS[args.preset] if args.preset else TraceParams()

    direct = (
        "mode", "threshold", "levels", "blur", "denoise", "close_px", "open_px",
        "simplify_mm", "smooth", "min_area_mm2", "width_mm", "height_mm",
        "dxf_version", "layer_name", "rotate_deg", "kerf_mm", "kerf_side",
        "brightness", "contrast", "gamma", "sharpen", "tab_count", "tab_mm",
        "tile_gap_mm",
    )
    overrides = {
        name: getattr(args, name)
        for name in direct
        if getattr(args, name, None) is not None
    }

    if args.invert:
        overrides["invert"] = True
    if args.no_holes:
        overrides["keep_holes"] = False
    if args.center:
        overrides["origin"] = "center"
    if args.no_arcs:
        overrides["fit_arcs"] = False
    if args.auto_levels:
        overrides["auto_levels"] = True
    if args.crop:
        overrides["crop"] = _parse_crop(args.crop)
    if args.copies:
        overrides["copies_x"], overrides["copies_y"] = _parse_pair(
            args.copies, "--copies", int
        )
    if args.bed:
        overrides["bed_width_mm"], overrides["bed_height_mm"] = _parse_pair(
            args.bed, "--bed", float
        )
    # A kerf without a side would silently do nothing; assume the common case.
    if args.kerf_mm and not args.kerf_side:
        overrides["kerf_side"] = "outside"
    if args.dpi is not None:
        overrides["size_mode"] = "dpi"
        overrides["dpi"] = args.dpi

    return replace(params, **overrides)


def _parse_pair(text: str, flag: str, cast):
    """Parse a "3x2" style argument into two numbers."""
    parts = text.lower().replace(" ", "").split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"{flag} expects two values, e.g. 3x2")
    try:
        return cast(parts[0]), cast(parts[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{flag} values must be numbers: {exc}")


def _parse_crop(text: str) -> tuple[float, float, float, float]:
    parts = text.replace(" ", "").split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "--crop needs four comma-separated fractions: left,top,right,bottom"
        )
    try:
        left, top, right, bottom = (float(value) for value in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--crop values must be numbers: {exc}")
    return left, top, right, bottom


def _format_from(output: Path | None) -> str:
    """Infer the format from the output extension, defaulting to DXF."""
    if output is not None and output.suffix.lower() == ".svg":
        return "svg"
    return "dxf"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.image.is_file():
        print(f"error: no such image: {args.image}", file=sys.stderr)
        return 2

    params = params_from_args(args)
    result = run_file(args.image, params)

    fmt = args.format or _format_from(args.output)
    output = args.output or args.image.with_suffix(f".{fmt}")

    if fmt == "svg":
        write_svg(result.paths, output, params, result.bounds)
    else:
        write_dxf(result.paths, output, params)

    print(result.summary())
    print(f"wrote {output}")
    if result.path_count == 0:
        print(
            "warning: the DXF is empty — try another --mode or --threshold",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
