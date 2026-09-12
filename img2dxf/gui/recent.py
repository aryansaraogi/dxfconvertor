"""A small list of recently opened images, remembered between sessions."""

from __future__ import annotations

import json
from pathlib import Path

MAX_ENTRIES = 10

_STORE = Path.home() / ".img2dxf" / "recent.json"


def load() -> list[Path]:
    """Recent images, newest first, skipping any that have since moved."""
    try:
        raw = json.loads(_STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []

    if not isinstance(raw, list):
        return []

    return [Path(item) for item in raw if isinstance(item, str) and Path(item).is_file()]


def remember(path: Path) -> list[Path]:
    """Add ``path`` to the front of the list and save it.

    Failing to write is not worth interrupting the user over — the list is a
    convenience, so a read-only home directory just means it does not persist.
    """
    path = Path(path).resolve()
    entries = [p for p in load() if p != path]
    entries.insert(0, path)
    entries = entries[:MAX_ENTRIES]

    try:
        _STORE.parent.mkdir(parents=True, exist_ok=True)
        _STORE.write_text(
            json.dumps([str(p) for p in entries], indent=2), encoding="utf-8"
        )
    except OSError:
        pass

    return entries
