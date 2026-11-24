"""Locations of bundled resources and of the user's writable data."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Folder that holds the executable (or the project root when run from source).
    The Android app points it at its own files folder (``AUTOSTRONGHOLD_APP_DIR``)."""
    if os.environ.get("AUTOSTRONGHOLD_APP_DIR"):
        return Path(os.environ["AUTOSTRONGHOLD_APP_DIR"])
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """Read-only resources shipped with the program (the Android app unpacks them from its
    assets and names the folder in ``AUTOSTRONGHOLD_RESOURCES``)."""
    if os.environ.get("AUTOSTRONGHOLD_RESOURCES"):
        return Path(os.environ["AUTOSTRONGHOLD_RESOURCES"])
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", app_dir())) / "resources"
    return Path(__file__).resolve().parent.parent / "resources"


def resource(*parts: str) -> Path:
    return resource_dir().joinpath(*parts)


def user_file(name: str) -> Path:
    """User-editable file next to the executable; falls back to the bundled copy."""
    local = app_dir() / name
    return local if local.exists() else resource(name)


def log_dir() -> Path:
    d = Path(os.environ.get("AUTOSTRONGHOLD_LOG_DIR", app_dir() / "logs"))
    d.mkdir(parents=True, exist_ok=True)
    return d
