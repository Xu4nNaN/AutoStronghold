"""Where a game is played: simulation mode and 规程等级 (extension point).

极速模拟 and 独立模拟 at 规程等级 1-4 are supported. ``game.lobby.select_level`` can select
any unlocked level (it drags the difficulty list), but levels 5-20 play on maps whose cells
are not calibrated yet (only 战场#01 is in ``layout/board.json``), and 联合模拟 is not
implemented. They are declared so menus, feature plans and logs can already name them;
selecting one raises a clear "not supported yet" message instead of misbehaving. To add a
level: calibrate its map and add it to ``SUPPORTED_LEVELS``.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Mode(str, Enum):
    SPEED = "极速模拟"
    INDEPENDENT = "独立模拟"
    JOINT = "联合模拟"


MIN_LEVEL, MAX_LEVEL = 1, 20
SUPPORTED_LEVELS = frozenset({1, 2, 3, 4})   # 战场#01, the calibrated map


@dataclass(frozen=True)
class SimulationTarget:
    mode: Mode
    level: int | None = None   # 规程等级, only for 独立模拟 / 联合模拟

    def __post_init__(self) -> None:
        if self.mode is Mode.SPEED and self.level is not None:
            raise ValueError("极速模拟没有规程等级")
        if self.level is not None and not MIN_LEVEL <= self.level <= MAX_LEVEL:
            raise ValueError(f"规程等级必须在 {MIN_LEVEL}~{MAX_LEVEL} 之间")

    @property
    def label(self) -> str:
        return self.mode.value + (f"·规程等级{self.level}" if self.level else "")

    def unsupported_reason(self) -> str | None:
        if self.mode is Mode.JOINT:
            return "联合模拟尚未实现（需要组队与自选编队，已预留扩展接口）。"
        if self.level is not None and self.level not in SUPPORTED_LEVELS:
            return f"规程等级{self.level}尚未实现（目前支持规程等级 1～4，已预留扩展接口）。"
        return None


SPEED = SimulationTarget(Mode.SPEED)


def independent(level: int) -> SimulationTarget:
    return SimulationTarget(Mode.INDEPENDENT, level)
