"""Reading the preparation-phase HUD: round, gold, slots, shop level and shop cards."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import cv2
import numpy as np

from ..geometry import Prep as P
from .names import Names, clean
from .ocr import OcrEngine, TextBox, digits_of, find, has_cjk, in_region

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6}
# Highest tier an operator of a given cost can have (I-II cost 1-2, III-IV 3, V-VI 4).
# Cards of operators we already own glow gold, which can look like a V/VI frame.
MAX_TIER_FOR_COST = {0: 6, 1: 2, 2: 2, 3: 4, 4: 6}


@dataclass
class ShopCard:
    slot: int                 # index into the visible card slots, left to right
    x: int
    name: str = ""
    labels: list[str] = field(default_factory=list)   # alliance / trait lines
    cost: int | None = None
    tier: int = 0             # 1..6, 0 = unknown
    operator: bool = False    # operators have label lines; equipment cards do not
    empty: bool = False       # bought / "NO INFO"

    @property
    def tap_point(self) -> tuple[int, int]:
        return self.x, P.CARD_TAP_Y

    def describe(self) -> str:
        kind = "干员" if self.operator else "装备"
        tier = f"{self.tier}阶" if self.tier else "?阶"
        return f"{self.name or '?'}（{kind} {tier} {self.cost if self.cost is not None else '?'}费）"


@dataclass
class PrepState:
    round: int | None
    gold: int | None
    slots_left: int | None
    level_x: int | None           # x of the 升级 / 已满级 box
    maxed: bool
    upgrade_cost: int | None
    refresh_cost: int | None
    collapsed: bool
    cards: list[ShopCard]
    level: int | None = None      # shop level 1-6 (None when the numeral could not be read)


def parse_tier(text: str) -> int:
    t = text.strip().upper().replace("川", "III").replace("Ⅰ", "I").replace("Ⅱ", "II").replace("Ⅲ", "III")
    t = t.replace("Ⅳ", "IV").replace("Ⅴ", "V").replace("Ⅵ", "VI")
    t = "".join("I" if ch in "1L|!" else ch for ch in t)
    t = "".join(ch for ch in t if ch in "IV")
    return ROMAN.get(t, 0)


def tier_by_colour(image: np.ndarray, x: int) -> int:
    """Tier of the shop card centred at ``x`` (see :func:`tier_in_box`)."""
    return tier_in_box(image, (x + P.TIER_BOX_DX[0], P.TIER_BOX_Y[0], x + P.TIER_BOX_DX[1], P.TIER_BOX_Y[1]))


def tier_in_box(image: np.ndarray, box: tuple[int, int, int, int]) -> int:
    """Tier from the colour of a numeral frame: I grey, II white, III green, IV blue,
    V yellow, VI orange. Returns 0 when no frame is found."""
    x1, y1, x2, y2 = box
    crop = image[max(0, y1):y2, max(0, x1):x2]
    if crop.size == 0:
        return 0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.int32)
    h, s, v = hsv[:, 0], hsv[:, 1], hsv[:, 2]
    vivid = (s >= 110) & (v >= 120)
    if vivid.mean() >= 0.06:
        hue = float(np.median(h[vivid]))
        if hue < 19:
            return 6
        if hue < 35:
            return 5
        if hue < 88:
            return 3
        if hue < 125:
            return 4
        return 0
    pale = (s < 50)
    if (pale & (v >= 215)).mean() >= 0.06:
        return 2
    if (pale & (v >= 120)).mean() >= 0.05:
        return 1
    return 0


def is_collapsed(boxes: Sequence[TextBox]) -> bool:
    hit = find(boxes, "展开", region=P.EXPAND_BOX)
    return hit is not None and len(hit.compact) <= 4


def read_slots(image: np.ndarray, ocr: OcrEngine, boxes: Sequence[TextBox], collapsed: bool) -> int | None:
    label = find(boxes, "剩余可放置角色", "可放置角色")
    if label:
        tail = label.compact.split("：")[-1].split(":")[-1]
        d = digits_of(tail)
        if d and label.compact.rstrip().endswith(tail) and len(d) <= 1:
            return int(d)
    box = P.SLOTS_COLLAPSED if collapsed else P.SLOTS_NORMAL
    if label is not None:  # the number follows the label on the same line
        box = (int(label.box[2]) - 6, int(label.y) - 24, int(label.box[2]) + 40, int(label.y) + 24)
    value = ocr.read_number(image, box, 0, 99)
    return None if value is None else value % 10   # at most 8 operators


def read_cards(image: np.ndarray, ocr: OcrEngine, boxes: Sequence[TextBox], level_x: int | None) -> list[ShopCard]:
    left_limit = (level_x or 0) + 150
    names = Names.load()
    cards: list[ShopCard] = []
    shop_boxes = in_region(boxes, P.SHOP_TEXT)
    for x in P.CARD_X:
        if x <= left_limit:
            continue
        card = ShopCard(slot=len(cards), x=x)
        mine = [b for b in shop_boxes if abs(b.x - x) < P.CARD_HALF_WIDTH]
        card.empty = any("INFO" in b.compact.upper() for b in mine)
        labels = [b.compact for b in mine if P.LABEL_Y[0] <= b.y <= P.LABEL_Y[1] and has_cjk(b.compact)]
        lines = [b for b in mine if P.NAME_Y[0] <= b.y <= P.NAME_Y[1] and b.compact]
        raw = max(lines, key=lambda b: len(b.compact)).compact if lines else ""
        # the profession icon in front of the name is often read as a character (「水」「入」)
        hit = names.operator(raw)
        card.name = hit.name if hit.known else clean(raw)
        card.labels = names.labels(labels) or labels
        card.operator = bool(labels) and not card.empty and hit.kind != "equipment"
        if not card.empty:
            card.cost = ocr.read_number(image, (x - 24, P.CARD_COST_Y[0], x + 24, P.CARD_COST_Y[1]), 0, 9)
            card.tier = tier_by_colour(image, x)
            if not card.tier:
                numeral = [b for b in mine if P.TIER_BOX_Y[0] - 10 <= b.y <= P.TIER_BOX_Y[1] + 10
                           and b.x < x + P.TIER_BOX_DX[1] + 10]
                card.tier = parse_tier(numeral[0].compact) if numeral else 0
            if card.operator and card.cost is not None:
                card.tier = min(card.tier, MAX_TIER_FOR_COST.get(card.cost, 6))
        cards.append(card)
    return cards


def read_prep(image: np.ndarray, ocr: OcrEngine, boxes: Sequence[TextBox], numbers: bool = True) -> PrepState:
    """The whole HUD. ``numbers=False`` skips round, gold and remaining slots (the caller
    already knows them) and reads only the shop: cards, level box, prices."""
    collapsed = is_collapsed(boxes)
    rnd = ocr.read_number(image, P.ROUND, 1, 30) if numbers else None
    gold = ocr.read_number(image, P.GOLD, 0, 99) if numbers else None
    slots = read_slots(image, ocr, boxes, collapsed) if numbers else None
    level_x = maxed = upgrade_cost = refresh_cost = None
    cards: list[ShopCard] = []
    if not collapsed:
        level = find(boxes, "已满级", "满级", "升级", region=(0, 960, 1700, 1020))
        level_x = int(level.x) if level else None
        maxed = bool(level and "满级" in level.compact)
        if level_x is not None and not maxed:
            upgrade_cost = ocr.read_number(image, (level_x - 24, 780, level_x + 24, 822), 0, 20)
        shop_level = 6 if maxed else read_shop_level(image, ocr, level_x)
        refresh_text = find(boxes, "FREE", region=(1700, 610, 1900, 680))
        refresh_cost = 0 if refresh_text else ocr.read_number(image, P.REFRESH_COST, 0, 9)
        cards = read_cards(image, ocr, boxes, level_x)
    else:
        shop_level = None
    return PrepState(rnd, gold, slots, level_x, bool(maxed), upgrade_cost, refresh_cost, collapsed, cards,
                     shop_level)


def read_level_box(image: np.ndarray, ocr: OcrEngine) -> tuple[int | None, bool, int | None]:
    """(x of the 升级 box, 已满级, next upgrade price) from the strip above the cards only."""
    level = find(ocr.read(image, (0, 960, 1700, 1020)), "已满级", "满级", "升级")
    if level is None:
        return None, False, None
    x, maxed = int(level.x), "满级" in level.compact
    cost = None if maxed else ocr.read_number(image, (x - 24, 780, x + 24, 822), 0, 20)
    return x, maxed, cost


def read_shop_level(image: np.ndarray, ocr: OcrEngine, level_x: int | None) -> int | None:
    """The roman numeral under LEVEL. A lone "I" is not recognised reliably, so only a
    confident reading counts; the tactic falls back to counting its own upgrades."""
    if level_x is None:
        return None
    text, score = ocr.read_line(image, (level_x - 45, 872, level_x + 45, 940))
    if score < 0.8 or not text.strip() or any(ch not in "IVⅠⅡⅢⅣⅤⅥ" for ch in text.strip().upper()):
        return None
    return parse_tier(text) or None
