"""The three features offered in the menu.

A feature is a list of stages; each stage plays games in one simulation target until
its badge goal is met. Adding a feature (for example one that uses 规程等级 5) means
adding a :class:`Feature` here and an entry in ``FEATURES``.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..extensions.targets import SPEED, SimulationTarget, independent
from ..vision.grid import Badge
from .goals import BadgeGoal

ANY_BADGE = frozenset({Badge.GOLD, Badge.COLOR})
COLOR_ONLY = frozenset({Badge.COLOR})


@dataclass(frozen=True)
class Stage:
    target: SimulationTarget
    goal: BadgeGoal


@dataclass(frozen=True)
class Feature:
    key: str
    title: str
    summary: str
    stages: tuple[Stage, ...]


ETCHING = Feature(
    "etching", "蚀刻章",
    "极速模拟中已获得角标（金标或彩标）的策略达到 20 个即完成；否则刷第一个没有角标的策略。",
    (Stage(SPEED, BadgeGoal(ANY_BADGE, count_target=20, name="蚀刻章")),),
)

ALL_GOLD = Feature(
    "all_gold", "全角标金标",
    "先让极速模拟的所有策略都有角标，再在独立模拟·规程等级1 中做同样的事。",
    (Stage(SPEED, BadgeGoal(ANY_BADGE, name="极速模拟全角标")),
     Stage(independent(1), BadgeGoal(ANY_BADGE, name="规程等级1全角标"))),
)

ALL_COLOR = Feature(
    "all_color", "全角标彩标",
    "先让极速模拟的所有策略都有彩标，再在独立模拟·规程等级1 中做同样的事。",
    (Stage(SPEED, BadgeGoal(COLOR_ONLY, name="极速模拟全彩标")),
     Stage(independent(1), BadgeGoal(COLOR_ONLY, name="规程等级1全彩标"))),
)

FEATURES: tuple[Feature, ...] = (ETCHING, ALL_GOLD, ALL_COLOR)
