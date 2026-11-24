"""Tactic interface: a tactic decides, the prep session carries it out.

A tactic never touches the screen. It receives :class:`PrepActions`, an object that
reads the shop and performs one UI operation per call, and returns when it is done
with the round. Swapping tactics therefore never affects navigation, recognition or
the feature logic, and tactics can be unit-tested with a fake ``PrepActions``.
"""
from __future__ import annotations

from typing import Callable, Protocol, Sequence

from ..game.board import BoardState, Cell, Layout, Unit
from ..vision.hud import PrepState, ShopCard


class PrepActions(Protocol):
    board: BoardState
    layout: Layout
    refusal: str   # why the last buy() was refused: "bench_full", "gold" or ""
    deploy_failure: str   # why the last deploy() failed: "no_room", "drop" (refused) or "missing" (not on the bench)

    def state(self) -> PrepState:
        """Current shop/HUD (re-read after every action)."""

    def upgrade(self) -> bool:
        """Raise the shop level once. True when it worked."""

    def refresh(self) -> bool:
        """Refresh the shop once. True when the cards changed."""

    def buy(self, card: ShopCard) -> Unit | None:
        """Buy a shop card; the operator lands on the bench."""

    def deploy(self, unit: Unit, cells: Sequence[Cell]) -> Cell | None:
        """Drag ``unit`` from the bench to the first *free* cell of ``cells`` and face it right."""

    def deploy_bench(self, choose: Callable[[Unit], Sequence[Cell]]) -> int:
        """Deploy operators already waiting on the bench; ``choose`` orders the cells per unit."""

    def bench_count(self) -> int:
        """Occupied bench (整备区) slots, out of ten."""

    def survey_bench(self) -> list[tuple[int, Unit]]:
        """(slot x, operator with name/tier/labels) for every operator on the bench."""

    def sell_bench(self, slot_x: int, unit: Unit) -> bool:
        """Sell the bench operator in the slot at ``slot_x``."""

    def replace(self, unit: Unit, cell: Cell) -> bool:
        """Drop ``unit`` on an occupied cell and sell the operator it pushes out."""


class Tactic(Protocol):
    name: str

    def on_match_start(self) -> None:
        """A new game begins (reset per-game memory)."""

    def on_prep(self, actions: PrepActions, round_no: int | None) -> None:
        """Spend this preparation phase. Must return; the caller presses 准备就绪."""

    def choose_option(self, title: str, options: Sequence[str]) -> int:
        """道具补给 / 战术决策: index of the option to take."""
