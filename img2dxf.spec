# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for the img2dxf desktop app.

Built one-file so it can be copied to a machine that has no Python at all,
which is the point: the tool should be reachable by double-click from the
workshop PC, not only from a checkout with its virtualenv activated.
"""

block_cipher = None

a = Analysis(
    ["packaging/entry.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    # tkinterdnd2 ships its Tcl extension as package data that PyInstaller
    # cannot see by following imports, so it is collected explicitly. The app
    # degrades gracefully without it, but drag-and-drop is worth keeping.
    hiddenimports=["tkinterdnd2"],
    hookspath=[],
    runtime_hooks=[],
    # Nothing here imports these, and each drags in tens of megabytes.
    excludes=["matplotlib", "PySide6", "PyQt5", "PyQt6", "IPython", "pytest"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="img2dxf",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # A GUI app: no console window behind it.
    console=False,
    disable_windowed_traceback=False,
)
