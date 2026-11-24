"""极速模拟 strategy: 9 rounds, the leader on round 9, no hidden round.

Everything is decided by the round-9 leader fight (all simulator losses were overtime
drain there; normal rounds leak almost nothing), and a faster leader kill is also the
shorter game. So: cheap levels early (FAST prices 1/1/5/8/10: level 3 at round 2, 6 at
round 6), a 精准 / 奥术 core, few refreshes before the end, and in round 9 the bench is
sold and every coin is spent. Parameters: ``resources/tactics/sp3_fast.json``.
"""
from __future__ import annotations

from .catalog import Catalog
from .engine import EngineTactic, Params

PARAMS_FILE = "sp3_fast.json"
MODE = "极速模拟"


class FastTactic(EngineTactic):
    name = "SP3·极速模拟"

    def __init__(self, params: Params | None = None, catalog: Catalog | None = None):
        catalog = catalog or Catalog.load()
        mode = catalog.mode(MODE)
        super().__init__(params or Params.load(PARAMS_FILE, {"inactive_bonds": mode.get("inactive_bonds", [])}), catalog)
        self.boss_round = int(mode.get("boss_round") or 9)
        self.hidden_round = None
