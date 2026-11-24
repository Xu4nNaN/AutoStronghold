"""独立模拟·规程等级2~20 strategy: clear first; enter and clear the hidden round when it opens.

14 rounds, the leader on round 14; 规程等级5~20 add round 15 (隐秘核心), which opens after a
round-14 win when the activated bond layers summed at the end of the round-14 prep exceed
350 and at least 2 target HP are left (simulator config hiddenCore; PRTS only says
「满足特定条件」). The hidden round is never chosen: it follows automatically, so the
strategy plays for the round-14 win first and, from 规程等级5, values 助力 (+2 / +4 layers
on every active bond at each prep end) for the layer count.

Levels are played in groups with their own parameters (``resources/tactics/
sp3_independent_clear.json``: ``base`` plus one block per group in ``GROUPS``):
2~4 FUNNY (map 战场#01 only, no hidden round), 5~8 NORMAL, 9~14 HARD, 15~20 ABYSS
(leader HP 3.3× / 8× / 14× the 2~4 value; 9~20 also change the special rounds to 3/9/11).
"""
from __future__ import annotations

import json
from pathlib import Path

from ...paths import user_file
from .catalog import Catalog
from .engine import EngineTactic, Params, check_version

PARAMS_FILE = "sp3_independent_clear.json"
GROUPS: dict[str, range] = {"2-4": range(2, 5), "5-8": range(5, 9), "9-14": range(9, 15), "15-20": range(15, 21)}


def group_of(level: int) -> str:
    for name, levels in GROUPS.items():
        if level in levels:
            return name
    raise ValueError(f"规程等级{level} 不在 2~20 之间")


def load_params(level: int, inactive_bonds: list[str]) -> Params:
    data = json.loads(Path(user_file(f"tactics/{PARAMS_FILE}")).read_text(encoding="utf-8"))
    check_version(PARAMS_FILE, data)
    merged = {**data.get("base", {}), **data.get("groups", {}).get(group_of(level), {}),
              **data.get("levels", {}).get(str(level), {}), "inactive_bonds": inactive_bonds}
    p = Params()
    for key, value in merged.items():
        if key.startswith("_") or not hasattr(p, key):
            continue
        if key in ("level_plan", "min_field", "refresh_budget"):
            value = {int(k): int(v) for k, v in value.items()}
        setattr(p, key, value)
    return p


class IndependentClearTactic(EngineTactic):
    name = "SP3·独立模拟·通关优先"

    def __init__(self, level: int, params: Params | None = None, catalog: Catalog | None = None):
        catalog = catalog or Catalog.load()
        mode = catalog.mode(f"规程等级{level}")
        super().__init__(params or load_params(level, mode.get("inactive_bonds", [])), catalog)
        self.level_no = level
        self.group = group_of(level)
        self.name = f"SP3·独立模拟·通关优先（规程等级{level}，{self.group} 组）"
        self.boss_round = int(mode.get("boss_round") or 14)
        self.hidden_round = mode.get("hidden_round")

