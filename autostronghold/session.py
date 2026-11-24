"""One run: GPU check → connect → self-check → feature.

The window (``gui``) calls :func:`run_session` from a worker thread and passes a :class:`UI`
that decides how messages are shown and how questions are asked (tests pass a fake one).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol, Sequence

from . import log, variant
from .device.base import Device
from .errors import SetupError
from .features.plans import FEATURES, Feature

DEVICES = {"emulator": "模拟器（MuMu / 雷电 / 蓝叠等）", "pc": "PC 客户端（鹰角启动器版，需管理员权限；运行时会占用鼠标）"}
PC_MOUSE_WARNING = "PC 端运行时程序会控制鼠标（点击、拖动都通过鼠标完成），期间请注意鼠标使用。"


class UI(Protocol):
    def say(self, message: str, level: str = "info") -> None:
        """Show a line; level is "info", "ok", "warn" or "error"."""

    def ask_yes_no(self, question: str, default: bool = False) -> bool: ...

    def choose(self, title: str, options: Sequence[str], default: int = 0) -> int: ...


@dataclass
class RunOptions:
    device: str = "emulator"          # "emulator" | "pc" | "android" (this phone, Android app only)
    feature: str = FEATURES[0].key
    max_games: int = 0
    start_stage: int = 1
    cpu: bool = False                 # GPU build: use the CPU anyway
    check: bool = False               # self-check only

    @property
    def feature_plan(self) -> Feature:
        return next(f for f in FEATURES if f.key == self.feature)


def decide_gpu(force_cpu: bool, ui: UI) -> bool:
    """GPU build: make sure a usable GPU exists, otherwise say why and offer the CPU."""
    if variant.current() != variant.GPU or force_cpu:
        return False
    from .accel import check_gpu

    ui.say("正在检测显卡（DirectML）…")
    report = check_gpu()
    if report.usable:
        ui.say(f"显卡可用：{'、'.join(report.adapters) or 'DirectML 设备'}", "ok")
        return True
    ui.say("GPU 版无法使用显卡加速：" + report.reason, "error")
    ui.say("GPU 版需要支持 DirectX 12 的显卡（NVIDIA / AMD / Intel 均可）和较新的显卡驱动；"
           "没有可用显卡时请改用 CPU 版（AutoStronghold-CPU）。", "warn")
    if ui.ask_yes_no("GPU 版没有检测到可用显卡。\n是否改用 CPU 继续本次运行？", default=False):
        return False
    raise SetupError("GPU 版未检测到可用显卡，已按选择退出。", "使用 CPU 版，或更新显卡驱动后重试。")


def connect_emulator(opts: RunOptions, ui: UI) -> Device:
    from .device import emulator

    ui.say("正在查找模拟器…")
    targets = emulator.discover()
    if not targets:
        raise SetupError("没有找到正在运行的安卓模拟器。",
                         "请启动模拟器与游戏，并开启模拟器的「ADB 调试」选项。")
    target = targets[0]
    if len(targets) > 1:
        target = targets[ui.choose("找到多个模拟器，请选择：", [t.label() for t in targets], default=0)]
    return emulator.connect(target)


def connect_pc(opts: RunOptions, ui: UI) -> Device:
    from .device.pc import PcDevice

    return PcDevice()


def connect_android(opts: RunOptions, ui: UI) -> Device:
    from .device.android import AndroidDevice

    return AndroidDevice(say=ui.say)


UI_SCALE_WARNING = ("开始界面的按钮位置与 100% 界面缩放时不一致，游戏内界面缩放可能不是 100%。"
                    "请在游戏设置中检查，否则识别和点击位置会出现偏差。")


def check_ui_scale(boxes, ui: UI) -> bool:
    """PC client: warn when the start screen does not have the 100 % UI-scale layout.
    False if it could not be checked (the 卫戍协议 start screen is not shown)."""
    from .vision.uiscale import matches_default, panel_spacing_percent

    percent = panel_spacing_percent(boxes)
    if percent is None:
        return False
    log.debug("开始界面按钮间距为 100%% 界面缩放时的 %d%%", percent)
    if matches_default(percent):
        ui.say("游戏内界面缩放：100%", "ok")
    else:
        ui.say(UI_SCALE_WARNING, "warn")
    return True


def self_check(device: Device, ocr, ui: UI, pc: bool = False) -> bool:
    """Screenshot, OCR and (PC) in-game UI scale. True when the UI scale was checked."""
    from .game.screens import classify

    image = device.screenshot()
    w, h = device.raw_size
    if abs(w / h - 16 / 9) > 0.02:
        raise SetupError(f"画面比例不是 16:9（{w}x{h}）。",
                         "把模拟器或游戏分辨率改为 1920x1080；安卓版只能在 16:9 屏幕的设备上使用。")
    note = "" if (w, h) == (1920, 1080) else "（已按比例换算；推荐直接使用 1920x1080）"
    ui.say(f"截图：{w}x{h}{note}", "ok")
    started = time.monotonic()
    boxes = ocr.read(image)
    screen = classify(image, boxes)
    ui.say(f"文字识别：{'显卡' if ocr.on_gpu() else 'CPU'}，整屏 {time.monotonic() - started:.1f} 秒，"
           f"当前画面：{screen.kind.value}", "ok")
    if not pc:
        return False
    if check_ui_scale(boxes, ui):
        return True
    ui.say("当前不在卫戍协议开始界面，将在进入开始界面后检查游戏内界面缩放。")
    return False


def run_session(opts: RunOptions, ui: UI, stop: threading.Event | None = None,
                listener: Callable[[str, Any], None] | None = None):
    """Run one session; returns the feature's RunReport (None for a self-check)."""
    feature = opts.feature_plan
    use_gpu = decide_gpu(opts.cpu, ui)
    from .vision.ocr import OcrEngine

    connect = {"pc": connect_pc, "android": connect_android}.get(opts.device, connect_emulator)
    device = connect(opts, ui)
    ocr = ctx = None
    try:
        ui.say(f"已连接：{device.describe()}", "ok")
        ocr = OcrEngine(use_gpu=use_gpu)
        scale_checked = self_check(device, ocr, ui, pc=opts.device == "pc")
        if opts.check:
            ui.say("自检完成。", "ok")
            return None

        from .features.runner import FeatureRunner
        from .game.board import Layout
        from .game.context import GameContext
        from .tactics import tactic_for

        ctx = GameContext(device, ocr, stop=stop, listener=listener)
        if opts.device == "pc" and not scale_checked:
            ctx.on_lobby = lambda screen: check_ui_scale(screen.boxes, ui)
        log.info("开始运行「%s」，打法按模式与规程等级选择", feature.title)
        return FeatureRunner(ctx, feature, tactic_for, Layout.load(), max_games=opts.max_games,
                             start_stage=opts.start_stage, new_ocr=lambda: OcrEngine(use_gpu=use_gpu)).run()
    finally:
        for engine in (ocr, ctx and ctx.ocr):   # the runner replaces the engine after each game
            if engine is not None:
                engine.close()
        device.close()
