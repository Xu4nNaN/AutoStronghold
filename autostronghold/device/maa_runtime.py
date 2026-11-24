"""Loading MaaFramework (LGPL-3.0, used unmodified through its ``maafw`` package)."""
from __future__ import annotations

import ctypes
import os
import sys
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from ..paths import app_dir

_ready = False


@contextmanager
def quiet_native_output():
    """Point the process's standard handles at NUL while native libraries load.

    MuMu's SDK (loaded by MaaFramework for its screenshot extension) prints debug lines
    through its own C runtime, which binds to the console handle when it loads. Loading
    it while the handles point at NUL keeps those lines out of the player's window for
    the rest of the run; our own output is unaffected afterwards.
    """
    if os.name != "nt":
        yield
        return
    k32 = ctypes.windll.kernel32
    k32.GetStdHandle.restype = ctypes.c_void_p
    k32.CreateFileW.restype = ctypes.c_void_p
    k32.SetStdHandle.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    std_out, std_err = ctypes.c_uint32(-11 & 0xFFFFFFFF), ctypes.c_uint32(-12 & 0xFFFFFFFF)
    old_out, old_err = k32.GetStdHandle(std_out), k32.GetStdHandle(std_err)
    nul = k32.CreateFileW("NUL", 0x40000000, 0x3, None, 3, 0, None)   # GENERIC_WRITE, OPEN_EXISTING
    if not nul or nul == ctypes.c_void_p(-1).value:
        yield
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (AttributeError, ValueError):
            pass
    k32.SetStdHandle(std_out, nul)
    k32.SetStdHandle(std_err, nul)
    try:
        yield
    finally:
        k32.SetStdHandle(std_out, old_out)
        k32.SetStdHandle(std_err, old_err)


_dll_dirs: list = []   # keeps the add_dll_directory handles alive


def _register_native_libraries() -> None:
    """Let Windows find MaaFramework's DLLs, which ship in the package's ``bin`` folder.

    Python only searches registered directories for a DLL's own dependencies, so the
    folder is registered once before the toolkit is imported.
    """
    if _dll_dirs:
        return
    folder = Path(str(resources.files("maa"))) / "bin"
    if not folder.is_dir():
        return
    if hasattr(os, "add_dll_directory"):
        _dll_dirs.append(os.add_dll_directory(str(folder)))
    os.environ["PATH"] = os.pathsep.join([str(folder), os.environ.get("PATH", "")])


def toolkit():
    """Import and initialise ``maa.toolkit.Toolkit`` once; raises ImportError/OSError on failure."""
    global _ready
    _register_native_libraries()
    from maa.toolkit import Toolkit

    if not _ready:
        data = app_dir() / "data" / "maafw"
        data.mkdir(parents=True, exist_ok=True)
        Toolkit.init_option(str(data))
        _ready = True
    return Toolkit


class MaaInput:
    """Shared input/screenshot calls for any ``maa.controller.Controller``."""

    def __init__(self, controller) -> None:
        self.ctl = controller
        try:
            controller.set_screenshot_use_raw_size(True)
        except Exception:
            pass

    def screenshot(self):
        job = self.ctl.post_screencap().wait()
        img = job.get() if hasattr(job, "get") else None
        if img is None:
            img = self.ctl.cached_image
        return img

    def tap(self, x: int, y: int) -> None:
        self.ctl.post_click(x, y).wait()

    def down(self, x: int, y: int) -> None:
        self.ctl.post_touch_down(x, y).wait()

    def move(self, x: int, y: int) -> None:
        self.ctl.post_touch_move(x, y).wait()

    def up(self) -> None:
        self.ctl.post_touch_up().wait()

    def close(self) -> None:
        """Drop the controller: MaaFramework frees its native handle (and adb / window hooks)."""
        self.ctl = None
