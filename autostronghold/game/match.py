"""One game: from the first in-game screen to the result screen."""
from __future__ import annotations

from dataclasses import dataclass

from .. import log
from ..errors import StopRun
from ..extensions.squad import NoSquad, SquadPolicy
from ..features.goals import BadgeGoal, Decision
from ..geometry import Difficulty, Event, Lobby, Prep, Result, Squad, StrategyGrid
from ..tactics.base import Tactic
from ..vision import events
from .board import BoardState, Layout
from .context import GameContext
from .lobby import unfinished_game
from .prep import PrepSession, confirm_ready_dialog
from .screens import Kind, Screen
from .strategy import StrategySelector

# Buttons that only move a dialog/animation forward; tapped on unknown in-event screens.
# Matched as whole texts so titles such as 「模拟完成」 are not mistaken for buttons.
CONTINUE_WORDS = ("继续", "下一步", "领取", "完成", "确定")
MAX_PREP_ERRORS = 10


@dataclass
class MatchOutcome:
    goal_reached: bool = False        # nothing left to farm: we left the simulation
    started: bool = True              # False: never got into a game (caller re-enters)
    win: bool = False
    strategy: str = ""
    decision: Decision | None = None
    rounds: int = 0


class MatchRunner:
    def __init__(self, ctx: GameContext, goal: BadgeGoal, tactic: Tactic, layout: Layout,
                 squad: SquadPolicy | None = None):
        self.ctx = ctx
        self.goal = goal
        self.tactic = tactic
        self.layout = layout
        self.squad = squad or NoSquad()

    def run(self, lobby_grace: float = 5.0) -> MatchOutcome:
        ctx = self.ctx
        board = BoardState()
        self.tactic.on_match_start()
        outcome = MatchOutcome(started=False)
        picked_at: float | None = None
        prepared_round: int | None = None
        ready_at = 0.0
        prep_errors = 0
        lobby_since: float | None = None
        while True:
            s = ctx.look()
            ctx.check_watchdogs(s)
            kind = s.kind
            if kind not in (Kind.LOBBY, Kind.UNKNOWN):
                lobby_since = None

            if kind is Kind.RESULT:
                outcome.win = s.win
                log.info("本局%s，策略：%s，通过回合：%s", "通关" if s.win else "未通关", outcome.strategy or "未知",
                         outcome.rounds or "?")
                log.snapshot(s.image, "result", limit=50)
                hit = s.find("返回主页")
                ctx.tap(*(hit.x, hit.y) if hit else Result.HOME, wait=4.0)
                ctx.progress()
                outcome.started = True
                return outcome

            if kind is Kind.LOBBY and s.reconnect:
                if not s.interrupted:
                    raise unfinished_game()
                # back on the start screen after the daily data update ended the game
                hit = s.find("断线重连")
                log.info("回到了开始界面，点「断线重连」继续本局")
                ctx.tap(*(hit.x, hit.y) if hit else Lobby.INDEPENDENT_BUTTON, wait=5.0)
                continue
            if kind is Kind.LOBBY:
                if outcome.started:
                    log.warn("对局中回到了开始界面（可能被中断），视为本局结束")
                    return outcome
                lobby_since = lobby_since or ctx.clock()
                if ctx.clock() - lobby_since > lobby_grace:
                    return outcome   # never entered; caller enters again
            elif kind is Kind.LOBBY_JOINT:
                # Back on the start screen (joint tab): the game is over or never began;
                # the feature runner switches tabs and enters again.
                return outcome
            elif kind is Kind.DIFFICULTY:
                hit = s.find("开始模拟")
                ctx.tap(*(hit.x, hit.y) if hit else Difficulty.START, wait=3.0)
            elif kind is Kind.MATCH_INFO:
                hit = s.find("准备就绪", "确认", region=(1300, 850, 1920, 1080))
                ctx.tap(*(hit.x, hit.y) if hit else Squad.READY, wait=2.0)
            elif kind is Kind.STRATEGY:
                outcome.started = True
                if picked_at is None:
                    selection = StrategySelector(ctx, self.goal).run()
                    outcome.decision = selection.decision
                    if selection.decision.done:
                        log.info(selection.decision.message)
                        leave_simulation(ctx)
                        outcome.goal_reached = True
                        return outcome
                    outcome.strategy = selection.strategy
                    picked_at = ctx.clock()
                elif ctx.clock() - picked_at > 12:
                    hit = s.find("确认选择")   # still here: the confirm tap may have been missed
                    if hit:
                        ctx.tap_box(hit, wait=2.0)
                    picked_at = ctx.clock()
            elif kind is Kind.SQUAD:
                outcome.started = True
                if not s.ready_pressed:
                    log.info("跳过自选编队，直接准备就绪")
                    self.squad.choose(ctx)
            elif kind is Kind.PREP:
                outcome.started = True
                if s.collapsed:
                    log.info("卡牌区被收起了，点「展开」还原")
                    hit = s.find("展开", region=Prep.EXPAND_BOX)
                    ctx.tap(*(hit.x, hit.y) if hit else (1777, 1010), wait=1.2)
                    continue
                rnd = ctx.ocr.read_number(s.image, Prep.ROUND, 1, 30)
                if rnd is None or rnd != prepared_round:
                    if prepared_round is None and rnd and rnd > 1 and not board.occupied:
                        board.resumed = True   # the program started in the middle of this game
                    if rnd == 1 and board.shop_level is None:
                        board.shop_level = 1   # every game starts at level 1 (a lone "I" is hard to read)
                    session = PrepSession(ctx, self.layout, board)
                    log.info("—— 第 %s 回合休整期 ——", rnd if rnd is not None else "?")
                    ctx.notify("round", rnd)
                    try:
                        self.tactic.on_prep(session, rnd)
                    except StopRun:
                        raise
                    except Exception as exc:  # keep playing: an odd screen must not end the run
                        prep_errors += 1
                        log.warn("休整期处理出错（第 %d 次，已跳过）：%r", prep_errors, exc)
                        log.snapshot(ctx.device.screenshot(), "prep_error")
                        if prep_errors >= MAX_PREP_ERRORS:
                            raise StopRun("休整期连续出错次数过多，程序已停止。截图已保存到 logs 文件夹。",
                                          "确认游戏画面为 1920x1080、默认主题，然后重新运行。") from exc
                    session.press_ready()
                    prepared_round, ready_at = rnd, ctx.clock()
                    outcome.rounds = max(outcome.rounds, rnd or 0)
                    ctx.progress()
                elif ctx.clock() - ready_at > 10:
                    log.info("休整期还没结束，再按一次「准备就绪」")
                    PrepSession(ctx, self.layout, board).press_ready()
                    ready_at = ctx.clock()
            elif kind is Kind.CONFIRM_READY:
                confirm_ready_dialog(ctx, s)
            elif kind is Kind.EVENT:
                outcome.started = True
                self._event(s)
            elif kind is Kind.FACING:
                # A deployment waits for a direction (our facing drag was not taken):
                # cancel it; the operator returns to the bench and is redeployed later.
                hit = s.find("点击取消")
                log.info("停在选择朝向界面，取消这次部署")
                ctx.tap(*(hit.x, hit.y) if hit else (960, 540), wait=1.0)
            elif kind in (Kind.LOADING, Kind.BATTLE):
                outcome.started = True
                ctx.sleep(2.0)
                continue
            elif kind is Kind.UNKNOWN and s.in_garrison:
                hit = next((b for b in s.boxes if b.compact in CONTINUE_WORDS
                            or b.compact.startswith(("点击任意", "点击屏幕"))), None)
                if hit:
                    log.info("点击「%s」继续", hit.compact)
                    ctx.tap_box(hit, wait=1.5)
            ctx.sleep(ctx.timeouts.poll)

    def _event(self, s: Screen) -> None:
        hit = s.find("确认选择", region=(0, 600, 1920, 900))
        if hit is None:
            centres = events.option_centres(s.image)
            options = [str(i) for i in range(len(centres))] or ["0", "1", "2"]
            index = self.tactic.choose_option(s.event_title, options)
            point = centres[index] if 0 <= index < len(centres) else Event.MIDDLE_OPTION
            log.info("%s：选择第 %d 个选项", s.event_title, index + 1)
            self.ctx.tap(*point, wait=1.2)
            hit = self.ctx.look().find("确认选择", region=(0, 600, 1920, 900))
        log.info("%s：确认选择", s.event_title)
        self.ctx.tap(*(hit.x, hit.y) if hit else Event.CONFIRM_FALLBACK, wait=2.0)
        self.ctx.progress()


