"""独立模拟·规程等级1 strategy: 14 rounds, the leader on round 14, no hidden round.

At 规程等级1 (FUNNY difficulty, enemies ×0.70 attack / ×0.75 HP, the lowest leader HP) the
simulator won every derivation game, so the remaining goal is a shorter game: the
in-game actions (buy, deploy, refresh, sell, replace — 1.6 to 8 s each) are the part a
strategy controls, the normal waves last as long as they last. The rules therefore buy
less after the field is good enough (higher ``buy_min`` / ``replace_margin``), refresh
little, and keep the leader-round spending that shortens the leader fight. The shop levels
follow 规程 prices (5/8/11/12/13). Parameters: ``resources/tactics/sp3_independent_l1.json``.
"""
from __future__ import annotations

from .catalog import Catalog
from .engine import EngineTactic, Params

PARAMS_FILE = "sp3_independent_l1.json"
MODE = "规程等级1"


class IndependentL1Tactic(EngineTactic):
    name = "SP3·独立模拟·规程等级1"

    def __init__(self, params: Params | None = None, catalog: Catalog | None = None):
        catalog = catalog or Catalog.load()
        mode = catalog.mode(MODE)
        super().__init__(params or Params.load(PARAMS_FILE, {"inactive_bonds": mode.get("inactive_bonds", [])}), catalog)
        self.boss_round = int(mode.get("boss_round") or 14)
        self.hidden_round = None
