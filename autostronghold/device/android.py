"""This phone or tablet, from inside the Android app.

Screenshots come from the screen recording the player allows when a run starts
(MediaProjection); taps and drags are gestures of the app's accessibility service. Both
live in the Kotlin class ``DeviceBridge``, which Python reaches through Chaquopy.
"""
from __future__ import annotations

import time
from typing import Callable

import cv2
import numpy as np

from ..errors import SetupError
from .base import Device

BRIDGE = "com.autostronghold.app.DeviceBridge"
LANDSCAPE_WAIT = 30.0   # seconds to wait for the game (landscape) after the run starts


def _bytes(java_array) -> bytes:
    """A Java byte[] as Python bytes (Chaquopy arrays support the buffer protocol)."""
    try:
        return memoryview(java_array).tobytes()
    except TypeError:
        return bytes(java_array)


class AndroidDevice(Device):
    name = "本机（安卓）"

    def __init__(self, bridge=None, say: Callable[..., None] | None = None) -> None:
        super().__init__()
        if bridge is None:
            from java import jclass  # type: ignore[import-not-found]  # Chaquopy

            bridge = jclass(BRIDGE)
        self.bridge = bridge
        problem = bridge.problem()
        if problem:
            raise SetupError(str(problem), "回到本程序，按提示开启无障碍服务并允许录屏后再点「开始」。")
        self._wait_landscape(say)

    def _wait_landscape(self, say: Callable[..., None] | None) -> None:
        """The run starts while this app is on screen (portrait); wait until the game is."""
        w, h = self.bridge.displaySize()
        if w > h:
            return
        if say:
            say("等待切换到游戏（横屏）…")
        deadline = time.monotonic() + LANDSCAPE_WAIT
        while time.monotonic() < deadline:
            time.sleep(0.5)
            w, h = self.bridge.displaySize()
            if w > h:
                time.sleep(1.0)   # let the rotation finish before the first screenshot
                return
        raise SetupError("屏幕一直是竖屏，没有看到游戏画面。", "点「开始」后切换到明日方舟，并保持横屏。")

    def describe(self) -> str:
        w, h = self.bridge.displaySize()
        return f"本机屏幕 {max(w, h)}x{min(w, h)}，录屏 + 无障碍手势"

    def _raw_screenshot(self):
        frame = self.bridge.capture()
        if frame is None:
            return None
        w, h, stride = int(frame.width), int(frame.height), int(frame.rowStride)
        rows = np.frombuffer(_bytes(frame.pixels), np.uint8).reshape(h, stride)
        rgba = rows[:, : w * 4].reshape(h, w, 4)
        return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)

    def _raw_tap(self, x, y):
        self.bridge.tap(x, y)

    def _raw_touch_down(self, x, y):
        self.bridge.down(x, y)

    def _raw_touch_move(self, x, y):
        self.bridge.move(x, y)

    def _raw_touch_up(self, x, y):
        self.bridge.up(x, y)

    def close(self) -> None:
        self.bridge.release()
