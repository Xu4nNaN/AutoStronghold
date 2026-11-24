"""Map layout and what we know about the operators on the field."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from ..paths import user_file


@dataclass(frozen=True)
class Cell:
    id: str
    col: int          # from the right, red-gate column excluded
    row: int          # from the top
    x: int            # drag-view screen position
    y: int
    tag: str          # "path" | "safe" | "blocked"

    @property
    def point(self) -> tuple[int, int]:
        return self.x, self.y


@dataclass
class Layout:
    cells: dict[str, Cell]
    columns: tuple[int, int]
    rows: tuple[int, int]
    max_operators: int
    order: list[str]

    def in_region(self, cell: Cell) -> bool:
        return (self.columns[0] <= cell.col <= self.columns[1] and self.rows[0] <= cell.row <= self.rows[1]
                and cell.tag != "blocked")

    def region_cells(self) -> list[Cell]:
        """Cells operators may use, in the preferred filling order."""
        ordered = [self.cells[i] for i in self.order if i in self.cells and self.in_region(self.cells[i])]
        rest = [c for c in self.cells.values() if self.in_region(c) and c not in ordered]
        rest.sort(key=lambda c: (c.col, c.row))
        return ordered + rest

    @classmethod
    def load(cls, path: Path | None = None) -> "Layout":
        path = path or user_file("layout/board.json")
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        cells = {c["id"]: Cell(c["id"], int(c["col"]), int(c["row"]), int(c["x"]), int(c["y"]), c.get("tag", "path"))
                 for c in data["cells"]}
        region = data.get("region", {})
        cols = tuple(region.get("columns", (2, 4)))
        rows = tuple(region.get("rows", (1, 3)))
        return cls(cells, (int(cols[0]), int(cols[1])), (int(rows[0]), int(rows[1])),
                   int(data.get("max_operators", 8)), list(data.get("order", [])))


@dataclass(eq=False)   # two copies of the same operator are different units
class Unit:
    """An operator we bought."""

    name: str
    tier: int = 0
    labels: tuple[str, ...] = ()
    cost: int | None = None
    bench_xy: tuple[int, int] | None = None   # where it waits on the bench (normal view)
    elite: bool = False                       # three copies merged (精锐)
    equipment: bool = False                   # what was picked up is equipment, not an operator
    summon: bool = False                      # a summon (狼群 …): takes a bench slot, cannot be sold
    unknown: bool = False                     # the slot could not be picked up and read (some summons)
    misses: int = 0                           # failed reads of an unknown slot this game

    def describe(self) -> str:
        return f"{self.name or '未知干员'}（{self.tier or '?'}阶{'·精锐' if self.elite else ''}）"


@dataclass
class BoardState:
    occupied: dict[str, Unit] = field(default_factory=dict)   # cell id -> unit
    bench: list[Unit] = field(default_factory=list)          # bought but not deployed
    sold: int = 0
    shop_level: int | None = None   # last known 调度中心 level (the numeral is not always readable)
    resumed: bool = False           # joined a game already in progress: the field record starts empty
    bench_full: bool = False        # the last arrival took the leftmost slot (slots fill right to left)

    def units(self) -> list[Unit]:
        return list(self.occupied.values())

    def copies(self, name: str) -> int:
        return sum(1 for u in self.units() + self.bench if name and u.name == name)

    def label_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for u in self.units():
            for label in u.labels:
                counts[label] = counts.get(label, 0) + 1
        return counts


def is_green(image: np.ndarray, point: tuple[int, int], radius: int = 20) -> bool:
    """While an operator is held, free deployable cells are highlighted green."""
    x, y = point
    crop = image[max(0, y - radius): y + radius, max(0, x - radius): x + radius]
    if crop.size == 0:
        return False
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    return float(cv2.inRange(hsv, (35, 90, 90), (85, 255, 255)).mean() / 255) > 0.5
