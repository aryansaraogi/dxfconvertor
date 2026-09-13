"""Entry point for the packaged application.

A module of its own rather than pointing PyInstaller at ``img2dxf/__main__``:
the frozen app has no console, so an exception during startup would otherwise
vanish without trace. Here it can be shown.
"""

from __future__ import annotations

import sys


def main() -> int:
    try:
        from img2dxf.gui import launch

        launch()
        return 0
    except Exception:  # pragma: no cover - only reachable in a frozen build
        import traceback

        message = traceback.format_exc()
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("img2dxf could not start", message)
            root.destroy()
        except Exception:
            print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
