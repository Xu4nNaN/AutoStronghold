"""File logging (plus the window's log view) and diagnostic screenshots."""
from __future__ import annotations

import logging
import time
from pathlib import Path

import cv2
import numpy as np

from .paths import log_dir

_logger = logging.getLogger("autostronghold")


def setup(verbose: bool = False, extra: logging.Handler | None = None) -> Path:
    """Log to a daily file plus ``extra`` (the window's log view); without it (development
    scripts) the second output is stderr."""
    path = log_dir() / f"run_{time.strftime('%Y%m%d')}.log"
    if _logger.handlers:
        return path
    _logger.setLevel(logging.DEBUG)
    shown = extra if extra is not None else logging.StreamHandler()
    shown.setLevel(logging.DEBUG if verbose else logging.INFO)
    shown.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    file = logging.FileHandler(path, encoding="utf-8")
    file.setLevel(logging.DEBUG)
    file.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    _logger.addHandler(shown)
    _logger.addHandler(file)
    # Third-party loggers (RapidOCR prints INFO lines on start) only go to the file.
    for name in ("RapidOCR", "OrtInferSession"):
        other = logging.getLogger(name)
        other.handlers.clear()
        other.addHandler(file)
        other.propagate = False
    return path


def get() -> logging.Logger:
    return _logger


def info(msg: str, *args) -> None:
    _logger.info(msg, *args)


def warn(msg: str, *args) -> None:
    _logger.warning(msg, *args)


def debug(msg: str, *args) -> None:
    _logger.debug(msg, *args)


_saved_tags: dict[str, int] = {}


def snapshot(image: np.ndarray | None, tag: str, limit: int = 20) -> Path | None:
    """Save a screenshot for diagnosis; at most ``limit`` files per tag per run."""
    if image is None:
        return None
    count = _saved_tags.get(tag, 0)
    if count >= limit:
        return None
    _saved_tags[tag] = count + 1
    path = log_dir() / f"{time.strftime('%Y%m%d_%H%M%S')}_{tag}.png"
    ok, buf = cv2.imencode(".png", image)
    if ok:
        path.write_bytes(buf.tobytes())  # cv2.imwrite cannot handle non-ASCII paths on Windows
        return path
    return None
