"""Checking that the game's own UI scale (PC client setting) is 100 %.

The mode buttons 个人模拟 / 联合模拟 and the start button below them belong to one panel.
At 100 % (1920×1080 coordinates) their labels are 255 px apart horizontally and 159 px
vertically. A different spacing shows that the layout is not the 100 % one; it does not
tell the actual setting, because how the game rearranges the panel at other scales is
not known.
"""
from __future__ import annotations

from statistics import median
from typing import Sequence

from .ocr import TextBox, find

REF_DX = 255.0       # 个人模拟 → 联合模拟
REF_DY = 159.0       # 联合模拟 → 独立模拟 (personal) / 搜寻队友 (joint)
TOLERANCE = 0.04     # OCR centres move a few pixels; 4 % is well above that


def panel_spacing_percent(boxes: Sequence[TextBox]) -> int | None:
    """Spacing of the start-screen panel relative to the 100 % layout (100 = same), or None
    when the start screen is not shown."""
    personal = find(boxes, "个人模拟")
    joint = find(boxes, "联合模拟")
    below = find(boxes, "独立模拟", "搜寻队友")
    ratios = []
    if personal and joint and joint.x > personal.x:
        ratios.append((joint.x - personal.x) / REF_DX)
    if joint and below and below.y > joint.y:
        ratios.append((below.y - joint.y) / REF_DY)
    return round(median(ratios) * 100) if ratios else None


def matches_default(percent: int) -> bool:
    return abs(percent - 100) <= TOLERANCE * 100
