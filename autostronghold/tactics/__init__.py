"""Tactics: how gold is spent and where operators go. See ``base.Tactic``.

Each simulation target has its own strategy module; :func:`tactic_for` is the only place
that chooses between them. Adding or removing a strategy means adding / removing its
module, its parameter file and its line in ``STRATEGIES`` — no other strategy changes.

| target | strategy | module | parameters |
| --- | --- | --- | --- |
| 极速模拟 | SP3·极速模拟 | ``sp3/fast.py`` | ``tactics/sp3_fast.json`` |
| 独立模拟·规程等级1 | SP3·独立模拟·规程等级1 | ``sp3/independent_l1.py`` | ``tactics/sp3_independent_l1.json`` |
| 独立模拟·规程等级2~20 | SP3·独立模拟·通关优先 | ``sp3/independent_clear.py`` | ``tactics/sp3_independent_clear.json`` |

The pre-SP3 tactic 叠层优先 (``traits.py``, ``tactics/default.json``) stays available as
``trait_stack``: no target uses it by default, but it is the fallback when an SP3 strategy
cannot start (operator table or parameters missing, edited, or from another season — see
``sp3.catalog.DATA_VERSION`` and the content hash).
"""
from __future__ import annotations

import json
from typing import Callable

from .. import log
from ..extensions.targets import Mode, SimulationTarget
from .base import Tactic
from .traits import TraitConfig, TraitStackTactic


def _fast(target: SimulationTarget) -> Tactic:
    from .sp3.fast import FastTactic
    return FastTactic()


def _independent_l1(target: SimulationTarget) -> Tactic:
    from .sp3.independent_l1 import IndependentL1Tactic
    return IndependentL1Tactic()


def _independent_clear(target: SimulationTarget) -> Tactic:
    from .sp3.independent_clear import IndependentClearTactic
    return IndependentClearTactic(target.level or 2)


def _trait_stack(target: SimulationTarget) -> Tactic:
    return TraitStackTactic(TraitConfig.load())


STRATEGIES: dict[str, Callable[[SimulationTarget], Tactic]] = {
    "fast": _fast,
    "independent_l1": _independent_l1,
    "independent_clear": _independent_clear,
    "trait_stack": _trait_stack,
}


def strategy_key(target: SimulationTarget) -> str:
    if target.mode is Mode.SPEED:
        return "fast"
    if target.mode is Mode.INDEPENDENT:
        return "independent_l1" if (target.level or 1) == 1 else "independent_clear"
    raise ValueError(f"{target.label} 没有对应的打法")


def tactic_for(target: SimulationTarget) -> Tactic:
    key = strategy_key(target)
    try:
        return STRATEGIES[key](target)
    except KeyError:
        raise
    except (ValueError, OSError, json.JSONDecodeError) as exc:   # CatalogError is a ValueError
        log.warn("%s 的 SP3 打法无法启动（%s），改用旧打法「叠层优先」", target.label, exc)
        return _trait_stack(target)


def default_tactic() -> TraitStackTactic:
    """The pre-SP3 tactic (kept for comparison and older scripts)."""
    return TraitStackTactic(TraitConfig.load())
