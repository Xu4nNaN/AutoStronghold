"""Administrator rights, asked for only when they are needed.

The PC client runs elevated, so touches must come from an elevated process; the emulator
does not need it. The program therefore starts without the UAC prompt, and when a run on
the PC client is started from a normal process it starts itself again elevated (one UAC
prompt) with ``--start`` / ``--check``, which repeats the click in the new window.
"""
from __future__ import annotations

import os
import subprocess
import sys

from .paths import app_dir, is_frozen

START, CHECK = "--start", "--check"


def is_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def relaunch_elevated(args: list[str]) -> bool:
    """Start this program again as administrator. False when refused (UAC declined) or impossible."""
    if os.name != "nt":
        return False
    import ctypes

    if is_frozen():
        exe, params = sys.executable, args
    else:   # from source: the same interpreter, run as a module
        exe, params = sys.executable, ["-m", "autostronghold", *args]
    code = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, subprocess.list2cmdline(params),
                                               str(app_dir()), 1)
    return int(code) > 32   # ShellExecute: >32 success; 5 (access denied) when the prompt was declined
