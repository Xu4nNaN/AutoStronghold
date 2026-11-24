"""Arknights PC client (Hypergryph launcher) through MaaFramework's Win32Controller."""
from __future__ import annotations

import ctypes
import os

from .. import log
from ..elevate import is_admin
from ..errors import SetupError
from .base import Device
from .maa_runtime import MaaInput, toolkit

WINDOW_TITLES = ("明日方舟", "Arknights")
WINDOW_CLASS = "UnityWndClass"
# Input methods tried in order. AnchoredTouch works in the background without moving
# the real mouse; PostMessageWithCursorPos briefly moves the cursor; Seize takes it over.
INPUT_ORDER = ("AnchoredTouch", "PostMessageWithCursorPos", "Seize")


def client_size(hwnd: int) -> tuple[int, int]:
    import ctypes.wintypes as wt

    rect = wt.RECT()
    ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect))
    return rect.right - rect.left, rect.bottom - rect.top


class PcDevice(Device):
    name = "PC 端（MaaFramework）"

    def __init__(self, input_method: str = "") -> None:
        super().__init__()
        if os.name != "nt":
            raise SetupError("PC 端模式只支持 Windows。")
        try:
            # Real pixel sizes whatever the Windows display scaling is (it does not matter).
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass
        if not is_admin():
            raise SetupError("PC 端需要以管理员身份运行本程序：游戏以管理员身份运行，权限较低的程序无法向其发送操作。",
                             "选择 PC 端点「开始」时，在弹出的 UAC 窗口中点「是」。")
        try:
            tk = toolkit()
            from maa.controller import Win32Controller
            from maa.define import MaaWin32InputMethodEnum as IM
            from maa.define import MaaWin32ScreencapMethodEnum as SC
        except Exception as exc:
            raise SetupError(f"MaaFramework 加载失败：{exc}",
                             "可尝试安装 Microsoft Visual C++ 2015-2022 (x64) 运行库，并检查程序文件夹是否完整。") from exc

        windows = [w for w in tk.find_desktop_windows()
                   if w.class_name == WINDOW_CLASS and w.window_name in WINDOW_TITLES]
        if not windows:
            raise SetupError("找不到正在运行的明日方舟 PC 客户端窗口。",
                             "先启动游戏并进入卫戍协议开始界面，游戏窗口不要最小化，然后重新运行本程序。")
        hwnd = windows[0].hwnd
        self.hwnd = int(hwnd.value if hasattr(hwnd, "value") else hwnd)
        w, h = client_size(self.hwnd)
        if w <= 0 or h <= 0:
            raise SetupError("游戏窗口处于最小化状态，无法截图。", "把游戏窗口还原（不要最小化）后重新运行。")
        if abs(w / h - 16 / 9) > 0.02:
            raise SetupError(f"游戏画面比例不是 16:9（当前 {w}x{h}）。",
                             "在游戏设置中把分辨率改为 1920x1080（或其他 16:9 分辨率）。")
        self.client = (w, h)

        order = [input_method] if input_method else list(INPUT_ORDER)
        last_error = ""
        for method in order:
            im = getattr(IM, method, None)
            if im is None:
                last_error = f"未知的输入方式 {method}"
                continue
            ctl = Win32Controller(hwnd, SC.PrintWindow, im, IM.PostMessage)
            if ctl.post_connection().wait().succeeded:
                self.io = MaaInput(ctl)
                self.input_method = method
                break
            last_error = f"{method} 连接失败"
        else:
            raise SetupError(f"MaaFramework 无法连接游戏窗口（{last_error}）。",
                             "确认以管理员身份运行，且游戏窗口没有最小化。")
        log.debug("PC client %sx%s, input %s", w, h, self.input_method)

    def describe(self) -> str:
        return f"PC 端 {self.client[0]}x{self.client[1]}，输入方式 {self.input_method}"

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
