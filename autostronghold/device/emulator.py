"""Android emulator backends: MaaFramework's AdbController, or plain adb commands."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

import cv2
import numpy as np

from .. import log
from ..errors import SetupError
from .base import Device
from .maa_runtime import MaaInput, quiet_native_output, toolkit

NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW: adb must not flash console windows


@dataclass
class AdbTarget:
    name: str
    adb_path: str
    address: str
    screencap_methods: int = 0
    input_methods: int = 0
    config: dict | None = None

    def label(self) -> str:
        return f"{self.name}（{self.address}）"


def discover(adb_path: str = "", address: str = "") -> list[AdbTarget]:
    """Emulators found by MaaFramework, or the one given on the command line."""
    targets: list[AdbTarget] = []
    try:
        tk = toolkit()
        for d in tk.find_adb_devices(specified_adb=adb_path or None):
            targets.append(AdbTarget(d.name, str(d.adb_path), d.address, d.screencap_methods,
                                     d.input_methods, dict(d.config or {})))
    except Exception as exc:  # MaaFramework missing or failed: fall back to adb itself
        log.debug("MaaFramework device search failed: %r", exc)
    if address:
        chosen = [t for t in targets if t.address == address]
        if chosen:
            return chosen
        adb = adb_path or (targets[0].adb_path if targets else shutil.which("adb") or "")
        return [AdbTarget("指定设备", adb, address)] if adb else []
    if not targets:
        adb = adb_path or shutil.which("adb") or ""
        if adb:
            for serial in _adb_devices(adb):
                targets.append(AdbTarget("adb 设备", adb, serial))
    return targets


def _adb_devices(adb: str) -> list[str]:
    try:
        out = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=15,
                             creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.split()[0] for line in out.splitlines()[1:] if line.strip().endswith("device")]


class MaaAdbDevice(Device):
    """MaaFramework picks the fastest screenshot/touch method (MaaTouch, MuMu extras, ...)."""

    name = "模拟器（MaaFramework）"

    def __init__(self, target: AdbTarget) -> None:
        super().__init__()
        from maa.controller import AdbController
        from maa.define import MaaAdbInputMethodEnum, MaaAdbScreencapMethodEnum

        toolkit()
        sc = target.screencap_methods or MaaAdbScreencapMethodEnum.Default
        # Touches go through MaaTouch/minitouch; the emulator's own SDK input prints a debug
        # line for every touch, which would flood the console.
        im = (target.input_methods or MaaAdbInputMethodEnum.Default) & ~MaaAdbInputMethodEnum.EmulatorExtras
        im = im or MaaAdbInputMethodEnum.Default
        with quiet_native_output():
            ctl = AdbController(target.adb_path, target.address, sc, im, target.config or {})
            connected = ctl.post_connection().wait().succeeded
            self.io = MaaInput(ctl)
            if connected:
                self.io.screenshot()   # the screenshot extension loads on first use
        if not connected:
            raise SetupError(f"MaaFramework 无法连接 {target.label()}。")
        self.target = target

    def describe(self) -> str:
        return f"{self.target.label()}，MaaFramework"

    def close(self) -> None:
        self.io.close()

    def _raw_screenshot(self):
        return self.io.screenshot()

    def _raw_tap(self, x, y):
        self.io.tap(x, y)

    def _raw_touch_down(self, x, y):
        self.io.down(x, y)

    def _raw_touch_move(self, x, y):
        self.io.move(x, y)

    def _raw_touch_up(self, x, y):
        self.io.up()


class PlainAdbDevice(Device):
    """Fallback that only needs adb (slower; dragging needs Android 10+ ``motionevent``)."""

    name = "模拟器（adb 命令）"

    def __init__(self, target: AdbTarget) -> None:
        super().__init__()
        self.target = target
        if ":" in target.address:
            self._run("connect", target.address, serial=False)
        if self._raw_screenshot() is None:
            raise SetupError(f"无法通过 adb 截图：{target.label()}。",
                             "请开启模拟器的「ADB 调试」选项，并关闭其他正在使用 adb 的程序。")
        help_text = self._run("shell", "input", text=True) or ""
        if "motionevent" not in help_text:
            raise SetupError("模拟器系统版本过低，adb 无法执行拖动操作，不能部署干员。",
                             "请改用安卓 12 模拟器（已在 MuMu 模拟器 12 上测试），或安装 VC++ 运行库以启用 MaaFramework。")

    def describe(self) -> str:
        return f"{self.target.label()}，adb 命令"

    def _run(self, *args: str, serial: bool = True, text: bool = False):
        cmd = [self.target.adb_path] + (["-s", self.target.address] if serial else []) + list(args)
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=30, creationflags=NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            return None
        out = r.stdout + r.stderr if text else r.stdout
        return out.decode("utf-8", "ignore") if text else out

    def _raw_screenshot(self):
        raw = self._run("exec-out", "screencap", "-p")
        if not raw:
            return None
        return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)

    def _raw_tap(self, x, y):
        self._run("shell", "input", "tap", str(x), str(y))

    def _raw_touch_down(self, x, y):
        self._run("shell", "input", "motionevent", "DOWN", str(x), str(y))

    def _raw_touch_move(self, x, y):
        self._run("shell", "input", "motionevent", "MOVE", str(x), str(y))

    def _raw_touch_up(self, x, y):
        self._run("shell", "input", "motionevent", "UP", str(x), str(y))


def connect(target: AdbTarget, prefer_maafw: bool = True) -> Device:
    if prefer_maafw:
        try:
            return MaaAdbDevice(target)
        except Exception as exc:
            log.warn("MaaFramework 连接失败（%s），改用 adb 命令方式。", exc)
    return PlainAdbDevice(target)
