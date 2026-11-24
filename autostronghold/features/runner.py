"""Runs a feature: its stages in order, one game after another, until the goals are met."""
from __future__ import annotations

import gc
from dataclasses import dataclass, field
from typing import Callable

from .. import log
from ..errors import StopRun
from ..extensions.targets import SimulationTarget
from ..extensions.squad import SquadPolicy
from ..game import lobby
from ..game.board import Layout
from ..game.context import GameContext
from ..game.match import MatchOutcome, MatchRunner
from ..game.screens import Kind
from ..tactics.base import Tactic
from ..vision.ocr import OcrEngine
from .plans import Feature, Stage


@dataclass
class RunReport:
    finished: bool = False
    message: str = ""
    games: int = 0
    wins: int = 0
    history: list[tuple[str, str, bool]] = field(default_factory=list)   # (stage, strategy, win)


class FeatureRunner:
    def __init__(self, ctx: GameContext, feature: Feature, tactic: Tactic | Callable[[SimulationTarget], Tactic],
                 layout: Layout,
                 squad: SquadPolicy | None = None, max_games: int = 0, max_losses_in_row: int = 5,
                 start_stage: int = 1, new_ocr: Callable[[], OcrEngine] | None = None):
        self.ctx = ctx
        self.feature = feature
        # one tactic for every stage, or a selector giving each stage (mode / level) its own
        self.tactic_for = tactic if callable(tactic) and not hasattr(tactic, "on_prep") else (lambda _t: tactic)
        self._tactics: dict[SimulationTarget, Tactic] = {}
        self.layout = layout
        self.squad = squad
        self.max_games = max_games
        self.max_losses_in_row = max_losses_in_row
        self.start_stage = max(1, min(start_stage, len(feature.stages)))
        self.report = RunReport()
        self.new_ocr = new_ocr            # builds a fresh OCR engine after each game

    def _runner(self, stage: Stage) -> MatchRunner:
        tactic = self._tactics.get(stage.target)
        if tactic is None:
            tactic = self._tactics[stage.target] = self.tactic_for(stage.target)
            log.info("%s 使用打法：%s", stage.target.label, tactic.name)
        return MatchRunner(self.ctx, stage.goal, tactic, self.layout, self.squad)

    def _record(self, stage: Stage, out: MatchOutcome) -> None:
        self.report.games += 1
        self.report.wins += int(out.win)
        self.report.history.append((stage.target.label, out.strategy, out.win))
        log.info("已进行 %d 局，通关 %d 局", self.report.games, self.report.wins)
        self.ctx.notify("games", (self.report.games, self.report.wins))

    def _release(self) -> None:
        """Between games: drop the tactics and the OCR engine so nothing from one game carries
        into the next; the device connection is kept."""
        self._tactics.clear()
        if self.new_ocr is not None:
            self.ctx.ocr.close()
            self.ctx.ocr = None
            gc.collect()                  # free the old ONNX sessions before the new ones load
            self.ctx.ocr = self.new_ocr()

    def _limit_reached(self) -> bool:
        if self.max_games and self.report.games >= self.max_games:
            self.report.message = f"已达到设定的对局数上限（{self.max_games} 局），程序停止。"
            return True
        return False

    def run(self) -> RunReport:
        first = self.feature.stages[self.start_stage - 1]
        screen = lobby.ensure_lobby(self.ctx, timeout=self.ctx.timeouts.leave, allow_match=True)
        if screen.kind is not Kind.LOBBY:
            log.info("检测到正在进行的对局，先把这一局打完")
            out = self._runner(first).run()
            if out.started and not out.goal_reached:
                self._record(first, out)
                if self._limit_reached():
                    return self.report
                self._release()

        for number, stage in enumerate(self.feature.stages, 1):
            if number < self.start_stage:
                continue
            log.info("===== 阶段 %d/%d：%s · %s =====", number, len(self.feature.stages), stage.target.label,
                     stage.goal.name)
            self.ctx.notify("stage", f"{stage.target.label} · {stage.goal.name}")
            losses = 0
            idle_entries = 0
            while True:
                lobby.enter(self.ctx, stage.target)
                out = self._runner(stage).run()
                if out.goal_reached:
                    if out.decision:
                        self.report.message = out.decision.message
                    break
                if not out.started:
                    idle_entries += 1
                    if idle_entries >= 3:
                        raise StopRun(f"多次尝试进入「{stage.target.label}」都没有开始对局。",
                                      "确认卫戍协议开放中、没有弹窗挡住按钮，然后重新运行。")
                    continue
                idle_entries = 0
                self._record(stage, out)
                losses = 0 if out.win else losses + 1
                if losses >= self.max_losses_in_row:
                    raise StopRun(f"已连续 {losses} 局未通关，为避免无效刷取，程序已停止。",
                                  "可以在 tactics 文件夹中调整打法参数后重新运行。")
                if self._limit_reached():
                    return self.report
                self._release()
        self.report.finished = True
        self.report.message = f"「{self.feature.title}」已完成。{self.report.message}"
        return self.report
