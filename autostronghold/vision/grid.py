"""Strategy grid (2/3 选择策略): find cards, read their badges, fingerprint them.

Detection is purely visual so one screenshot is enough to know every visible card:

* **Cards** have a bright top border spanning the whole card width with a dark gap
  above it. Looking for that line per column also handles rows with fewer than four
  cards and ignores the section headers (泛用型策略 / 盟约型策略), whose text never
  covers a full card width.
* **Badges** sit in the card's top-right corner: a gold frame (3 clears) or a white/teal
  frame (6 clears, "彩标"). A badge must match the frame template *and* have the right
  colours, so teal-tinted portraits are not mistaken for badges.
* **Signatures** are small normalised thumbnails of the portrait. They identify a card
  across scroll positions, so a row seen on two pages is counted once.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache

import cv2
import numpy as np

from ..geometry import StrategyGrid as G
from ..paths import resource


class Badge(str, Enum):
    NONE = "none"
    GOLD = "gold"     # 金标: cleared 3 times
    COLOR = "color"   # 彩标: cleared 6 times

    @property
    def label(self) -> str:
        return {"none": "无角标", "gold": "金标", "color": "彩标"}[self.value]


@dataclass
class Card:
    column: int          # 0..3, left to right
    x: int               # card centre x
    top: int             # y of the top border
    badge: Badge
    signature: np.ndarray | None

    @property
    def tap_point(self) -> tuple[int, int]:
        return self.x, min(self.top + G.CARD_HEIGHT // 2, G.VIEW_BOTTOM - 30)

    @property
    def right(self) -> int:
        return self.x + G.CARD_HALF_WIDTH


LINE_STRENGTH = 8      # a border's dimmer pixels are this much brighter than the gap above it
LINE_FLOOR = 22        # and the border is at least this bright (20th percentile over the card width)
BORDER_PAIR = (12, 45)  # a bottom border is followed by the next card's top border this far below
CARD_SPAN = (178, 194)  # a card's bottom border lies this far below its top border
SIG_SIZE = (24, 24)    # signature thumbnail (w, h)
SIG_TOP, SIG_BOTTOM = 35, 155   # signature crop, relative to the card top
SCROLLBAR_X = {"shifted": (1420, 1442), "unshifted": (1818, 1842)}


def _row_levels(gray: np.ndarray, x: int) -> tuple[np.ndarray, np.ndarray]:
    """Per row: the 20th percentile (a full-width line lifts it) and the median."""
    band = gray[:, x - G.CARD_HALF_WIDTH + 4: x + G.CARD_HALF_WIDTH - 4].astype(np.float32)
    low, mid = np.percentile(band, [20, 50], axis=1)
    return low, mid


def _border_lines(low: np.ndarray, mid: np.ndarray) -> list[int]:
    """Rows that are bright lines spanning the card width with a dark gap right above.

    The test is relative (the line's dimmer pixels against the gap's median), so it
    holds on the dimmer right-hand columns and while a card is selected; a portrait's
    own horizontal edges have no uniformly dark band above them and are not lines.
    """
    lines: list[int] = []
    for y in range(G.VIEW_TOP + 10, G.VIEW_BOTTOM - 20):   # skip the list's clipping edge
        gap = max(mid[y - 8], mid[y - 6])
        if low[y] >= LINE_FLOOR and low[y] - gap >= LINE_STRENGTH and low[y + 2] - gap >= LINE_STRENGTH - 2:
            if lines and y - lines[-1] <= 8:
                continue                     # same (≈6 px thick) border, keep its first row
            lines.append(y)
    return lines


def card_tops(gray: np.ndarray, x: int) -> list[int]:
    """Top-border y of every card in the column centred at ``x``.

    Card borders are thin bright lines. The test is relative to the rows just above and
    below, so it works on the dimmer right-hand columns and while a card is selected.
    A top border has the card's bottom border about 186 px below it (unless the card runs
    off the bottom of the view). A line with a top border about 186 px above it, or with
    the next card's top border right below it, is a bottom border.
    """
    low, mid = _row_levels(gray, x)
    lines = _border_lines(low, mid)
    tops: list[int] = []
    for y in lines:
        if any(BORDER_PAIR[0] <= other - y <= BORDER_PAIR[1] for other in lines):
            continue                      # bottom border of the card above
        if any(CARD_SPAN[0] <= y - other <= CARD_SPAN[1] for other in lines):
            continue                      # bottom border: its card's top border is just above
        closed = any(CARD_SPAN[0] <= other - y <= CARD_SPAN[1] for other in lines)
        if not closed and y + CARD_SPAN[0] < G.VIEW_BOTTOM - 20:
            continue                      # no card body below: a bottom border or a header line
        if tops and y - tops[-1] < G.CARD_HEIGHT - 30:
            continue                      # a line inside the card (portrait detail)
        tops.append(y)
    return tops


def _scrollbar_length(gray: np.ndarray, x1: int, x2: int) -> int:
    column = gray[G.VIEW_TOP:G.VIEW_BOTTOM, x1:x2].max(axis=1)
    best = run = 0
    for v in column:
        run = run + 1 if v > 90 else 0
        best = max(best, run)
    return best


def detect_layout(gray: np.ndarray) -> tuple[int, ...] | None:
    """Column centres of the visible grid, or None when no strategy list is showing.

    The list's scrollbar sits at x≈1830 before any card is tapped and at x≈1430 after
    the grid shifts left, which is a far steadier cue than counting cards.
    """
    shifted = _scrollbar_length(gray, *SCROLLBAR_X["shifted"])
    unshifted = _scrollbar_length(gray, *SCROLLBAR_X["unshifted"])
    if max(shifted, unshifted) >= 120:
        return G.COLUMNS_SHIFTED if shifted > unshifted else G.COLUMNS_UNSHIFTED
    best, best_n = None, 0
    for cols in (G.COLUMNS_SHIFTED, G.COLUMNS_UNSHIFTED):
        n = sum(len(card_tops(gray, x)) for x in cols)
        if n > best_n:
            best, best_n = cols, n
    return best


@lru_cache(maxsize=1)
def _templates() -> dict[Badge, np.ndarray]:
    out = {}
    for badge in (Badge.GOLD, Badge.COLOR):
        data = np.fromfile(str(resource("templates", f"badge_{badge.value}.png")), np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
        if img is not None:
            out[badge] = img
    return out


def _colour_shares(hsv: np.ndarray) -> tuple[float, float, float]:
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    gold = float(((h >= 5) & (h <= 30) & (s >= 120) & (v >= 150)).mean())
    white = float(((s < 70) & (v > 200)).mean())
    teal = float(((h >= 75) & (h <= 100) & (s >= 60) & (v >= 120)).mean())
    return gold, white, teal


def badge_of(image: np.ndarray, x: int, top: int) -> Badge:
    right = x + G.CARD_HALF_WIDTH
    bw, bh = G.BADGE_SIZE
    x1, y1 = right - G.BADGE_FROM_RIGHT, top + 4
    m = 6  # search margin for the template
    region = image[max(0, y1 - m): y1 + bh + m, max(0, x1 - m): x1 + bw + m]
    if region.shape[0] < bh or region.shape[1] < bw:
        return Badge.NONE
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    # The frame shape decides whether there is a badge; its colour decides which one.
    best_score, best_loc = 0.0, (m, m)
    for tpl in _templates().values():
        if gray.shape[0] < tpl.shape[0] or gray.shape[1] < tpl.shape[1]:
            continue
        res = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        if score > best_score:
            best_score, best_loc = float(score), loc
    if best_score < 0.55:
        return Badge.NONE
    lx, ly = best_loc
    hsv = cv2.cvtColor(region[ly:ly + bh, lx:lx + bw], cv2.COLOR_BGR2HSV)
    gold, white, teal = _colour_shares(hsv)
    if gold >= 0.18:
        return Badge.GOLD
    if white >= 0.06 and teal >= 0.12:
        return Badge.COLOR
    return Badge.NONE


def signature(image: np.ndarray, x: int, top: int) -> np.ndarray | None:
    """Normalised thumbnail of the portrait's centre, or None when the card is cut off.

    The crop avoids the card frame, the "STRAT" caption and the badge, which look alike
    on every card; what remains is the face, which differs between strategies.
    """
    y1, y2 = top + SIG_TOP, top + SIG_BOTTOM
    if y2 > G.VIEW_BOTTOM:
        return None
    crop = cv2.cvtColor(image[y1:y2, x - 70: x + 50], cv2.COLOR_BGR2GRAY)
    thumb = cv2.resize(crop, SIG_SIZE, interpolation=cv2.INTER_AREA).astype(np.float32)
    thumb -= thumb.mean()
    norm = float(np.linalg.norm(thumb))
    return thumb / norm if norm > 1e-3 else None


def same_card(a: np.ndarray | None, b: np.ndarray | None, threshold: float = 0.95) -> bool:
    return a is not None and b is not None and float((a * b).sum()) >= threshold


def visible_cards(image: np.ndarray, columns: tuple[int, ...] | None = None) -> list[Card]:
    """Cards whose badge corner is fully visible, in reading order."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    columns = columns or detect_layout(gray)
    if not columns:
        return []
    found: dict[int, list[tuple[int, int]]] = {}   # row top -> [(column, top)]
    for col, x in enumerate(columns):
        for top in card_tops(gray, x):
            if top + 4 + G.BADGE_SIZE[1] > G.VIEW_BOTTOM:
                continue
            row = next((r for r in found if abs(r - top) <= 15), top)
            found.setdefault(row, []).append((col, top))
    cards: list[Card] = []
    for row, members in found.items():
        # Rows are filled from the left, so a hole before the last card is a card whose
        # border is hidden by the selection frame.
        present = {c for c, _ in members}
        for col in range(max(present) + 1):
            top = next((t for c, t in members if c == col), row)
            x = columns[col]
            cards.append(Card(col, x, top, badge_of(image, x, top), signature(image, x, top)))
    # Rows from different columns are aligned; sort by row then column.
    cards.sort(key=lambda c: (round(c.top / 30), c.column))
    return cards


def list_moved(before: np.ndarray, after: np.ndarray) -> bool:
    """Whether the visible part of the list changed between two screenshots."""
    a = cv2.cvtColor(before[G.VIEW_TOP:G.VIEW_BOTTOM, 560:1420], cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(after[G.VIEW_TOP:G.VIEW_BOTTOM, 560:1420], cv2.COLOR_BGR2GRAY)
    return float(cv2.absdiff(a, b).mean()) > 4.0
