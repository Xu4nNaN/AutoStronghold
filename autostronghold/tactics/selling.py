"""Which bench (整备区) operators to sell when it is full. Pure logic, no I/O.

Order, first sold first:
  1. operators with no duplicate (no other copy on the bench or field) before duplicated ones;
  2. lower tier before higher tier;
  3. by trait: none of the listed traits, then 迅捷 > 奥术 > 精准 > 远见
     (an operator carrying several listed traits ranks by the one sold last).
Exception: with more than ``foresight_first_over`` (default 2) non-duplicated 远见
operators the trait order becomes 远见 > 迅捷 > 奥术 > 精准.
"""
from __future__ import annotations

from typing import Sequence

from ..game.board import Unit

DEFAULT_ORDER = ("迅捷", "奥术", "精准", "远见")
FORESIGHT = "远见"


def has_trait(unit: Unit, trait: str) -> bool:
    return any(trait in label for label in unit.labels)


def sell_order(bench: Sequence[tuple[int, Unit]], field: Sequence[Unit],
               order: Sequence[str] = DEFAULT_ORDER, foresight_first_over: int = 2) -> list[tuple[int, Unit]]:
    """Bench entries ``(slot x, unit)`` sorted from first to sell to last."""
    names = [u.name for _, u in bench] + [u.name for u in field]

    def duplicated(u: Unit) -> bool:
        return u.elite or (bool(u.name) and names.count(u.name) > 1)

    solo_foresight = sum(1 for _, u in bench if has_trait(u, FORESIGHT) and not duplicated(u))
    solo_foresight += sum(1 for u in field if has_trait(u, FORESIGHT) and not duplicated(u))
    traits = list(order)
    if solo_foresight > foresight_first_over and FORESIGHT in traits:
        traits.remove(FORESIGHT)
        traits.insert(0, FORESIGHT)

    def trait_rank(u: Unit) -> int:
        present = [i for i, t in enumerate(traits) if has_trait(u, t)]
        return 1 + max(present) if present else 0

    return sorted(bench, key=lambda e: (duplicated(e[1]), e[1].tier, trait_rank(e[1])))
