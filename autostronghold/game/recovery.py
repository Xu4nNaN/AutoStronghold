"""The way back to 卫戍协议 after the daily 4:00 data update.

A game in progress at 4:00 goes on until its settlement, where 「数据已更新，即将进行同步」
sends the player to the game's main screen. From there: close the 今日配给 / sign-in / notice
pop-ups, tap the 卫戍协议「规程」 banner, and on the start screen 「断线重连」 finishes the game
(handled by the lobby and match code). Each screen is handled wherever it shows up, so a
step that does not appear (or was done by hand) is simply skipped.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .. import log
from ..geometry import Outside as G
from .screens import Outside, Screen

if TYPE_CHECKING:
    from .context import GameContext

MAX_STEPS = 20   # actions in a row without reaching 卫戍协议; then the watchdog decides


def step(ctx: GameContext, screen: Screen) -> None:
    """Act on one screen of the way back (``screen.outside`` is set)."""
    kind = screen.outside
    if kind is Outside.SYNC:
        log.info("游戏数据已更新，点「√」同步后返回卫戍协议")
        ctx.tap(*G.SYNC_CONFIRM, wait=5.0)
    elif kind is Outside.SUPPLY:
        log.info("关闭「今日配给」")
        ctx.tap(*G.SUPPLY_CONFIRM, wait=2.0)
    elif kind is Outside.POPUP:
        log.info("关闭签到/公告弹窗")
        ctx.tap(*G.POPUP_CLOSE, wait=2.0)
    elif kind is Outside.MAIN_MENU:
        hit = screen.find("规程", region=G.BANNER)
        log.info("在游戏主界面，点「卫戍协议·规程」返回卫戍协议")
        ctx.tap(*(hit.x, hit.y) if hit else G.BANNER_TAP, wait=5.0)