def _exit_button(s: Screen):
    """The confirming button of the "leave the simulation?" dialog, if one is showing."""
    for b in s.boxes:
        text = b.compact
        if b.y > 540 and text in ("确认", "确定", "是", "放弃模拟", "退出模拟", "确认退出", "确认放弃"):
            return b
    return None


def leave_simulation(ctx: GameContext) -> None:
    """Goal reached while choosing a strategy: abandon this simulation, back to the start screen."""
    log.info("目标已完成，退出本次模拟")
    for _ in range(3):
        ctx.tap(*StrategyGrid.EXIT, wait=1.5)
        for _ in range(8):
            s = ctx.look()
            if s.kind is Kind.LOBBY:
                return
            if s.kind is Kind.RESULT:
                hit = s.find("返回主页")
                ctx.tap(*(hit.x, hit.y) if hit else Result.HOME, wait=3.0)
                continue
            button = _exit_button(s)
            if button is not None:
                ctx.tap_box(button, wait=2.0)
            elif s.kind is Kind.STRATEGY:
                break   # no dialog: the exit tap was not taken, tap it again
            else:
                ctx.sleep(1.0)
    raise StopRun("目标已经完成，但没能自动退出当前模拟。",
                  "请手动点击左上角退出本局；本次刷取的进度不受影响。")
