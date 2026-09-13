"""Save and reload a job's settings, and the user's own presets.

`TraceParams` has grown past thirty fields. Dialling in a job and then having
no way to reproduce it is the practical problem this solves: the settings go
next to the image as JSON, and a tuned set can be named and kept.

Fields are enumerated from the dataclass rather than listed here, so a new
parameter is persisted the moment it is added — matching the rule that
`TraceParams` is the only place a knob is declared.
"""

from __future__ import annotations

import json
from dataclasses import fields, replace
from pathlib import Path

from .params import TraceParams

#: Written into every file. Nothing reads it yet, but a file that cannot say
#: which version wrote it is a file that cannot be migrated later.
FORMAT_VERSION = 1

#: Where named presets live, alongside the recent-files list.
PRESETS_PATH = Path.home() / ".img2dxf" / "presets.json"

#: The suffix appended to an image's name for its companion settings file.
SETTINGS_SUFFIX = ".img2dxf.json"


def to_dict(params: TraceParams) -> dict:
    """Every field of ``params``, in a JSON-safe form."""
    out: dict = {"version": FORMAT_VERSION}
    for field in fields(params):
        value = getattr(params, field.name)
        # crop is a tuple; JSON has no tuples, so it round-trips as a list.
        out[field.name] = list(value) if isinstance(value, tuple) else value
    return out


def from_dict(data: dict) -> TraceParams:
    """Rebuild parameters from a saved dict.

    Unknown keys are ignored and missing ones keep their defaults, so a file
    written by a different version still loads instead of failing outright.
    """
    known = {field.name for field in fields(TraceParams)}
    values = {key: value for key, value in data.items() if key in known}

    if isinstance(values.get("crop"), list):
        values["crop"] = tuple(values["crop"])

    return replace(TraceParams(), **values).normalized()


def save(params: TraceParams, path: str | Path) -> Path:
    """Write ``params`` to ``path`` as JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_dict(params), indent=2), encoding="utf-8")
    return path


def load(path: str | Path) -> TraceParams:
    """Read parameters back from a file written by :func:`save`."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("settings file does not contain a settings object")
    return from_dict(data)


def companion_path(image_path: str | Path) -> Path:
    """Where a job's settings live if they sit beside the image."""
    image_path = Path(image_path)
    return image_path.with_name(image_path.name + SETTINGS_SUFFIX)


# --- named presets ---------------------------------------------------------


def load_presets() -> dict[str, TraceParams]:
    """The user's own saved presets, newest file wins over a broken one."""
    try:
        raw = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

    if not isinstance(raw, dict):
        return {}

    presets = {}
    for name, data in raw.items():
        if isinstance(data, dict):
            try:
                presets[name] = from_dict(data)
            except (TypeError, ValueError):
                continue  # one bad entry must not lose the rest
    return presets


def save_preset(name: str, params: TraceParams) -> dict[str, TraceParams]:
    """Add or replace a named preset and write the file."""
    name = name.strip()
    if not name:
        raise ValueError("a preset needs a name")

    presets = load_presets()
    presets[name] = params
    _write_presets(presets)
    return presets


def delete_preset(name: str) -> dict[str, TraceParams]:
    presets = load_presets()
    presets.pop(name, None)
    _write_presets(presets)
    return presets


def _write_presets(presets: dict[str, TraceParams]) -> None:
    """Persist presets, treating a read-only home as a non-event.

    Presets are a convenience; failing to store one is not worth interrupting
    a job over.
    """
    try:
        PRESETS_PATH.parent.mkdir(parents=True, exist_ok=True)
        PRESETS_PATH.write_text(
            json.dumps(
                {name: to_dict(params) for name, params in presets.items()}, indent=2
            ),
            encoding="utf-8",
        )
    except OSError:
        pass
