"""Moving around the 卫戍协议 start screen and the difficulty selection."""
from __future__ import annotations

import re

from .. import log
from ..errors import StopRun
from ..extensions.targets import Mode, SimulationTarget
from ..geometry import Difficulty, Lobby, Result
from .context import GameContext
from .screens import Kind, Screen

IN_MATCH = {Kind.MATCH_INFO, Kind.STRATEGY, Kind.SQUAD, Kind.LOADING, Kind.PREP, Kind.CONFIRM_READY,
            Kind.FACING, Kind.EVENT, Kind.BATTLE}


def unfinished_game() -> StopRun:
    """断线重连 for a game the data update did not end: it is the player's to finish or give up."""
    return StopRun("卫戍协议开始界面显示「断线重连」：有一局尚未结束的对局。",
                   "请在游戏中打完或放弃（「放弃模拟」）当前对局，回到卫戍协议开始界面后重新运行本程序。")


def switch_to_personal(ctx: GameContext, screen: Screen) -> None:
    """The start screen is on 联合模拟 (同盟模拟 / 搜寻队友 visible)."""
    log.info("当前为「联合模拟」，切换至「个人模拟」")
    hit = screen.find("个人模拟")
    ctx.tap(*(hit.x, hit.y) if hit else Lobby.PERSONAL_TAB, wait=2.0)


MODE_BUTTONS = (900, 900, 1920, 1080)   # 极速模拟 / 独立模拟 buttons at the bottom right
ENTER_TIMEOUT = 10.0                     # seconds for a mode button tap to leave the start screen
ENTER_ATTEMPTS = 3


def lobby_ready(screen: Screen) -> bool:
    """The personal start screen is fully shown: both mode buttons are readable."""
    if screen.kind is not Kind.LOBBY:
        return False
    if screen.reconnect:
        return True        # 断线重连 replaces the mode buttons
    return screen.has("极速模拟", region=MODE_BUTTONS) and screen.has("独立模拟", region=MODE_BUTTONS)


def ensure_lobby(ctx: GameContext, timeout: float = 60.0, allow_match: bool = False) -> Screen:
    """Return once the personal-simulation start screen is showing and settled.

    Screens that lead back to it (joint tab, difficulty list, result) are handled. After
    switching tabs the page animates in, so the screen is only accepted once two looks in
    a row show both mode buttons; a tap during the animation would be ignored by the game.
    With ``allow_match`` an in-progress game is returned as is so the caller can finish it.
    """
    deadline = ctx.clock() + timeout
    ready_once = False
    while True:
        screen = ctx.look()
        if allow_match and screen.kind in IN_MATCH:
            return screen
        if lobby_ready(screen):
            if ready_once or screen.reconnect:
                if ctx.on_lobby is not None and ctx.on_lobby(screen):
                    ctx.on_lobby = None
                return screen
            ready_once = True
            ctx.sleep(0.6)
            continue
        ready_once = False
        ctx.check_watchdogs(screen)
        if ctx.clock() > deadline:
            log.snapshot(screen.image, "no_lobby")
            raise StopRun(f"{int(timeout)} 秒内没有检测到卫戍协议开始界面（当前画面识别为「{screen.kind.value}」）。",
                          "请进入「卫戍协议」开始界面（右下角显示「个人模拟」「联合模拟」），然后重新运行。")
        if screen.kind is Kind.LOBBY_JOINT:
            switch_to_personal(ctx, screen)
        elif screen.kind is Kind.DIFFICULTY:
            ctx.tap(*Lobby.BACK, wait=2.0)
        elif screen.kind is Kind.RESULT:
            hit = screen.find("返回主页")
            ctx.tap(*(hit.x, hit.y) if hit else Result.HOME, wait=3.0)
        ctx.sleep(ctx.timeouts.poll)


_LEVEL = re.compile(r"规程等级(\d+)")


def _level_in(text: str) -> int | None:
    m = _LEVEL.search(text)
    return int(m.group(1)) if m else None


def current_level(screen: Screen) -> int | None:
    """The selected 规程等级: the bottom-left label, else the list entry at the selection mark."""
    label = screen.find("规程等级", region=Difficulty.CURRENT_LABEL)
    if label and _level_in(label.compact):
        return _level_in(label.compact)
    centred = [b for b in screen.boxes if _level_in(b.compact) and abs(b.y - Difficulty.SWIPE_CENTRE_Y) < 60
               and Difficulty.LIST[0] <= b.x <= Difficulty.LIST[2]]
    return _level_in(centred[0].compact) if centred else None


def _swipe_levels(ctx: GameContext, steps: int) -> None:
    """Drag the level list by ``steps`` levels (positive: towards higher levels)."""
    steps = max(-Difficulty.MAX_LEVELS_PER_SWIPE, min(Difficulty.MAX_LEVELS_PER_SWIPE, steps))
    half = abs(steps) * Difficulty.LEVEL_STEP / 2
    y1, y2 = Difficulty.SWIPE_CENTRE_Y - half, Difficulty.SWIPE_CENTRE_Y + half
    if steps < 0:
        y1, y2 = y2, y1
    ctx.device.swipe(Difficulty.SWIPE_X, y1, Difficulty.SWIPE_X, y2, duration=0.6, hold=0.4, wait=1.2)


