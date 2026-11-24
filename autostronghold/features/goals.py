"""What each feature is trying to achieve on the strategy grid (pure logic, no I/O)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..vision.grid import Badge

# Clears needed for each badge, as shown on the strategy panel ("已通过模拟N次").
CLEARS_FOR = {Badge.GOLD: 3, Badge.COLOR: 6}


@dataclass(frozen=True)
class StrategyEntry:
    """One strategy on the grid, in list order."""

    index: int
    badge: Badge
    label: str = ""          # e.g. "第 3 个策略"


@dataclass(frozen=True)
class Decision:
    done: bool
    pick: StrategyEntry | None = None
    message: str = ""
    badged: int = 0
    total: int = 0


@dataclass(frozen=True)
class BadgeGoal:
    """A strategy counts as finished when its badge is one of ``accepted``.

    With ``count_target`` the goal is reached as soon as that many strategies are
    finished (蚀刻章: 20); without it, every strategy must be finished.
    """

    accepted: frozenset[Badge]
    count_target: int | None = None
    name: str = ""

    def satisfied_by(self, badge: Badge) -> bool:
        return badge in self.accepted

    @property
    def clears_needed(self) -> int:
        """Clears that guarantee an accepted badge (used to double-check the grid)."""
        return min(CLEARS_FOR[b] for b in self.accepted)

    @property
    def wanted_label(self) -> str:
        return "彩标" if self.accepted == {Badge.COLOR} else "角标（金标或彩标）"

    def settled(self, entries: Sequence[StrategyEntry]) -> bool:
        """The cards read so far (in list order) already decide: 蚀刻章 has its 20 badges;
        an all-badges goal has found a strategy that still needs one. The scan stops here."""
        if self.count_target is not None:
            return sum(1 for e in entries if self.satisfied_by(e.badge)) >= self.count_target
        return any(not self.satisfied_by(e.badge) for e in entries)

    def decide(self, entries: Sequence[StrategyEntry], complete: bool) -> Decision:
        """``complete`` is False when the scan could not reach the end of the list."""
        badged = sum(1 for e in entries if self.satisfied_by(e.badge))
        first_open = next((e for e in entries if not self.satisfied_by(e.badge)), None)
        total = len(entries)
        if self.count_target is not None:
            if badged >= self.count_target:
                return Decision(True, None, f"已获得{self.wanted_label}的策略数：{badged}，达到 {self.count_target}，目标完成。",
                                badged, total)
            if first_open is None and complete:
                return Decision(True, None,
                                f"所有 {total} 个策略都已获得{self.wanted_label}，但总数 {badged} 不足 {self.count_target}，"
                                "已无可继续刷取的策略。", badged, total)
        elif first_open is None and complete:
            return Decision(True, None, f"全部 {total} 个策略都已获得{self.wanted_label}。", badged, total)
        if first_open is None:
            return Decision(False, None, "", badged, total)   # keep scanning
        return Decision(False, first_open, f"选择第一个没有{self.wanted_label}的策略：{first_open.label}", badged, total)
