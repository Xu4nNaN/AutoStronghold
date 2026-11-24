"""Android front end: the Kotlin run service calls into this module through Chaquopy.

It plays the part ``gui`` plays on Windows. :func:`setup` is called once when the app
starts; :func:`run` runs one session on the service's worker thread and reports to a
Kotlin ``RunSink`` (``log(level, text)``, ``status(key, value)``, ``finished(state)``);
:func:`stop` asks the running session to stop.
"""
from __future__ import annotations

import logging
import os
import threading
import traceback
from typing import Any, Sequence

from . import __version__, log, variant
from .errors import StopRun, UserStopped
from .features.plans import FEATURES
from .session import RunOptions, run_session

_sink: Any = None
_stop = threading.Event()


class SinkLogHandler(logging.Handler):
    """Forwards program log records to the app's log view."""

    def emit(self, record: logging.LogRecord) -> None:
        if _sink is not None:
            level = {"WARNING": "warn", "ERROR": "error", "CRITICAL": "error", "DEBUG": "debug"}.get(record.levelname, "info")
            _sink.log(level, record.getMessage())


class SinkUI:
    """:class:`session.UI` for the app. Its two questions never come up on a phone (GPU
    build, several emulators), so they take the default answer."""

    def say(self, message: str, level: str = "info") -> None:
        if _sink is not None:
            _sink.log(level, message)

    def ask_yes_no(self, question: str, default: bool = False) -> bool:
        return default

    def choose(self, title: str, options: Sequence[str], default: int = 0) -> int:
        return default


def setup(app_dir: str, resource_dir: str) -> str:
    """Point logs, settings overrides and resources at the app's folders; returns the title."""
    os.environ["AUTOSTRONGHOLD_APP_DIR"] = app_dir
    os.environ["AUTOSTRONGHOLD_RESOURCES"] = resource_dir
    log.setup(verbose=False, extra=SinkLogHandler())
    return f"AutoStronghold {__version__} · {variant.label()}"


def features() -> list[list[str]]:
    """[key, title, summary] for each feature, in menu order."""
    return [[f.key, f.title, f.summary] for f in FEATURES]


def options(feature: str, max_games: int, skip_speed: bool, check: bool) -> RunOptions:
    multi_stage = len(next(f for f in FEATURES if f.key == feature).stages) > 1
    return RunOptions(device="android", feature=feature, max_games=max(0, int(max_games)),
                      start_stage=2 if multi_stage and skip_speed else 1, check=check)


def run(feature: str, max_games: int, skip_speed: bool, check: bool, sink: Any) -> None:
    """One session; every outcome ends with ``sink.finished(state)``."""
    global _sink
    _sink = sink
    _stop.clear()
    ui = SinkUI()
    opts = options(feature, max_games, skip_speed, check)
    ui.say(f"{'连接自检' if check else '开始'}：本机 · {opts.feature_plan.title}"
           + (f" · 最多 {opts.max_games} 局" if opts.max_games else ""))

    def status(event: str, value: Any) -> None:
        if event == "games":
            sink.status("games", f"{value[0]}（{value[1]}）")
        else:
            sink.status(event, str(value) if value is not None else "?")

    try:
        report = run_session(opts, ui, stop=_stop, listener=status)
        if report is None:
            sink.finished("自检完成")
        else:
            ui.say(report.message, "ok" if report.finished else "info")
            ui.say(f"本次共进行 {report.games} 局，通关 {report.wins} 局。")
            sink.finished("已完成" if report.finished else "已停止")
    except UserStopped:
        ui.say("已手动停止。", "warn")
        sink.finished("已停止")
    except StopRun as exc:
        ui.say(exc.reason, "error")
        if exc.hint:
            ui.say("处理建议：" + exc.hint, "warn")
        sink.finished("已停止（出错）")
    except Exception:
        log.get().error(traceback.format_exc())
        ui.say("程序出现未预料的错误，已停止。详细信息已写入 logs 文件夹："
               + traceback.format_exc().strip().splitlines()[-1], "error")
        sink.finished("已停止（出错）")


def stop() -> None:
    _stop.set()