def select_level(ctx: GameContext, screen: Screen, level: int) -> None:
    """On 请选择模拟难度: make ``level`` the selected 规程等级. A visible entry is tapped;
    otherwise the list is dragged by the number of levels missing and read again."""
    stuck = 0
    for _ in range(6):
        current = current_level(screen)
        if current == level:
            log.info("当前难度：规程等级%d", level)
            return
        entry = next((b for b in screen.boxes if _level_in(b.compact) == level
                      and Difficulty.LIST[0] <= b.x <= Difficulty.LIST[2]
                      and Difficulty.LIST[1] <= b.y <= Difficulty.LIST[3]), None)
        if entry is not None:
            log.info("当前难度为%s，点击「规程等级%d」", f"规程等级{current}" if current else "未知", level)
            ctx.tap_box(entry, wait=1.5)
        else:
            steps = level - current if current else level - 1
            log.info("当前难度为%s，滑动难度列表 %+d 级", f"规程等级{current}" if current else "未知", steps)
            _swipe_levels(ctx, steps)
        screen = ctx.look()
        after = current_level(screen)
        stuck = stuck + 1 if after is not None and after == current else 0
        if stuck >= 2 and current is not None and level > current:
            # tapped / dragged twice without moving: the list stops at the highest unlocked level
            raise StopRun(f"规程等级{level}尚未解锁（当前最高可选规程等级{current}）。",
                          f"先在游戏中解锁规程等级{level}，或改用已解锁的等级。")
    raise StopRun(f"无法切换到规程等级{level}。", "请手动选择该难度后重新运行。")


def _left_lobby(ctx: GameContext, timeout: float) -> Screen | None:
    """Look until the game leaves the start screen; None if it is still there (or on the joint tab)."""
    deadline = ctx.clock() + timeout
    while True:
        screen = ctx.look()
        if screen.kind not in (Kind.LOBBY, Kind.LOBBY_JOINT, Kind.UNKNOWN):
            return screen          # difficulty list, match info, loading, the resumed game ...
        if screen.kind is Kind.LOBBY_JOINT or ctx.clock() > deadline:
            return None
        ctx.sleep(ctx.timeouts.poll)


def _open_mode(ctx: GameContext, target: SimulationTarget) -> Screen:
    """Tap the mode button (or 断线重连) until the game leaves the start screen; returns the next screen."""
    default = Lobby.SPEED_BUTTON if target.mode is Mode.SPEED else Lobby.INDEPENDENT_BUTTON
    for attempt in range(1, ENTER_ATTEMPTS + 1):
        screen = ensure_lobby(ctx)
        if screen.reconnect:
            if not screen.interrupted:
                raise unfinished_game()
            hit = screen.find("断线重连")
            log.info("对局被数据更新中断，点「断线重连」完成结算")
            ctx.tap(*(hit.x, hit.y) if hit else Lobby.INDEPENDENT_BUTTON, wait=5.0)
            # the settlement / game may take a while to come back
            screen = _left_lobby(ctx, 3 * ENTER_TIMEOUT)
            if screen is not None:
                return screen
            continue
        hit = screen.find(target.mode.value, region=MODE_BUTTONS)
        log.info("进入「%s」", target.label)
        ctx.tap(*(hit.x, hit.y) if hit else default, wait=2.0)
        screen = _left_lobby(ctx, ENTER_TIMEOUT)   # None: tap not taken (or the tab changed), start over
        if screen is not None:
            return screen
        log.info("点击「%s」后仍停在开始界面，重试（第 %d/%d 次）", target.mode.value, attempt, ENTER_ATTEMPTS)
    log.snapshot(ctx.device.screenshot(), "enter_failed")
    raise StopRun(f"多次点击「{target.mode.value}」后游戏都没有进入模拟。",
                  "确认卫戍协议开放中、没有弹窗挡住按钮，然后重新运行。")


def enter(ctx: GameContext, target: SimulationTarget) -> None:
    """From the start screen, open the target simulation up to its first in-game screen."""
    reason = target.unsupported_reason()
    if reason:
        raise StopRun(reason)
    screen = _open_mode(ctx, target)
    if screen.kind in IN_MATCH or screen.kind is Kind.RESULT:
        return             # an unfinished game was resumed; the match runner plays it
    if target.mode is Mode.INDEPENDENT and screen.kind is not Kind.MATCH_INFO:
        if screen.kind is not Kind.DIFFICULTY:
            screen = ctx.wait_for({Kind.DIFFICULTY}, 30, "请选择模拟难度")
        select_level(ctx, screen, target.level or 1)
        start = ctx.look().find("开始模拟")
        ctx.tap(*(start.x, start.y) if start else Difficulty.START, wait=3.0)
