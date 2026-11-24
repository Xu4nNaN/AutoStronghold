"""Shared state for one program run: device, OCR, timeouts and progress watchdogs."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .. import log
from ..device.base import Device
from ..errors import LeftGarrison, ScreenTimeout, Stalled, UserStopped
from ..vision.ocr import OcrEngine, TextBox
from . import recovery
from .screens import Kind, Screen, classify


@dataclass
class Timeouts:
    leave: float = 60.0      # no Stronghold Protocol screen for this long -> stop
    stall: float = 600.0     # no progress for this long -> stop
    poll: float = 1.0        # pause between looks while waiting


class GameContext:
    def __init__(self, device: Device, ocr: OcrEngine, timeouts: Timeouts | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 stop: threading.Event | None = None,
                 listener: Callable[[str, Any], None] | None = None):
        self.device = device
        self.ocr = ocr
        self.timeouts = timeouts or Timeouts()
        self._sleep = sleep
        self.clock = clock
        self.stop = stop                  # set by a front end to stop the run
        self.listener = listener          # receives ("screen" | "round" | "games", value)
        now = clock()
        self.last_garrison = now
        self.last_progress = now
        self._last_kind: Kind | None = None
        self._recovery_steps = 0          # way-back actions since 卫戍协议 was last seen
        # Called with the start screen each time ensure_lobby settles on it, until it returns True.
        self.on_lobby: Callable[[Screen], bool] | None = None

    # --- run control ---------------------------------------------------------------
    def check_stop(self) -> None:
        if self.stop is not None and self.stop.is_set():
            raise UserStopped("已手动停止。")

    def sleep(self, seconds: float) -> None:
        """Pause; returns at once (raising :class:`UserStopped`) when a stop is requested."""
        self.check_stop()
        if self.stop is not None and self._sleep is time.sleep:
            if self.stop.wait(seconds):
                self.check_stop()
        else:
            self._sleep(seconds)

    def notify(self, event: str, value: Any) -> None:
        if self.listener is not None:
            try:
                self.listener(event, value)
            except Exception:   # a display problem must never stop the run
                pass

    # --- looking -----------------------------------------------------------------
    def look(self) -> Screen:
        """The current screen. The way back from the data update (sync prompt, pop-ups, main
        screen) is walked here, so callers only ever see 卫戍协议 screens (or a loading one)."""
        while True:
            self.check_stop()
            image = self.device.screenshot()
            boxes = self.ocr.read(image)
            screen = classify(image, boxes)
            if screen.outside is None or self._recovery_steps >= recovery.MAX_STEPS:
                break
            self._recovery_steps += 1
            self.last_garrison = self.clock()   # on the way back: not "left 卫戍协议"
            recovery.step(self, screen)
        now = self.clock()
        if screen.in_garrison or screen.kind is not Kind.UNKNOWN:
            self.last_garrison = now
            self._recovery_steps = 0
        if screen.kind is not self._last_kind and screen.kind is not Kind.UNKNOWN:
            self._last_kind = screen.kind
            self.progress()
            self.notify("screen", screen.kind.value)
        return screen

    def read(self, box) -> list[TextBox]:
        return self.ocr.read(self.device.screenshot(), box)

    def progress(self) -> None:
        self.last_progress = self.clock()

    def check_watchdogs(self, screen: Screen) -> None:
        now = self.clock()
        if now - self.last_garrison > self.timeouts.leave:
            log.snapshot(screen.image, "left_garrison")
            raise LeftGarrison(
                f"{int(self.timeouts.leave)} 秒内未检测到卫戍协议画面，已停止。"
                "可能原因：断线、每日 4:00 更新、公告弹窗或已离开卫戍协议。",
                "请回到卫戍协议开始界面后重新运行；未完成的对局可在「断线重连」中继续。")
        if now - self.last_progress > self.timeouts.stall:
            log.snapshot(screen.image, "stalled")
            raise Stalled(
                f"{int(self.timeouts.stall // 60)} 分钟内对局流程没有推进，判定为卡住，已停止。截图已保存至 logs 文件夹。",
                "检查游戏画面是否停在异常界面，处理后回到卫戍协议开始界面重新运行。")

    # --- acting ------------------------------------------------------------------
    def tap(self, x: float, y: float, wait: float = 0.8) -> None:
        self.device.tap(x, y, wait)

    def tap_box(self, box: TextBox, wait: float = 0.8) -> None:
        self.device.tap(box.x, box.y, wait)

    def wait_for(self, kinds: Iterable[Kind], timeout: float, what: str,
                 on_other: Callable[[Screen], None] | None = None) -> Screen:
        """Look until one of ``kinds`` shows up; ``on_other`` may handle other screens."""
        wanted = set(kinds)
        deadline = self.clock() + timeout
        while True:
            screen = self.look()
            if screen.kind in wanted:
                return screen
            self.check_watchdogs(screen)
            if self.clock() > deadline:
                log.snapshot(screen.image, "timeout")
                raise ScreenTimeout(f"等待「{what}」超时（{int(timeout)} 秒），当前画面识别为「{screen.kind.value}」。",
                                    "确认游戏没有卡住或弹出意外窗口，回到卫戍协议开始界面后重新运行。")
            if on_other:
                on_other(screen)
            self.sleep(self.timeouts.poll)
