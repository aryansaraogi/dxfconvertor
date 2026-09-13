"""Build the standalone executable.

    .\.venv\Scripts\python.exe packaging\build.py

Leaves `dist/img2dxf.exe`, which runs on a machine with no Python installed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "img2dxf.spec"


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print(
            "PyInstaller is not installed. Run:\n"
            "  .\.venv\Scripts\python.exe -m pip install pyinstaller",
            file=sys.stderr,
        )
        return 1

    # A stale build directory is the usual cause of a build that succeeds but
    # ships the previous version's code.
    for stale in (ROOT / "build", ROOT / "dist"):
        shutil.rmtree(stale, ignore_errors=True)

    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm"],
        cwd=ROOT,
    )
    if result.returncode != 0:
        return result.returncode

    exe = ROOT / "dist" / "img2dxf.exe"
    if not exe.is_file():
        print("the build reported success but produced no exe", file=sys.stderr)
        return 1

    print(f"\nbuilt {exe}  ({exe.stat().st_size / 1_000_000:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
