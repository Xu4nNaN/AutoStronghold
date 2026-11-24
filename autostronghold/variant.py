"""Build variant: the CPU package, the GPU (DirectML) package and the Android app share all code.

The build script writes ``_build_variant.py`` with ``VARIANT = "cpu"``, ``"gpu"`` or ``"android"``.
When running from source the variant follows the installed onnxruntime flavour,
and can be forced with the ``AUTOSTRONGHOLD_VARIANT`` environment variable.
"""
from __future__ import annotations

import os

CPU = "cpu"
GPU = "gpu"
ANDROID = "android"


def current() -> str:
    forced = os.environ.get("AUTOSTRONGHOLD_VARIANT", "").strip().lower()
    if forced in (CPU, GPU, ANDROID):
        return forced
    try:
        from . import _build_variant  # type: ignore[attr-defined]

        return _build_variant.VARIANT
    except ImportError:
        pass
    try:
        import onnxruntime

        return GPU if "DmlExecutionProvider" in onnxruntime.get_available_providers() else CPU
    except Exception:
        return CPU


def label(variant: str | None = None) -> str:
    return {GPU: "GPU 版（DirectML）", ANDROID: "安卓版"}.get(variant or current(), "CPU 版")
