"""Operators waiting on the bench (备战席, the wooden plank) in the normal view."""
from __future__ import annotations

import numpy as np
import cv2

PLANK_BAND = (690, 745)   # where the operators' bodies cross the plank
PICK_Y = 705              # touch here to pick one up (higher up hits the scenery behind)


# The bench has ten fixed slots (x of each operator's body in the normal view).
SLOT_X = tuple(round(290 + 121.5 * i) for i in range(10))
SLOT_HALF = 25
# Every unit on the bench (operator or summon) has a dark tier badge (Ⅰ…Ⅵ) above-left of
# its slot; a summon stack has a small body that hardly covers the plank, but the badge.
BADGE_DX = (-60, -24)
BADGE_Y = (578, 612)
MAX_SHIFT = 90            # the leader round's camera shows the bench ~57 px further right
# While a unit is held the camera tilts into the drag view, where the bench is lower and
# wider: normal x 1384 is drag x ~1560, and a release at drag x 900 lands in slot 898.
DRAG_BENCH_Y = 900
DRAG_CENTRE_X = 890       # the x that is the same in both views
DRAG_WIDEN = 1.36


def drag_view_x(x: int) -> int:
    """Where the bench slot at normal-view ``x`` is in the drag view (to release a unit on it)."""
    return round(DRAG_CENTRE_X + (x - DRAG_CENTRE_X) * DRAG_WIDEN)


def _plank_taken(image: np.ndarray, x: int) -> bool:
    y1, y2 = PLANK_BAND
    crop = image[y1:y2, max(0, x - SLOT_HALF): x + SLOT_HALF]
    if crop.size == 0:
        return False
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).astype(np.int32)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    plank = (h >= 8) & (h <= 28) & (s >= 60) & (v >= 140)
    return (~plank).mean() > 0.35


def _badge(image: np.ndarray, x: int) -> float:
    crop = image[BADGE_Y[0]:BADGE_Y[1], max(0, x + BADGE_DX[0]): x + BADGE_DX[1]]
    if crop.size == 0:
        return 0.0
    return float((cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[..., 2] < 70).mean())


def bench_shift(image: np.ndarray) -> int:
    """Horizontal offset of the bench on screen (0 normally; the leader round's camera moves it),
    found from where the badges line up. 0 when no badge is shown."""
    best, score = 0, 0
    for dx in sorted(range(-MAX_SHIFT, MAX_SHIFT + 1, 3), key=abs):
        n = sum(_badge(image, x + dx) >= 0.45 for x in SLOT_X)
        if n > score:
            best, score = dx, n
    return best


def bench_positions(image: np.ndarray, shift: int | None = None) -> list[tuple[int, int]]:
    """Occupied bench slots, left to right, as slot x (``SLOT_X``; add ``bench_shift`` to touch).

    A slot is taken when its badge shows or the plank behind it is covered. (A toast drawn
    over the plank can make an empty slot look taken; picking it up then finds nothing.)
    """
    dx = bench_shift(image) if shift is None else shift
    return [(x, PICK_Y) for x in SLOT_X if _badge(image, x + dx) >= 0.45 or _plank_taken(image, x + dx)]
