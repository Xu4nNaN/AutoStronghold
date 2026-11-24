"""Window front end (tkinter): settings on the left, status and log on the right.

Visual language follows the Stronghold Protocol tools it sits next to: near-black panels,
a teal accent, section titles in Chinese with a small English caption and a thin teal
rule (StrongholdAssistant), and the task-column / log layout of MaaAssistantArknights.
The run itself happens in a worker thread through :func:`session.run_session`; the
window only talks to it through a queue and a stop event.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
import tkinter as tk
import traceback
from tkinter import messagebox
from typing import Any, Callable, Sequence

import sys

from . import __version__, elevate, log, variant
from .errors import StopRun, UserStopped
from .features.plans import FEATURES
from .paths import app_dir
from .session import DEVICES, PC_MOUSE_WARNING, RunOptions, run_session

# --- palette ------------------------------------------------------------------------
BG = "#111316"          # window
PANEL = "#181b1f"       # cards
PANEL_HI = "#20242a"    # hovered / selected card
LINE = "#2a2f36"        # borders
TEXT = "#e4e8eb"
DIM = "#8b949c"
FAINT = "#5c656e"
ACCENT = "#21d3a8"      # teal
ACCENT_DIM = "#123d34"
WARN = "#f2b33d"
ERROR = "#ef5b5b"
OK = "#3ddc97"
FONT = "Microsoft YaHei UI"
LEVEL_COLOURS = {"info": TEXT, "ok": OK, "warn": WARN, "error": ERROR, "debug": FAINT, "time": FAINT}
SETTINGS = app_dir() / "data" / "gui.json"
FEATURE_NOTES = {"etching": "极速模拟中有角标的策略达到 20 个即完成",
                 "all_gold": "极速模拟 → 规程等级1，全部策略获得角标",
                 "all_color": "极速模拟 → 规程等级1，全部策略获得彩标"}
STARTUP_GUIDE = """运行前请确认：
    1. 客户端为国服中文版，卫戍协议「更换主题」为默认主题。
    2. 进入「卫戍协议」开始界面（右下角显示「个人模拟」/「联合模拟」）
    3. 模拟器：把显示分辨率调成 1920×1080（测试环境为 MuMu 模拟器 12）；
       PC 端：游戏分辨率设为 1920×1080，游戏内界面缩放设为 100%，窗口不要最小化（可以被其他窗口挡住）。
       PC 端运行时会占用鼠标：程序通过鼠标点击和拖动，期间请注意鼠标使用。
    4. PC 端需要管理员权限（选择 PC 端点「开始」时会请求）。
    5. 运行期间不要操作游戏画面，也不要同时运行 MAA 等其他自动化程序。"""
_scale = 1.0


def px(n: float) -> int:
    """Pixels scaled for the display's DPI (fonts scale by themselves, sizes do not)."""
    return int(round(n * _scale))


def _font(size: int = 10, weight: str = "normal") -> tuple:
    return (FONT, size, weight)


class QueueLogHandler(logging.Handler):
    """Forwards program log records to the window."""

    def __init__(self, post: Callable[[str, Any], None]):
        super().__init__()
        self.post = post

    def emit(self, record: logging.LogRecord) -> None:
        level = {"WARNING": "warn", "ERROR": "error", "CRITICAL": "error", "DEBUG": "debug"}.get(record.levelname, "info")
        self.post("log", (level, record.getMessage()))


class WindowUI:
    """:class:`session.UI` for the worker thread: messages go to the log view, questions
    become dialogs on the window's thread while the worker waits for the answer."""

    def __init__(self, app: "App"):
        self.app = app

    def say(self, message: str, level: str = "info") -> None:
        self.app.post("log", (level, message))

    def _ask(self, make: Callable[[], Any]) -> Any:
        answer: dict[str, Any] = {}
        done = threading.Event()

        def run() -> None:
            try:
                answer["value"] = make()
            finally:
                done.set()

        self.app.post("call", run)
        done.wait()
        return answer.get("value")

    def ask_yes_no(self, question: str, default: bool = False) -> bool:
        result = self._ask(lambda: messagebox.askyesno("AutoStronghold", question, parent=self.app))
        return default if result is None else bool(result)

    def choose(self, title: str, options: Sequence[str], default: int = 0) -> int:
        result = self._ask(lambda: ChoiceDialog(self.app, title, options).result)
        return default if result is None else result


class ChoiceDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, title: str, options: Sequence[str]):
        super().__init__(master, bg=BG)
        self.title("AutoStronghold")
        self.result: int | None = None
        tk.Label(self, text=title, bg=BG, fg=TEXT, font=_font(11, "bold")).pack(padx=20, pady=(16, 8), anchor="w")
        for i, text in enumerate(options):
            tk.Button(self, text=text, command=lambda i=i: self._pick(i), bg=PANEL, fg=TEXT, relief="flat",
                      activebackground=PANEL_HI, activeforeground=TEXT, font=_font(10), anchor="w",
                      padx=12, pady=6, bd=0, highlightthickness=1, highlightbackground=LINE
                      ).pack(fill="x", padx=20, pady=3)
        self.transient(master)
        self.grab_set()
        self.wait_window()

    def _pick(self, index: int) -> None:
        self.result = index
        self.destroy()


class Section(tk.Frame):
    """Card with a Chinese title, a small English caption and a thin teal rule."""

    def __init__(self, master: tk.Misc, title: str, caption: str):
        super().__init__(master, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
        head = tk.Frame(self, bg=PANEL)
        head.pack(fill="x", padx=14, pady=(12, 0))
        tk.Label(head, text=title, bg=PANEL, fg=TEXT, font=_font(12, "bold")).pack(side="left")
        tk.Label(head, text=caption.upper(), bg=PANEL, fg=ACCENT, font=_font(8, "bold")).pack(side="left", padx=8, pady=(4, 0))
        tk.Frame(self, bg=ACCENT, height=2, width=36).pack(anchor="w", padx=14, pady=(6, 8))
        self.body = tk.Frame(self, bg=PANEL)
        self.body.pack(fill="both", expand=True, padx=14, pady=(0, 12))


class Choice(tk.Frame):
    """Selectable card (radio button styled as a chip with a description)."""

    def __init__(self, master: tk.Misc, var: tk.StringVar, value: str, title: str, detail: str = ""):
        super().__init__(master, bg=PANEL, highlightthickness=1, highlightbackground=LINE, cursor="hand2")
        self.var, self.value = var, value
        self.mark = tk.Frame(self, bg=PANEL, width=3)
        self.mark.pack(side="left", fill="y")
        box = tk.Frame(self, bg=PANEL)
        box.pack(side="left", fill="both", expand=True, padx=10, pady=7)
        self.title = tk.Label(box, text=title, bg=PANEL, fg=TEXT, font=_font(10, "bold"), anchor="w")
        self.title.pack(fill="x")
        self.detail = tk.Label(box, text=detail, bg=PANEL, fg=DIM, font=_font(8), anchor="w", justify="left",
                               wraplength=px(270)) if detail else None
        if self.detail:
            self.detail.pack(fill="x")
        for w in (self, box, self.title) + ((self.detail,) if self.detail else ()):
            w.bind("<Button-1>", self._select)
        var.trace_add("write", lambda *_: self.refresh())
        self.refresh()

    def _select(self, _event=None) -> None:
        self.var.set(self.value)

    def refresh(self) -> None:
        on = self.var.get() == self.value
        bg = PANEL_HI if on else PANEL
        for w in (self, self.title) + ((self.detail,) if self.detail else ()):
            w.configure(bg=bg)
        for child in self.winfo_children():
            if child is not self.mark:
                child.configure(bg=bg)
        self.mark.configure(bg=ACCENT if on else bg)
        self.configure(highlightbackground=ACCENT if on else LINE)
        self.title.configure(fg=ACCENT if on else TEXT)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        global _scale
        _scale = max(1.0, self.winfo_fpixels("1i") / 96)
        self.title(f"AutoStronghold {__version__} · {variant.label()}")
        self.configure(bg=BG)
        width = min(px(1120), int(self.winfo_screenwidth() * 0.9))
        height = min(px(760), int(self.winfo_screenheight() * 0.85))
        x = (self.winfo_screenwidth() - width) // 2
        y = max(0, (self.winfo_screenheight() - height) // 2 - px(20))
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(min(px(980), width), min(px(660), height))
        self.events: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.started_at: float | None = None
        self._load_settings()
        self._build()
        log.setup(verbose=False, extra=QueueLogHandler(self.post))
        self.after(100, self._pump)
        self.after(1000, self._tick)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.say(f"AutoStronghold {__version__}（{variant.label()}）已就绪。运行前请先阅读右上角的「运行前须知」。", "warn")

    # --- layout ------------------------------------------------------------------
    def _build(self) -> None:
        header = tk.Frame(self, bg="#0b0d0f", height=64)
        header.pack(fill="x")
        tk.Frame(header, bg=ACCENT, width=4).pack(side="left", fill="y")
        titles = tk.Frame(header, bg="#0b0d0f")
        titles.pack(side="left", padx=16, pady=10)
        tk.Label(titles, text="AutoStronghold", bg="#0b0d0f", fg=TEXT, font=_font(17, "bold")).pack(anchor="w")
        tk.Label(titles, text="卫戍协议自动刷角标  ·  STRONGHOLD PROTOCOL // AUTOMATION", bg="#0b0d0f", fg=DIM,
                 font=_font(8, "bold")).pack(anchor="w")
        right = tk.Frame(header, bg="#0b0d0f")
        right.pack(side="right", padx=16)
        tk.Label(right, text=variant.label(), bg=ACCENT_DIM, fg=ACCENT, font=_font(9, "bold"),
                 padx=10, pady=3).pack(side="right", padx=(10, 0))
        self.guide_button = tk.Button(right, text="⚠  运行前须知", command=self._show_guide, bg=WARN, fg="#2b1d00",
                                      activebackground="#ffc95c", activeforeground="#2b1d00", relief="flat",
                                      font=_font(11, "bold"), bd=0, cursor="hand2", padx=px(16), pady=px(6))
        self.guide_button.pack(side="right")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=14, pady=14)
        left = tk.Frame(body, bg=BG, width=px(330))
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        main = tk.Frame(body, bg=BG)
        main.pack(side="left", fill="both", expand=True, padx=(14, 0))

        device = Section(left, "设备", "Device")
        device.pack(fill="x")
        for key, text in DEVICES.items():
            title, _, detail = text.partition("（")
            Choice(device.body, self.device_var, key, title, detail.rstrip("）")).pack(fill="x", pady=3)
        self.mouse_note = tk.Label(device.body, text="⚠  PC 端运行时会占用鼠标，期间请注意鼠标使用", bg=PANEL, fg=WARN,
                                   font=_font(9, "bold"), anchor="w", justify="left")
        self.device_var.trace_add("write", lambda *_: self._show_mouse_note())
        self._show_mouse_note()

        feature = Section(left, "功能", "Feature")
        feature.pack(fill="x", pady=(12, 0))
        for f in FEATURES:
            Choice(feature.body, self.feature_var, f.key, f.title, FEATURE_NOTES.get(f.key, "")).pack(fill="x", pady=3)

        options = Section(left, "选项", "Options")
        options.pack(fill="x", pady=(12, 0))
        row = tk.Frame(options.body, bg=PANEL)
        row.pack(fill="x", pady=2)
        tk.Label(row, text="最多进行", bg=PANEL, fg=DIM, font=_font(9)).pack(side="left")
        tk.Spinbox(row, from_=0, to=999, width=5, textvariable=self.max_games_var, bg=PANEL_HI, fg=TEXT,
                   buttonbackground=PANEL_HI, insertbackground=TEXT, relief="flat", font=_font(9),
                   highlightthickness=1, highlightbackground=LINE).pack(side="left", padx=6)
        tk.Label(row, text="局（0 = 不限）", bg=PANEL, fg=DIM, font=_font(9)).pack(side="left")
        self._check(options.body, "全角标功能直接从「独立模拟·规程等级1」开始", self.skip_speed_var).pack(fill="x", pady=2)
        if variant.current() == variant.GPU:
            self._check(options.body, "不使用显卡（改用 CPU 识别）", self.cpu_var).pack(fill="x", pady=2)

        self.start_button = tk.Button(left, text="开  始", command=self._toggle, bg=ACCENT, fg="#06231c",
                                      activebackground="#3ee6bd", activeforeground="#06231c", relief="flat",
                                      font=_font(13, "bold"), bd=0, cursor="hand2", pady=10)
        self.start_button.pack(side="bottom", fill="x")
        self.check_button = tk.Button(left, text="连接自检", command=lambda: self._start(check=True), bg=PANEL,
                                      fg=TEXT, activebackground=PANEL_HI, activeforeground=TEXT, relief="flat",
                                      font=_font(10), bd=0, cursor="hand2", pady=6, highlightthickness=1,
                                      highlightbackground=LINE)
        self.check_button.pack(side="bottom", fill="x", pady=(0, 8))

        status = Section(main, "状态", "Status")
        status.pack(fill="x")
        grid = tk.Frame(status.body, bg=PANEL)
        grid.pack(fill="x")
        self.status_vars: dict[str, tk.StringVar] = {}
        for i, (key, label) in enumerate((("state", "运行状态"), ("screen", "当前画面"), ("stage", "阶段"),
                                          ("round", "回合"), ("games", "对局（通关）"), ("elapsed", "运行时长"))):
            cell = tk.Frame(grid, bg=PANEL)
            cell.grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 28), pady=4)
            tk.Label(cell, text=label, bg=PANEL, fg=FAINT, font=_font(8)).pack(anchor="w")
            var = tk.StringVar(value="—")
            self.status_vars[key] = var
            tk.Label(cell, textvariable=var, bg=PANEL, fg=TEXT, font=_font(11, "bold")).pack(anchor="w")
        for c in range(3):
            grid.columnconfigure(c, weight=1)
        self.status_vars["state"].set("待机")

        logs = Section(main, "日志", "Log")
        logs.pack(fill="both", expand=True, pady=(12, 0))
        holder = tk.Frame(logs.body, bg=BG, highlightthickness=1, highlightbackground=LINE)
        holder.pack(fill="both", expand=True)
        self.log_view = tk.Text(holder, bg="#0d0f12", fg=TEXT, font=(FONT, 9), relief="flat", wrap="word",
                                padx=10, pady=8, insertbackground=TEXT, state="disabled", bd=0)
        self.log_view.pack(side="left", fill="both", expand=True)
        for level, colour in LEVEL_COLOURS.items():
            self.log_view.tag_configure(level, foreground=colour)

    def _show_mouse_note(self) -> None:
        if self.device_var.get() == "pc":
            self.mouse_note.pack(fill="x", pady=(4, 0))
        else:
            self.mouse_note.pack_forget()

    def _check(self, master: tk.Misc, text: str, var: tk.BooleanVar) -> tk.Checkbutton:
        return tk.Checkbutton(master, text=text, variable=var, bg=PANEL, fg=TEXT, selectcolor=PANEL_HI,
                              activebackground=PANEL, activeforeground=TEXT, font=_font(9), anchor="w",
                              highlightthickness=0, bd=0)

    # --- settings ----------------------------------------------------------------
    def _load_settings(self) -> None:
        try:
            data = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        self.device_var = tk.StringVar(value=data.get("device", "emulator"))
        self.feature_var = tk.StringVar(value=data.get("feature", FEATURES[0].key))
        self.max_games_var = tk.StringVar(value=str(data.get("max_games", 0)))
        self.skip_speed_var = tk.BooleanVar(value=bool(data.get("skip_speed", False)))
        self.cpu_var = tk.BooleanVar(value=bool(data.get("cpu", False)))

    def _save_settings(self) -> None:
        data = {"device": self.device_var.get(), "feature": self.feature_var.get(),
                "max_games": self._max_games(), "skip_speed": self.skip_speed_var.get(), "cpu": self.cpu_var.get()}
        try:
            SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _max_games(self) -> int:
        try:
            return max(0, int(self.max_games_var.get()))
        except ValueError:
            return 0

    # --- running -----------------------------------------------------------------
    def options(self, check: bool = False) -> RunOptions:
        feature = self.feature_var.get()
        multi_stage = len(next(f for f in FEATURES if f.key == feature).stages) > 1
        return RunOptions(device=self.device_var.get(), feature=feature, max_games=self._max_games(),
                          start_stage=2 if multi_stage and self.skip_speed_var.get() else 1,
                          cpu=self.cpu_var.get(), check=check)

    @property
    def running(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def _toggle(self) -> None:
        if self.running:
            self._stop()
        else:
            self._start()

    def _start(self, check: bool = False) -> None:
        if self.running:
            return
        self._save_settings()
        opts = self.options(check)
        if opts.device == "pc" and not elevate.is_admin():
            self._restart_elevated(check)
            return
        self.stop_event = threading.Event()
        self.started_at = time.monotonic()
        for key in ("screen", "stage", "round", "games"):
            self.status_vars[key].set("—")
        self.status_vars["state"].set("自检中" if check else "运行中")
        self.start_button.configure(text="停  止", bg=ERROR, activebackground="#ff7a7a", fg="#2a0909")
        self.check_button.configure(state="disabled")
        if opts.device == "pc":
            self.say(PC_MOUSE_WARNING, "warn")
        self.say(f"{'连接自检' if check else '开始'}：{DEVICES[opts.device]} · {opts.feature_plan.title}"
                 + (f" · 最多 {opts.max_games} 局" if opts.max_games else ""), "info")
        self.worker = threading.Thread(target=self._work, args=(opts,), daemon=True)
        self.worker.start()

    def _work(self, opts: RunOptions) -> None:
        try:
            report = run_session(opts, WindowUI(self), stop=self.stop_event,
                                 listener=lambda event, value: self.post("status", (event, value)))
            self.post("done", report)
        except UserStopped:
            self.post("stopped", None)
        except StopRun as exc:
            self.post("failed", exc)
        except Exception:
            log.get().error(traceback.format_exc())
            self.post("crashed", traceback.format_exc().strip().splitlines()[-1])

    def _restart_elevated(self, check: bool) -> None:
        """PC client: start again as administrator (one UAC prompt); the new window repeats the click."""
        self.say("PC 端需要管理员权限，正在请求（请在 UAC 窗口中点「是」）…", "info")
        if elevate.relaunch_elevated([elevate.CHECK if check else elevate.START]):
            self.destroy()
        else:
            self.say("没有获得管理员权限，无法操作以管理员身份运行的游戏。可以改用模拟器，或重新点「开始」并在 UAC 窗口中点「是」。",
                     "error")

    def _stop(self) -> None:
        self.stop_event.set()
        self.status_vars["state"].set("正在停止…")
        self.start_button.configure(state="disabled", text="正在停止…")

    def _finished(self, state: str) -> None:
        self.status_vars["state"].set(state)
        self.start_button.configure(state="normal", text="开  始", bg=ACCENT, activebackground="#3ee6bd",
                                    fg="#06231c")
        self.check_button.configure(state="normal")
        self.started_at = None

    # --- thread-safe plumbing ----------------------------------------------------
    def post(self, kind: str, payload: Any) -> None:
        self.events.put((kind, payload))

    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                self._handle(kind, payload)
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def _handle(self, kind: str, payload: Any) -> None:
        if kind == "log":
            self.say(payload[1], payload[0])
        elif kind == "call":
            payload()
        elif kind == "status":
            event, value = payload
            if event == "games":
                self.status_vars["games"].set(f"{value[0]}（{value[1]}）")
            elif event in self.status_vars:
                self.status_vars[event].set(str(value) if value is not None else "?")
        elif kind == "done":
            if payload is None:
                self._finished("自检完成")
            else:
                self.say(payload.message, "ok" if payload.finished else "info")
                self.say(f"本次共进行 {payload.games} 局，通关 {payload.wins} 局。", "info")
                self._finished("已完成" if payload.finished else "已停止")
        elif kind == "stopped":
            self.say("已手动停止。", "warn")
            self._finished("已停止")
        elif kind == "failed":
            self.say(payload.reason, "error")
            if payload.hint:
                self.say("处理建议：" + payload.hint, "warn")
            self._finished("已停止（出错）")
        elif kind == "crashed":
            self.say("程序出现未预料的错误，已停止。详细信息已写入 logs 文件夹：" + payload, "error")
            self._finished("已停止（出错）")

    def say(self, message: str, level: str = "info") -> None:
        view = self.log_view
        view.configure(state="normal")
        view.insert("end", time.strftime("%H:%M:%S  "), "time")
        view.insert("end", message + "\n", level if level in LEVEL_COLOURS else "info")
        lines = int(view.index("end-1c").split(".")[0])
        if lines > 3000:
            view.delete("1.0", f"{lines - 3000}.0")
        view.configure(state="disabled")
        view.see("end")

    def _tick(self) -> None:
        if self.started_at is not None:
            seconds = int(time.monotonic() - self.started_at)
            self.status_vars["elapsed"].set(f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}")
        self.after(1000, self._tick)

    def _show_guide(self) -> None:
        win = tk.Toplevel(self, bg=BG)
        win.title("运行前须知")
        tk.Frame(win, bg=WARN, height=4).pack(fill="x")
        tk.Label(win, text="⚠  运行前须知", bg=BG, fg=WARN, font=_font(13, "bold")).pack(anchor="w", padx=16, pady=(12, 0))
        text = tk.Text(win, bg=PANEL, fg=TEXT, font=_font(11), relief="flat", wrap="none", padx=16, pady=14,
                       width=104, height=8, bd=0, spacing1=4)
        text.insert("1.0", STARTUP_GUIDE)
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, padx=12, pady=12)
        win.transient(self)

    def _close(self) -> None:
        if self.running:
            if not messagebox.askyesno("AutoStronghold", "正在运行，确定要停止并退出吗？", parent=self):
                return
            self.stop_event.set()
            self.worker.join(timeout=5)
        self._save_settings()
        self.destroy()


def enable_dpi_awareness() -> None:
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    enable_dpi_awareness()
    app = App()
    if elevate.START in argv or elevate.CHECK in argv:   # restarted as administrator for the PC client
        app.after(600, lambda: app._start(check=elevate.CHECK in argv))
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
