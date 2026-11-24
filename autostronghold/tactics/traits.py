"""Default tactic "叠层优先" (trait stacking).

Operators are valued by how much they add to trait stacks, not by their own strength:

* trait priority 精准 > 奥术 > 远见 (``trait_weights``);
* target field: 3 × 精准, 2 × 奥术, 1 medic, the remaining cells for 远见 stackers
  (``composition``, ``medic_count``). A trait below its target counts extra; above it,
  精准/奥术 still add (``over_target_factor``) and 远见 always adds fully;
* copies of an operator already owned add (3 copies merge into an elite); for operators
  costing 1 the copy bonus is larger and they get a cost bonus, because three copies are
  cheap to collect and low-tier elites keep growing;
* tier is only a small tie-breaker.

Round plan: round 1 buys ``opening_buys`` operators; from then on the field is first
kept at ``min_field_by_round`` operators, and the rest is spent on the best stacking
cards, replacing the weakest field operator when the 8 region cells are full, and
refreshing a maxed shop. Shop levels: from ``upgrade_from_round`` the shop is levelled
straight to ``buy_first_level`` (3). From there operators come first: the shop goes up one
level only when the field reaches one of the lineups in ``level_up_lineups`` for the
current level, or after ``level_up_after_rounds`` rounds of buying at that level. A
clearly better card that is 1-2 gold out of reach is bought after selling bench operators.
When the bench (整备区) is full — or a purchase is refused for that reason — bench
operators are sold in the order defined in :mod:`tactics.selling`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .. import log
from ..extensions.advisor import Advisor, NullAdvisor
from ..game.board import BoardState, Cell, Layout, Unit
from ..paths import user_file
from ..vision.bench import SLOT_X
from ..vision.hud import PrepState, ShopCard
from .base import PrepActions
from .selling import DEFAULT_ORDER, has_trait, sell_order


@dataclass
class TraitConfig:
    opening_buys: int = 2
    upgrade_from_round: int = 2
    buy_first_level: int = 3             # from this shop level on, operators come before levels
    # Field lineups (distinct operators per trait) that earn the next level; any one is enough.
    level_up_lineups: dict[int, list[dict[str, int]]] = field(default_factory=lambda: {
        3: [{"精准": 2}, {"精准": 1, "奥术": 1}],
        4: [{"精准": 3, "奥术": 1}, {"精准": 2, "奥术": 2}],
        5: [{"精准": 3, "奥术": 2}, {"精准": 2, "奥术": 3}],
    })
    level_up_after_rounds: int = 2       # ...or after this many rounds of buying at that level
    min_field_by_round: dict[int, int] = field(default_factory=lambda: {2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 8})
    min_value_when_maxed: float = 30
    replace_margin: float = 15
    max_refresh_per_round: int = 8
    refresh_reserve: int = 0
    tier_value: dict[int, float] = field(default_factory=lambda: {0: 6, 1: 4, 2: 6, 3: 9, 4: 12, 5: 16, 6: 20})
    trait_weights: dict[str, float] = field(default_factory=lambda: {"精准": 30, "奥术": 24, "远见": 18})
    composition: dict[str, int] = field(default_factory=lambda: {"精准": 3, "奥术": 2})
    over_target_factor: float = 0.4
    below_target_factor: float = 1.6
    medics: list[str] = field(default_factory=list)
    medic_count: int = 1
    medic_bonus: float = 35
    duplicate_bonus: list[float] = field(default_factory=lambda: [0, 12, 30])
    # Cheap operators: easy to collect three copies, and low-tier elites keep growing.
    cost_bonus: dict[int, float] = field(default_factory=lambda: {1: 14})
    cheap_merge_factor: float = 1.5      # duplicate bonus multiplier for operators costing 1
    sell_for_funds_max: int = 2          # bench operators that may be sold to afford a card
    sell_for_funds_margin: float = 10    # ...only for a card worth this much more than the best affordable one
    priority: dict[str, float] = field(default_factory=dict)
    ranged: list[str] = field(default_factory=list)
    bench_keep: int = 8
    sell_trait_order: list[str] = field(default_factory=lambda: list(DEFAULT_ORDER))
    foresight_first_over: int = 2

    @classmethod
    def load(cls, path: Path | None = None) -> "TraitConfig":
        path = path or user_file("tactics/default.json")
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        cfg = cls()
        for key, value in data.items():
            if key.startswith("_") or not hasattr(cfg, key):
                continue
            if key in ("tier_value", "cost_bonus"):
                value = {int(k): float(v) for k, v in value.items()}
            elif key == "min_field_by_round":
                value = {int(k): int(v) for k, v in value.items()}
            elif key == "level_up_lineups":
                value = {int(k): [{t: int(n) for t, n in lineup.items()} for lineup in v] for k, v in value.items()}
            setattr(cfg, key, value)
        return cfg


def _matches(name: str, keys: Sequence[str]) -> bool:
    return bool(name) and any(k and k in name for k in keys)


class TraitStackTactic:
    name = "叠层优先"

    def __init__(self, config: TraitConfig | None = None, advisor: Advisor | None = None):
        self.cfg = config or TraitConfig()
        self.advisor = advisor or NullAdvisor()
        self.shop_level = 1
        self.rounds_at_level = 0     # rounds of buying at the current shop level

    # --- valuation ---------------------------------------------------------------
    def is_medic(self, unit: Unit | ShopCard) -> bool:
        return _matches(unit.name, self.cfg.medics)

    def _field_counts(self, units: Sequence[Unit]) -> tuple[dict[str, int], int]:
        """Distinct operators per trait (copies of one operator count once) and medics."""
        distinct: dict[str, Unit] = {}
        for i, u in enumerate(units):
            distinct.setdefault(u.name or f"?{i}", u)
        counts = {t: sum(1 for u in distinct.values() if has_trait(u, t)) for t in self.cfg.trait_weights}
        medics = sum(1 for u in distinct.values() if self.is_medic(u))
        return counts, medics

    def on_field(self, name: str, board: BoardState) -> bool:
        return bool(name) and any(u.name == name for u in board.units())

    def protected(self, unit: Unit, newcomer: Unit, board: BoardState) -> bool:
        """Removing ``unit`` would drop a composition trait (or the only medic) below its
        target and ``newcomer`` does not bring it back."""
        others = [u for u in board.units() if u is not unit]
        counts, medics = self._field_counts(others)
        for trait, target in self.cfg.composition.items():
            if has_trait(unit, trait) and counts.get(trait, 0) < target and not has_trait(newcomer, trait):
                return True
        return self.is_medic(unit) and medics < self.cfg.medic_count and not self.is_medic(newcomer)

    def _value(self, name: str, tier: int, labels: Sequence[str], others: Sequence[Unit],
               copies: int, cost: int | None = None) -> float:
        probe = Unit(name, tier, tuple(labels))
        counts, medics = self._field_counts(others)
        value = self.cfg.tier_value.get(tier, self.cfg.tier_value.get(0, 6))
        for trait, weight in self.cfg.trait_weights.items():
            if not has_trait(probe, trait):
                continue
            target = self.cfg.composition.get(trait)
            if target is None:
                value += weight                      # pure stacking trait (远见)
            elif counts[trait] < target:
                value += weight * self.cfg.below_target_factor
            else:
                value += weight * self.cfg.over_target_factor
        if self.is_medic(probe):
            value += self.cfg.medic_bonus if medics < self.cfg.medic_count else -self.cfg.medic_bonus
        cheap = cost is not None and cost <= 1
        if copies:
            bonus = self.cfg.duplicate_bonus[min(copies, len(self.cfg.duplicate_bonus) - 1)]
            value += bonus * (self.cfg.cheap_merge_factor if cheap else 1)
        if cost is not None:
            value += self.cfg.cost_bonus.get(cost, 0)
        value += max((v for k, v in self.cfg.priority.items() if k in (name or "")), default=0)
        return value

    def card_value(self, card: ShopCard, board: BoardState) -> float:
        advised = self.advisor.card_value(card, board)
        if advised is not None:
            return advised
        value = self._value(card.name, card.tier, card.labels, board.units(), board.copies(card.name), card.cost)
        return value + (200 if card.cost == 0 else 0)   # free operator after a promotion

    def unit_value(self, unit: Unit, board: BoardState) -> float:
        """What this field operator contributes (counted as if it were being added)."""
        others = [u for u in board.units() if u is not unit]
        copies = sum(1 for u in others if unit.name and u.name == unit.name)
        return self._value(unit.name, unit.tier, unit.labels, others, copies, unit.cost) + (20 if unit.elite else 0)

    def is_ranged(self, unit: Unit) -> bool:
        return _matches(unit.name, self.cfg.ranged) or self.is_medic(unit) or has_trait(unit, "精准")

    def cells_for(self, unit: Unit, layout: Layout, board: BoardState) -> list[Cell]:
        """Where ``unit`` may go, best first. Empty for a copy of an operator already on
        the field: copies add nothing to trait counts and wait on the bench until three
        merge into an elite (the field copy is the one that is promoted)."""
        if self.on_field(unit.name, board):
            return []
        cells = layout.region_cells()
        safe = [c for c in cells if c.tag == "safe"]
        path = [c for c in cells if c.tag != "safe"]
        ordered = safe + path if self.is_ranged(unit) else path + safe
        advised = self.advisor.choose_cell(unit, [c for c in ordered if c.id not in board.occupied], board)
        if advised is not None:
            ordered = [advised] + [c for c in ordered if c is not advised]
        return ordered

    # --- Tactic interface --------------------------------------------------------
    def on_match_start(self) -> None:
        self.shop_level = 1
        self.rounds_at_level = 0

    def choose_option(self, title: str, options: Sequence[str]) -> int:
        return 1 if len(options) >= 2 else 0   # the middle option

    def on_prep(self, act: PrepActions, round_no: int | None) -> None:
        st = act.state()
        rnd = round_no or st.round or 0
        act.deploy_bench(lambda unit: self.cells_for(unit, act.layout, act.board))
        self._sell_if_bench_full(act)
        if rnd <= 1 and not act.board.occupied:
            for _ in range(self.cfg.opening_buys):
                if not self._buy_one(act, act.state(), opening=True):
                    break
            return
        if self._fill_field(act, rnd) is None:
            return
        if rnd >= self.cfg.upgrade_from_round:
            self._upgrade_early(act)
            self._level_up_if_earned(act)
        self._buy_round(act)
        if rnd >= self.cfg.upgrade_from_round and self._level(act) >= self.cfg.buy_first_level:
            self.rounds_at_level += 1
            self._level_up_if_earned(act)

    def _buy_round(self, act: PrepActions) -> None:
        refreshes = 0
        for _ in range(40):   # hard bound: each pass buys, refreshes or stops
            st = act.state()
            if st.gold == 0:
                break
            bought = self._buy_one(act, st)
            if bought:
                continue
            if bought is None:
                break
            if not st.maxed or refreshes >= self.cfg.max_refresh_per_round:
                break
            cost = st.refresh_cost if st.refresh_cost is not None else 1
            if st.gold is not None and st.gold < cost + self.cfg.refresh_reserve:
                break
            if not act.refresh():
                log.info("刷新没有效果，结束本回合购买")
                break
            refreshes += 1

    # --- steps -------------------------------------------------------------------
    def _sell_if_bench_full(self, act: PrepActions, force: bool = False) -> int:
        """Sell bench operators down to ``bench_keep`` when the bench is full."""
        if not force and act.bench_count() < len(SLOT_X):
            return 0
        bench = act.survey_bench()
        excess = len(bench) - min(self.cfg.bench_keep, len(SLOT_X) - 1)
        sold = 0
        for slot_x, unit in sell_order(bench, act.board.units(), self.cfg.sell_trait_order,
                                       self.cfg.foresight_first_over)[:max(excess, 1 if force else 0)]:
            if act.sell_bench(slot_x, unit):
                sold += 1
        return sold

    def _wanted_field(self, rnd: int, limit: int) -> int:
        reached = [n for r, n in self.cfg.min_field_by_round.items() if r <= rnd]
        return min(max(reached, default=0), limit)

    def _fill_field(self, act: PrepActions, rnd: int) -> bool | None:
        """Keep enough defenders before spending on shop levels; None if a purchase was refused."""
        wanted = self._wanted_field(rnd, act.layout.max_operators)
        for _ in range(8):
            st = act.state()
            if st.slots_left is not None:
                field_count = act.layout.max_operators - st.slots_left
            else:
                field_count = len(act.board.occupied)
            if field_count >= wanted:
                return True
            bought = self._buy_one(act, st, opening=True)
            if not bought:
                return bought
        return True

    # --- shop level ----------------------------------------------------------------
    def _level(self, act: PrepActions) -> int:
        """Shop level: the HUD numeral when it was read, otherwise the upgrades counted
        since the match started (a lone "I" is not readable)."""
        st = act.state()
        read = 6 if st.maxed else st.level
        if read and read != self.shop_level:
            self.shop_level = read
            self.rounds_at_level = 0
        return self.shop_level

    def _upgrade_once(self, act: PrepActions) -> bool:
        st = act.state()
        if st.maxed or st.level_x is None:
            return False
        if st.gold is not None and st.upgrade_cost is not None and st.gold < st.upgrade_cost:
            return False
        if not act.upgrade():
            return False
        self.shop_level = min(6, self.shop_level + 1)
        self.rounds_at_level = 0
        return True

    def _upgrade_early(self, act: PrepActions) -> None:
        """Below ``buy_first_level`` the shop is levelled as far as the gold allows."""
        while self._level(act) < self.cfg.buy_first_level:
            if not self._upgrade_once(act):
                return

    def lineup_reached(self, level: int, units: Sequence[Unit]) -> bool:
        counts, _ = self._field_counts(units)
        return any(all(counts.get(t, 0) >= n for t, n in lineup.items())
                   for lineup in self.cfg.level_up_lineups.get(level, []))

    def _level_up_if_earned(self, act: PrepActions) -> None:
        """From ``buy_first_level`` on: one level when the field reached a wanted lineup,
        or after ``level_up_after_rounds`` rounds of buying at this level."""
        level = self._level(act)
        if level < self.cfg.buy_first_level or level >= 6:
            return
        reached = self.lineup_reached(level, act.board.units())
        if not reached and self.rounds_at_level < self.cfg.level_up_after_rounds:
            return
        why = "阵容已达标" if reached else f"已在此等级购买 {self.rounds_at_level} 回合"
        if self._upgrade_once(act):
            log.info("商店 %d → %d 级（%s）", level, level + 1, why)

    def _free_slots(self, act: PrepActions, st: PrepState) -> int:
        """Free region cells. The HUD count is authoritative (remembered occupants can be
        stale after merges); the region size caps it."""
        region = len(act.layout.region_cells())
        if st.slots_left is not None:
            on_field = act.layout.max_operators - st.slots_left
            return max(0, min(st.slots_left, region - on_field))
        return sum(1 for c in act.layout.region_cells() if c.id not in act.board.occupied)

    def _buy(self, act: PrepActions, card: ShopCard) -> Unit | None:
        unit = act.buy(card)
        if unit is None and act.refusal == "bench_full" and self._sell_if_bench_full(act, force=True):
            unit = act.buy(card)
        return unit

    def _sell_for_funds(self, act: PrepActions, st: PrepState) -> PrepState:
        """When a clearly better card is just out of reach, sell bench operators to afford it.

        Only bench operators without a duplicate (no elite in the making) are sold, in the
        bench selling order, at most ``sell_for_funds_max`` of them.
        """
        if st.gold is None:
            return st
        board = act.board
        cards = [c for c in st.cards if c.operator and c.cost is not None]
        affordable = [self.card_value(c, board) for c in cards if c.cost <= st.gold]
        wanted = [c for c in cards if c.cost > st.gold and c.cost - st.gold <= self.cfg.sell_for_funds_max
                  and self.card_value(c, board) >= max(affordable, default=0) + self.cfg.sell_for_funds_margin]
        if not wanted:
            return st
        target = max(wanted, key=lambda c: self.card_value(c, board))
        names = [u.name for u in board.units()] + [u.name for u in board.bench]
        bench = [(x, u) for x, u in act.survey_bench() if not u.elite and names.count(u.name) <= 1]
        if len(bench) < target.cost - st.gold:
            return st
        log.info("资金不足以购买 %s（需 %d，现有 %d），出售整备区干员补足", target.describe(), target.cost, st.gold)
        for slot_x, unit in sell_order(bench, board.units(), self.cfg.sell_trait_order,
                                       self.cfg.foresight_first_over)[:self.cfg.sell_for_funds_max]:
            act.sell_bench(slot_x, unit)
            st = act.state()
            if st.gold is not None and st.gold >= target.cost:
                break
        return st

    def _buy_one(self, act: PrepActions, st: PrepState, opening: bool = False) -> bool | None:
        """True: bought one. False: nothing worth buying. None: the game refused a purchase."""
        board = act.board
        st = self._sell_for_funds(act, st)
        affordable = [c for c in st.cards if c.operator and c.cost is not None
                      and (st.gold is None or c.cost <= st.gold)]
        if not affordable:
            return False
        ranked = sorted(affordable, key=lambda c: self.card_value(c, board), reverse=True)
        free = self._free_slots(act, st)
        for card in ranked:
            value = self.card_value(card, board)
            special = card.cost == 0 or board.copies(card.name) >= 2   # free gift, or completes an elite
            if free > 0:
                if opening and self.on_field(card.name, board):
                    continue   # filling the field needs a new operator, not a merge copy
                if st.maxed and not opening and not special and value < self.cfg.min_value_when_maxed:
                    continue
                unit = self._buy(act, card)
                if unit is None:
                    log.info("购买被拒绝（%s），结束本回合购买",
                             "整备区已满" if act.refusal == "bench_full" else "资金不足")
                    return None
                cells = self.cells_for(unit, act.layout, board)
                if cells:
                    act.deploy(unit, cells)
                else:
                    log.info("%s 已在场上，新买的这名留在整备区等待合成精锐", unit.describe())
                return True
            newcomer = Unit(card.name, card.tier, tuple(card.labels))
            if self.on_field(card.name, board):
                # A copy for merging: buy it to wait on the bench, never to replace someone.
                if special and act.bench_count() < len(SLOT_X):
                    unit = self._buy(act, card)
                    return None if unit is None else True
                continue
            weakest = self._weakest(act, newcomer)
            gain = self._value(card.name, card.tier, card.labels, board.units(), 0, card.cost)
            if weakest and gain >= weakest[1] + self.cfg.replace_margin:
                unit = self._buy(act, card)
                if unit is None:
                    return None
                if unit.bench_xy:
                    act.replace(unit, weakest[0])
                return True
        return False

    def _weakest(self, act: PrepActions, newcomer: Unit) -> tuple[Cell, float] | None:
        """Weakest field operator ``newcomer`` may replace: never a copy of itself, and never
        one whose removal breaks the 精准/奥术/medic composition (see :meth:`protected`)."""
        board = act.board
        scored = [(act.layout.cells[cid], self.unit_value(u, board)) for cid, u in board.occupied.items()
                  if cid in act.layout.cells and u.name != newcomer.name
                  and not self.protected(u, newcomer, board)]
        return min(scored, key=lambda t: t[1]) if scored else None
