"""Headless entry point: ``python -m img2dxf.cli logo.png -o logo.dxf``."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from .dxfwrite import write_dxf
from .params import DXF_VERSIONS, PRESETS, TraceParams
from .pipeline import run_file


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

    out = parser.add_argument_group("output")
    out.add_argument("--dxf-version", choices=DXF_VERSIONS, help="DXF flavour to write")
    out.add_argument("--layer", dest="layer_name", help="base layer name")
    return parser


def params_from_args(args: argparse.Namespace) -> TraceParams:
    """Fold CLI flags onto the chosen preset, leaving unset flags alone."""
    params = PRESETS[args.preset] if args.preset else TraceParams()

    direct = (
        "mode", "threshold", "levels", "blur", "denoise", "close_px", "open_px",
        "simplify_mm", "smooth", "min_area_mm2", "width_mm", "height_mm",
        "dxf_version", "layer_name",
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
    if args.dpi is not None:
        overrides["size_mode"] = "dpi"
        overrides["dpi"] = args.dpi

    return replace(params, **overrides)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.image.is_file():
        print(f"error: no such image: {args.image}", file=sys.stderr)
        return 2

    params = params_from_args(args)
    result = run_file(args.image, params)

    output = args.output or args.image.with_suffix(".dxf")
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
