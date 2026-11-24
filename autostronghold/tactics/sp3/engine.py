"""Shared machinery of the SP3 strategies: board power, buying, placing, selling, levelling.

This module holds no strategy of its own. Every number that decides *what* to do (level
plan, weights, budgets, thresholds) lives in the strategy's own parameter file
(``resources/tactics/sp3_*.json``) and every mode-specific rule in the strategy's own
module (``fast.py``, ``independent_l1.py``, ``independent_clear.py``). A strategy is an
:class:`EngineTactic` subclass that supplies its :class:`Params` and may override the hooks
``level_wanted``, ``refresh_budget`` and ``final_round``.

The rules are the ones validated on the Stronghold-Protocol simulator
(``private/sim/strategies/engine.mjs``; evidence in ``docs/SP3-无模型策略-证据与评测.md``):

* power(field) = Σ tier power × (elite multiplier) + Σ bond value (per threshold reached,
  a small prospect below the first one) + one medic + melee blockers up to a minimum;
* a card is worth power(field with it) − power(field), or the elite share for a copy of an
  owned operator; it is bought when it adds at least ``buy_min`` (``replace_margin`` when it
  has to push the weakest field operator out);
* melee operators take the enemy-route cells first, ranged ones the wooden platforms; all face right;
* the shop is levelled to the plan before buying, the field is first filled to ``min_field``;
* refreshes only once the planned level is reached, within the round's budget; in the
  final (leader) round the bench is sold and every coin goes to buying and refreshing.
Ties: higher value per cost first, then the leftmost card.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from ... import log
from ...game.board import BoardState, Cell, Layout, Unit
from ...paths import user_file
from ...vision.bench import SLOT_X
from ...vision.hud import ShopCard
from ..base import PrepActions
from .catalog import DATA_VERSION, Catalog, CatalogError, Identity

BENCH_FREE_PREP = 1    # bench slots kept empty while buying
BENCH_FREE_READY = 2   # … and before 准备就绪 (Task-3: 至少留 1 个，准备就绪前留 2 个)


@dataclass(frozen=True)
class Decision:
    """One executed action, with the entity it targeted (SP3 data id, not only a slot number)."""

    round: int
    action: str                     # buy | deploy | replace | sell | refresh | upgrade | option
    operator: str = ""              # name read on the card / bench
    chess_id: str = ""              # SP3 data id ("" when the name was not identified)
    confidence: float = 0.0         # identification confidence (catalog.Identity)
    slot: int | None = None         # shop slot index (buy) or option index (option)
    cell: str = ""                  # region cell (deploy / replace)
    value: float | None = None      # the score that chose it
    reason: str = ""                # field | merge | replace | fill | final | budget …


def by_round(table: dict[int, object], rnd: int, default=None):
    """The value of the latest key <= rnd."""
    value = default
    for r in sorted(table):
        if r <= rnd:
            value = table[r]
    return value


@dataclass
class Params:
    level_plan: dict[int, int] = field(default_factory=dict)
    min_field: dict[int, int] = field(default_factory=dict)
    tier_power: list[float] = field(default_factory=lambda: [0, 10, 14, 19, 25, 32, 40])
    elite_mul: float = 2.2
    bond_weights: dict[str, float] = field(default_factory=dict)
    season_weight: float = 10
    other_weight: float = 4
    bond_prospect: float = 0.25
    medic_weight: float = 0
    medic_max: int = 1
    melee_min: int = 3
    melee_weight: float = 10
    merge_share: list[float] = field(default_factory=lambda: [0, 0.35, 0.8])
    buy_min: float = 4
    merge_min: float = 2
    replace_margin: float = 8
    bench_keep: int = 7
    refresh_budget: dict[int, int] = field(default_factory=dict)
    final_sell_bench: bool = True
    option_index: int = 1
    inactive_bonds: list[str] = field(default_factory=list)
    data_version: str = DATA_VERSION

    @classmethod
    def load(cls, name: str, overrides: dict | None = None) -> "Params":
        data = json.loads(Path(user_file(f"tactics/{name}")).read_text(encoding="utf-8"))
        check_version(name, data)
        data.update(overrides or {})
        p = cls()
        for key, value in data.items():
            if key.startswith("_") or not hasattr(p, key):
                continue
            if key in ("level_plan", "min_field", "refresh_budget"):
                value = {int(k): int(v) for k, v in value.items()}
            setattr(p, key, value)
        return p


def check_version(name: str, data: dict) -> None:
    """Parameters derived for one season are refused for another (a new season needs new evidence)."""
    version = data.get("data_version")
    if version != DATA_VERSION:
        raise CatalogError(f"tactics/{name} 适用于 {version or '未注明的版本'}，当前干员表是 {DATA_VERSION}")


class EngineTactic:
    """Base of the SP3 strategies; see the module docstring."""

    name = "SP3"
    boss_round = 14
    hidden_round: int | None = None

    def __init__(self, params: Params, catalog: Catalog | None = None):
        self.p = params
        self.catalog = catalog or Catalog.load()
        self.level = 1
        self.options_taken = 0
        self.round = 0
        self.no_room = False                    # a deployment failed this round: buy no more for the field
        self.decisions: list[Decision] = []     # this match, in order (tests, logs, evaluation)

    def record(self, action: str, unit: Unit | ShopCard | None = None, **kw) -> None:
        ident = self.who(unit) if unit is not None else None
        self.decisions.append(Decision(self.round, action, unit.name if unit is not None else "",
                                       ident.chess_id if ident else "", ident.confidence if ident else 0.0, **kw))

    def action_counts(self, rnd: int | None = None) -> dict[str, int]:
        counts: dict[str, int] = {}
        for d in self.decisions:
            if rnd is None or d.round == rnd:
                counts[d.action] = counts.get(d.action, 0) + 1
        return counts

    # --- hooks ------------------------------------------------------------------------
    def level_wanted(self, rnd: int) -> int:
        return by_round(self.p.level_plan, rnd, 1)

    def refresh_budget(self, rnd: int, final: bool) -> int:
        return 99 if final else by_round(self.p.refresh_budget, rnd, 0)

    def final_round(self, rnd: int) -> bool:
        return rnd == self.boss_round or (self.hidden_round is not None and rnd == self.hidden_round)

    # --- Tactic interface ----------------------------------------------------------------
    def on_match_start(self) -> None:
        if self.decisions:
            log.info("上一局动作统计：%s", self.action_counts())
        self.level = 1
        self.options_taken = 0
        self.round = 0
        self.decisions = []

    def choose_option(self, title: str, options: Sequence[str]) -> int:
        self.options_taken += 1
        index = max(0, min(len(options) - 1, self.p.option_index))
        self.record("option", slot=index, reason=title)
        return index

    def on_prep(self, act: PrepActions, round_no: int | None) -> None:
        st = act.state()
        rnd = round_no or st.round or 0
        self.round = rnd
        try:
            self._prep(act, rnd)
        finally:
            counts = self.action_counts(rnd)
            if counts:
                log.info("第 %d 回合动作：%s", rnd, "、".join(f"{k} {v}" for k, v in counts.items()))

    def _prep(self, act: PrepActions, rnd: int) -> None:
        final = self.final_round(rnd)
        self.no_room = False
        self.place_bench(act)
        self.trim_bench(act)
        wanted = min(act.layout.max_operators, by_round(self.p.min_field, rnd, 0))
        for _ in range(8):
            if self.no_room or self.field_count(act) >= wanted or not self.buy_one(act, fill_only=True):
                break
        self.level_up(act, rnd)
        if final and self.p.final_sell_bench:
            self.sell_bench_for_final(act)
        budget, refreshes = self.refresh_budget(rnd, final), 0
        for _ in range(60):   # hard bound: each pass buys, refreshes or stops
            if self.buy_one(act):
                continue
            st = act.state()
            if not final and not st.maxed and self.read_level(act) < self.level_wanted(rnd):
                break
            cost = st.refresh_cost if st.refresh_cost is not None else 1
            if refreshes >= budget or (st.gold is not None and st.gold < cost) or st.gold == 0:
                break
            if not act.refresh():
                log.info("刷新没有效果，结束本回合购买")
                break
            refreshes += 1
            self.record("refresh", reason="final" if final else f"budget {refreshes}/{budget}")
        # leftover gold is lost at the end of the prep: one more level is better than nothing
        st = act.state()
        if not final and not st.maxed and st.gold and st.upgrade_cost is not None and st.gold >= st.upgrade_cost:
            self.upgrade_once(act)
        self.free_bench(act, BENCH_FREE_READY)

    def free_bench(self, act: PrepActions, free: int) -> None:
        """Before 准备就绪: leave ``free`` bench slots empty (operators given between rounds, and
        summons, need room; an overflowing unit is destroyed), selling the least useful."""
        missing = free - (len(SLOT_X) - act.bench_count())
        if missing > 0:
            self.sell_bench(act, missing)

    # --- knowledge --------------------------------------------------------------------
    def who(self, unit: Unit | ShopCard) -> Identity:
        return self.catalog.identify(unit.name, unit.tier, unit.labels)

    def owned(self, board: BoardState) -> list[Unit]:
        return board.units() + list(board.bench)

    def copies(self, board: BoardState, name: str) -> int:
        return sum(1 for u in self.owned(board) if name and u.name == name)

    def elite_owned(self, board: BoardState, name: str) -> bool:
        return any(u.elite and u.name == name for u in self.owned(board))

    def field_count(self, act: PrepActions) -> int:
        st = act.state()
        if st.slots_left is not None:
            return act.layout.max_operators - st.slots_left
        return len(act.board.occupied)

    def free_slots(self, act: PrepActions) -> int:
        st = act.state()
        region = len(act.layout.region_cells())
        on_field = self.field_count(act)
        left = st.slots_left if st.slots_left is not None else act.layout.max_operators - on_field
        return max(0, min(left, region - on_field))

    # --- valuation --------------------------------------------------------------------
    def bond_weight(self, bond: str) -> float:
        if bond in self.p.bond_weights:
            return self.p.bond_weights[bond]
        return self.p.season_weight if self.catalog.is_season(bond) else self.p.other_weight

    def power(self, units: Sequence[Unit | ShopCard]) -> float:
        p = self.p
        value = 0.0
        distinct: dict[str, Identity] = {}
        for i, u in enumerate(units):
            ident = self.who(u)
            tier = ident.tier or u.tier
            value += (p.tier_power[tier] if 0 <= tier < len(p.tier_power) else 0) * \
                (p.elite_mul if getattr(u, "elite", False) else 1)
            distinct.setdefault(u.name or f"?{i}", ident)
        counts: dict[str, int] = {}
        medics = melee = 0
        for ident in distinct.values():
            medics += ident.medic
            melee += ident.melee and ident.block >= 1
            for b in ident.bonds:
                counts[b] = counts.get(b, 0) + 1
        for bond, n in counts.items():
            if bond in p.inactive_bonds:
                continue
            th = self.catalog.thresholds(bond)
            w = self.bond_weight(bond)
            reached = sum(1 for t in th if n >= t)
            value += w * reached * (1 + 0.15 * (n - th[0]))
            if not reached:
                value += w * p.bond_prospect * n
        value += p.medic_weight * min(medics, p.medic_max) - (6 * (medics - p.medic_max) if medics > p.medic_max else 0)
        value += p.melee_weight * min(melee, p.melee_min)
        return value

    def field_gain(self, board: BoardState, card: ShopCard | Unit) -> tuple[float, str | None]:
        """Power added by fielding ``card``; when the region is full, by replacing the
        operator whose removal costs least (its cell id is returned)."""
        field_units = list(board.occupied.items())
        units = [u for _, u in field_units]
        base = self.power(units)
        if len(units) < 8:
            return self.power(units + [card]) - base, None
        best: tuple[float, str | None] = (float("-inf"), None)
        for cid, u in field_units:
            if u.name == card.name:
                continue
            gain = self.power([x for x in units if x is not u] + [card]) - base
            if gain > best[0]:
                best = (gain, cid)
        return best

    def merge_gain(self, board: BoardState, card: ShopCard) -> float:
        if self.elite_owned(board, card.name):
            return float("-inf")
        n = self.copies(board, card.name)
        if not n:
            return 0.0
        tier = self.who(card).tier or card.tier
        elite = (self.p.tier_power[tier] if 0 <= tier < len(self.p.tier_power) else 0) * (self.p.elite_mul - 1)
        share = self.p.merge_share[min(n, len(self.p.merge_share) - 1)]
        return elite * share + (elite * 0.5 if n >= 2 else 0)

    # --- placement --------------------------------------------------------------------
    def cells_for(self, unit: Unit, layout: Layout) -> list[Cell]:
        cells = layout.region_cells()
        safe = [c for c in cells if c.tag == "safe"]
        road = [c for c in cells if c.tag != "safe"]
        return road + safe if self.who(unit).melee else safe + road

    def place_bench(self, act: PrepActions) -> None:
        """Deploy bench operators that add enough (copies wait for their merge); an elite
        or a clearly better operator replaces the weakest when the region is full."""
        board = act.board

        def choose(unit: Unit) -> list[Cell]:
            if any(u.name == unit.name for u in board.units()):
                return []
            if self.free_slots(act) <= 0:
                return []
            if unit.elite or self.power(board.units() + [unit]) - self.power(board.units()) >= self.p.buy_min:
                return self.cells_for(unit, act.layout)
            return []

        if act.deploy_bench(choose):
            self.record("deploy", reason="bench")
        if self.free_slots(act) > 0:
            return
        for unit in list(board.bench):
            if not unit.bench_xy or any(u.name == unit.name for u in board.units()):
                continue
            gain, out = self.field_gain(board, unit)
            if out and gain > self.p.replace_margin and act.replace(unit, act.layout.cells[out]):
                self.record("replace", unit, cell=out, value=gain, reason="bench")

    # --- bench ------------------------------------------------------------------------
    def sell_bench(self, act: PrepActions, n: int, keep=None) -> int:
        """Sell up to ``n`` bench operators, least useful first; ``keep(unit, names)`` spares one
        (``names``: every operator owned, bench as surveyed now plus the field)."""
        if n <= 0:
            return 0
        surveyed = act.survey_bench()
        names = [u.name for _, u in surveyed] + [u.name for u in act.board.units()]
        bench = [(x, u) for x, u in surveyed if not (keep and keep(u, names))]
        on_field = {u.name for u in act.board.units()}
        bench.sort(key=lambda e: (e[1].elite, e[1].name in on_field, names.count(e[1].name),
                                  self.who(e[1]).tier or e[1].tier))
        sold = 0
        for x, u in bench:
            if sold >= n:
                break
            if act.sell_bench(x, u):
                sold += 1
                self.record("sell", u)
        return sold

    def trim_bench(self, act: PrepActions) -> None:
        count = act.bench_count()
        if count > self.p.bench_keep:
            self.sell_bench(act, count - self.p.bench_keep)

    def sell_bench_for_final(self, act: PrepActions) -> None:
        """Leader round: bench operators no longer fight; keep elites and merge pairs, sell the rest."""
        self.sell_bench(act, len(SLOT_X), keep=lambda u, names: u.elite or names.count(u.name) >= 2)

    # --- buying -----------------------------------------------------------------------
    def options(self, act: PrepActions, fill_only: bool) -> list[tuple[float, float, str, ShopCard, str | None]]:
        st = act.state()
        board = act.board
        room = self.free_slots(act) > 0 and not self.no_room
        out = []
        for card in st.cards:
            if not card.operator or card.cost is None or (st.gold is not None and card.cost > st.gold):
                continue
            merge = self.merge_gain(board, card)
            if merge == float("-inf"):
                continue
            on_field = any(u.name == card.name for u in board.units())
            cell = None
            if on_field or (merge > 0 and not fill_only):
                if fill_only and self.copies(board, card.name) < 2:
                    continue
                value, kind = merge, "merge"
            else:
                gain, cell = self.field_gain(board, card)
                value, kind = gain + merge, ("replace" if cell else "field")
                if kind == "replace" and (fill_only or gain < self.p.replace_margin):
                    continue
                if kind == "field" and not room:
                    continue    # no place left (or a deployment failed): it could only wait on the bench
            if card.cost == 0:
                value += 100
            out.append((value / max(1, card.cost) ** 0.3, value, kind, card, cell))
        out.sort(key=lambda o: (-o[0], o[3].slot))
        return out

    def buy_one(self, act: PrepActions, fill_only: bool = False) -> bool:
        ranked = self.options(act, fill_only)
        if not ranked:
            return False
        _, value, kind, card, cell = ranked[0]
        if value < (self.p.merge_min if kind == "merge" else self.p.buy_min):
            return False
        # keep at least one bench slot free while preparing: a copy that completes a merge
        # takes no slot, anything else does
        adds = not (kind == "merge" and self.copies(act.board, card.name) >= 2)
        if adds and len(SLOT_X) - act.bench_count() <= BENCH_FREE_PREP and not self.sell_bench(act, 1):
            return False
        unit = act.buy(card)
        if unit is None:
            if act.refusal == "bench_full" and self.sell_bench(act, 1):
                unit = act.buy(card)
            if unit is None:
                return False
        self.record("buy", card, slot=card.slot, value=value, reason=kind + (" fill" if fill_only else ""))
        if not unit.bench_xy:          # merged into an elite on the field
            return True
        if kind == "field" and self.free_slots(act) > 0:
            placed = act.deploy(unit, self.cells_for(unit, act.layout))
            if placed is not None:
                self.record("deploy", unit, cell=placed.id, reason="buy")
            elif getattr(act, "deploy_failure", "no_room") != "missing":
                self.no_room = True
        elif kind == "replace" and cell and act.replace(unit, act.layout.cells[cell]):
            self.record("replace", unit, cell=cell, value=value, reason="buy")
        return True

    # --- shop level -------------------------------------------------------------------
    def read_level(self, act: PrepActions) -> int:
        st = act.state()
        read = 6 if st.maxed else st.level
        if read:
            self.level = read
        return self.level

    def upgrade_once(self, act: PrepActions) -> bool:
        # an unread 升级 box is no reason to give up: act.upgrade() reads it again (and knows
        # where it should be), so a misread at the start of a round cannot stop the levelling
        st = act.state()
        if st.maxed:
            return False
        if st.gold is not None and st.upgrade_cost is not None and st.gold < st.upgrade_cost:
            return False
        if not act.upgrade():
            return False
        self.level = min(6, self.level + 1)
        self.record("upgrade", reason=f"level {self.level}")
        return True

    def level_up(self, act: PrepActions, rnd: int) -> None:
        want = self.level_wanted(rnd)
        for _ in range(6):
            if self.read_level(act) >= want:
                return
            if not self.upgrade_once(act):
                st = act.state()
                log.info("商店 %d 级，低于本回合目标 %d 级，没有升级（资金 %s，升级费用 %s%s）", self.level, want,
                         st.gold, st.upgrade_cost, "，未找到「升级」框" if st.level_x is None else "")
                return
            log.info("商店升到 %d 级（本回合目标 %d 级）", self.level, want)
