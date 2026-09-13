"""Generate a calibration piece, to check the whole chain on real material.

Everything else in this project is verified against synthetic artwork and by
re-reading the files that were written. That proves the software agrees with
itself; it does not prove the beam removes the width of material the kerf
setting claims, or that the machine's importer reads millimetres the way the
header says.

This builds a small test piece whose true dimensions are known, runs it
through the ordinary pipeline, and prints what each feature should measure
once cut. Measure the real part, compare, and the numbers say which setting
is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path as FsPath

import cv2
import numpy as np

from .params import TraceParams

#: Pixels per millimetre in the generated artwork. High enough that the
#: drawing is not itself the source of error being measured.
RENDER_PX_PER_MM = 20

#: The piece is this wide; every feature below is placed within it.
PLATE_WIDTH_MM = 80.0
PLATE_HEIGHT_MM = 50.0


@dataclass(frozen=True)
class Feature:
    """One thing to measure on the cut part."""

    name: str
    nominal_mm: float
    what_to_measure: str
    tells_you: str


#: Each feature isolates one setting, so a discrepancy points somewhere.
FEATURES: tuple[Feature, ...] = (
    Feature(
        "Outer plate", PLATE_WIDTH_MM, "overall width",
        "the import scale: wrong here and everything else is too",
    ),
    Feature(
        "Outer plate", PLATE_HEIGHT_MM, "overall height",
        "scale on the other axis, and that nothing is stretched",
    ),
    Feature(
        "Large hole", 20.0, "hole diameter",
        "kerf on an inside cut, and that arcs came through as circles",
    ),
    Feature(
        "Small hole", 6.0, "hole diameter",
        "whether small features survive the kerf",
    ),
    Feature(
        "Slot", 4.0, "slot width",
        "kerf on a narrow cut - the first thing to close up if kerf is wrong",
    ),
    Feature(
        "Square window", 15.0, "window side",
        "kerf on straight inside cuts, and that corners stayed sharp",
    ),
)


def build_image() -> np.ndarray:
    """Render the calibration artwork.

    Drawn as a filled plate with white cut-outs, because that is the shape of
    a real job: an outline to cut out, with holes inside it.
    """
    width = int(PLATE_WIDTH_MM * RENDER_PX_PER_MM)
    height = int(PLATE_HEIGHT_MM * RENDER_PX_PER_MM)
    margin = 2 * RENDER_PX_PER_MM

    image = np.full((height + 2 * margin, width + 2 * margin, 3), 255, np.uint8)

    def mm(value: float) -> int:
        return int(round(value * RENDER_PX_PER_MM))

    # The plate itself.
    cv2.rectangle(
        image,
        (margin, margin),
        (margin + width - 1, margin + height - 1),
        (0, 0, 0), -1, lineType=cv2.LINE_AA,
    )

    white = (255, 255, 255)
    cv2.circle(image, (margin + mm(15), margin + mm(25)), mm(10), white, -1,
               lineType=cv2.LINE_AA)
    cv2.circle(image, (margin + mm(34), margin + mm(13)), mm(3), white, -1,
               lineType=cv2.LINE_AA)
    cv2.rectangle(
        image,
        (margin + mm(30), margin + mm(28)),
        (margin + mm(30) + mm(4), margin + mm(28) + mm(16)),
        white, -1,
    )
    cv2.rectangle(
        image,
        (margin + mm(45), margin + mm(10)),
        (margin + mm(45) + mm(15), margin + mm(10) + mm(15)),
        white, -1,
    )
    return image


def calibration_params(**overrides) -> TraceParams:
    """Settings for the piece: no adjustment, nothing that moves an edge.

    Straightening and smoothing are off so that anything measured off-size is
    the machine or the kerf setting, not a finishing pass. Kerf is left at
    zero deliberately — cut it once uncompensated, measure the error, and that
    error *is* your kerf.
    """
    base = TraceParams(
        width_mm=PLATE_WIDTH_MM + 4.0,  # the plate plus its 2 mm margin
        mode="otsu",
        detail=2,
        simplify_mm=0.02,
        min_area_mm2=0.5,
        smooth=0,
        straighten_mm=0.0,
        kerf_mm=0.0,
        kerf_side="none",
        fit_arcs=True,
    )
    from dataclasses import replace

    return replace(base, **overrides) if overrides else base


def measure(result) -> dict[str, float]:
    """The size of each feature as it actually appears in the written file.

    Reported instead of the nominal sizes because the two are not identical:
    the traced edge sits on the artwork's anti-aliased midpoint, which puts
    holes a few hundredths over and the outline a few hundredths under. The
    question being asked is whether the machine reproduces *the file*, so the
    file is what the operator must compare against.
    """
    sizes: dict[str, float] = {}

    for path in result.paths:
        xs = path.outer[:, 0]
        ys = path.outer[:, 1]
        sizes["Outer plate width"] = float(xs.max() - xs.min())
        sizes["Outer plate height"] = float(ys.max() - ys.min())

        for index, hole in enumerate(path.holes, start=1):
            circle = path.circles.get(index)
            if circle is not None:
                sizes[f"circle_{circle[2] * 2:.2f}"] = circle[2] * 2
                continue
            width = float(hole[:, 0].max() - hole[:, 0].min())
            height = float(hole[:, 1].max() - hole[:, 1].min())
            sizes[f"opening_{min(width, height):.2f}"] = min(width, height)
            if abs(width - height) < 0.5:
                sizes[f"square_{width:.2f}"] = width

    return sizes


def _closest(sizes: dict[str, float], nominal: float) -> float | None:
    """The measured size nearest a nominal one, if anything is close."""
    if not sizes:
        return None
    best = min(sizes.values(), key=lambda value: abs(value - nominal))
    return best if abs(best - nominal) < max(1.0, nominal * 0.1) else None


def checklist(result=None) -> str:
    """What to measure on the cut part, and what each answer means."""
    sizes = measure(result) if result is not None else {}

    lines = [
        "Measure these on the finished part:",
        "",
        f"  {'feature':<15}{'measure':<22}{'in the file':>12}",
        f"  {'-' * 15}{'-' * 22}{'-' * 12:>12}",
    ]
    for feature in FEATURES:
        actual = _closest(sizes, feature.nominal_mm)
        shown = feature.nominal_mm if actual is None else actual
        lines.append(
            f"  {feature.name:<15}{feature.what_to_measure:<22}{shown:>9.2f} mm"
        )

    lines += [
        "",
        "These are what the DXF contains, not round numbers: the traced edge",
        "follows the artwork's anti-aliased midpoint, so it differs from the",
        "nominal size by a few hundredths. Compare your part against these.",
    ]

    lines += [
        "",
        "Reading the result:",
        "",
        "  Everything off by the same PERCENTAGE",
        "    -> the import scale is wrong. Check the importer is reading mm",
        "       (R12 files carry no units at all and must be told).",
        "",
        "  Everything off by the same AMOUNT, holes and outline in opposite",
        "  directions",
        "    -> that amount is your kerf. Halve the difference, set it as",
        "       Kerf, pick a cut side, and cut again.",
        "",
        "  Only the small hole or the slot is off",
        "    -> the kerf is eating narrow features. Expected below about",
        "       twice the beam width.",
        "",
        "  Circles measure differently across than up",
        "    -> a mechanical problem on the machine, not this software.",
    ]
    return "\n".join(lines)


def write(out_path: str | FsPath, params: TraceParams | None = None):
    """Write the calibration DXF and return ``(path, result)``."""
    from .dxfwrite import write_dxf
    from .pipeline import run

    params = params or calibration_params()
    result = run(build_image(), params)
    return write_dxf(result.paths, out_path, params), result


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="img2dxf.calibrate",
        description="Generate a calibration piece to check a real machine.",
    )
    parser.add_argument(
        "-o", "--output", type=FsPath, default=FsPath("calibration.dxf"),
        help="where to write the DXF (or .svg)",
    )
    parser.add_argument(
        "--dxf-version", default="R2010", help="DXF flavour to write"
    )
    parser.add_argument(
        "--png", type=FsPath, help="also save the source artwork as a PNG"
    )
    args = parser.parse_args(argv)

    params = calibration_params(dxf_version=args.dxf_version)

    if args.png:
        cv2.imwrite(str(args.png), build_image())
        print(f"wrote {args.png}")

    if str(args.output).lower().endswith(".svg"):
        from .pipeline import run
        from .svgwrite import write_svg

        result = run(build_image(), params)
        write_svg(result.paths, args.output, params, result.bounds)
        path = args.output
    else:
        path, result = write(args.output, params)

    print(f"wrote {path}")
    print(result.summary())
    print()
    print(checklist(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
