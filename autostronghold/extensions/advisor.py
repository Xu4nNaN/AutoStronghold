"""Hook for an external planner such as StrongholdAssistant (extension point).

StrongholdAssistant (卫戍协议助手, Apache-2.0) knows operator data, alliances and
placement. A future adapter can implement :class:`Advisor` to advise how to spend gold
and where to deploy; the default tactic consults the advisor first and falls back to
its own rules whenever the advisor returns ``None``. Nothing here talks to
StrongholdAssistant yet.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from ..game.board import BoardState, Cell, Unit
from ..vision.hud import PrepState, ShopCard


@dataclass
class FundingAdvice:
    upgrade_shop: bool | None = None          # None = no opinion
    buy: Sequence[int] = ()                   # shop slot indexes to buy, in order
    refreshes: int | None = None              # how many refreshes are worth it this round


class Advisor(Protocol):
    name: str

    def plan_funds(self, state: PrepState, board: BoardState) -> FundingAdvice | None: ...

    def choose_cell(self, unit: Unit, free: Sequence[Cell], board: BoardState) -> Cell | None: ...

    def card_value(self, card: ShopCard, board: BoardState) -> float | None: ...


class NullAdvisor:
    """No external advice: the tactic decides on its own."""

    name = "无"

    def plan_funds(self, state, board):
        return None

    def choose_cell(self, unit, free, board):
        return None

    def card_value(self, card, board):
        return None
