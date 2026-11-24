"""Device abstraction: every backend exposes 1920x1080 screenshots and input."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod

import cv2
import numpy as np

from ..geometry import HEIGHT, WIDTH


class Device(ABC):
    """A screen we can look at and touch.

    Subclasses implement the ``_raw_*`` methods in device pixels; this class converts
    between device pixels and the fixed 1920x1080 coordinate space used everywhere else.
    """

    name = "device"

    def __init__(self) -> None:
        self.raw_size: tuple[int, int] = (WIDTH, HEIGHT)

    # --- implemented by backends -------------------------------------------------
    @abstractmethod
    def _raw_screenshot(self) -> np.ndarray | None: ...

    @abstractmethod
    def _raw_tap(self, x: int, y: int) -> None: ...

    @abstractmethod
    def _raw_touch_down(self, x: int, y: int) -> None: ...

    @abstractmethod
    def _raw_touch_move(self, x: int, y: int) -> None: ...

    @abstractmethod
    def _raw_touch_up(self, x: int, y: int) -> None: ...

    def close(self) -> None:
        """Release resources (lift a held finger, restore windows, ...)."""

    def describe(self) -> str:
        return self.name

    # --- public API in 1920x1080 space ------------------------------------------
    def screenshot(self, retries: int = 5) -> np.ndarray:
        """A 1920x1080 BGR frame. Black frames are valid (the game fades through black
        between screens); only a missing frame counts as a failure."""
        for _ in range(retries):
            img = self._raw_screenshot()
            if img is not None and img.size:
                if img.ndim == 3 and img.shape[2] == 4:
                    img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                h, w = img.shape[:2]
                if h > w:  # portrait framebuffer: rotate to landscape
                    img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
                    h, w = w, h
                self.raw_size = (w, h)
                if (w, h) != (WIDTH, HEIGHT):
                    img = cv2.resize(img, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA)
                return img
            time.sleep(0.4)
        from ..errors import StopRun

        raise StopRun("截图失败：连续多次没有拿到画面。",
                      "确认游戏窗口没有最小化、模拟器仍在运行，然后重新启动本程序。")

    def _to_raw(self, x: float, y: float) -> tuple[int, int]:
        w, h = self.raw_size
        return int(round(x * w / WIDTH)), int(round(y * h / HEIGHT))

    def tap(self, x: float, y: float, wait: float = 0.6) -> None:
        self._raw_tap(*self._to_raw(x, y))
        if wait:
            time.sleep(wait)

    def touch_down(self, x: float, y: float) -> None:
        self._raw_touch_down(*self._to_raw(x, y))

    def touch_move(self, x: float, y: float) -> None:
        self._raw_touch_move(*self._to_raw(x, y))

    def touch_up(self, x: float, y: float) -> None:
        self._raw_touch_up(*self._to_raw(x, y))

    def move_path(self, x1: float, y1: float, x2: float, y2: float, steps: int = 10,
                  step_delay: float = 0.015) -> None:
        """Move a held finger in a straight line (does not press or release)."""
        steps = max(1, steps)
        for k in range(1, steps + 1):
            self.touch_move(x1 + (x2 - x1) * k / steps, y1 + (y2 - y1) * k / steps)
            if step_delay:
                time.sleep(step_delay)

    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration: float = 0.5,
              hold: float = 0.3, wait: float = 0.6) -> None:
        """Press, move slowly, pause (to kill scroll inertia), release."""
        steps = max(6, int(duration / 0.03))
        self.touch_down(x1, y1)
        self.move_path(x1, y1, x2, y2, steps, duration / steps)
        if hold:
            time.sleep(hold)
        self.touch_up(x2, y2)
        if wait:
            time.sleep(wait)
