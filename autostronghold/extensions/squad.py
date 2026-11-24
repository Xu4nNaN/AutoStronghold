"""自选编队 policy (extension point).

Squad selection is skipped: after choosing a strategy the program presses 准备就绪
straight away (:class:`NoSquad`). 联合模拟 may need a custom squad later; implement
:class:`SquadPolicy.choose` for that screen and pass the policy to the match runner.
"""
from __future__ import annotations

from typing import Protocol

from ..geometry import Squad


class SquadScreen(Protocol):
    """What a squad policy may use on the 3/3 确定自选编队 screen."""

    def tap(self, x: float, y: float, wait: float = 0.8) -> None: ...


class SquadPolicy(Protocol):
    name: str

    def choose(self, screen: SquadScreen) -> None:
        """Pick operators (if any) and press 准备就绪 exactly once."""


class NoSquad:
    name = "不选择自选编队，直接准备就绪"

    def choose(self, screen: SquadScreen) -> None:
        screen.tap(*Squad.READY, wait=1.5)
