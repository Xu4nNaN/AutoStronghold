"""道具补给 / 战术决策: locate the three option boxes."""
from __future__ import annotations

import cv2
import numpy as np

from ..geometry import Event

# Option boxes are large rectangles with a thin light frame, side by side in the middle
# band of the screen (about 430 x 360 px each at 1920x1080).
BOX_W = (360, 500)
BOX_H = (300, 450)
SEARCH = (200, 280, 1760, 820)   # x1, y1, x2, y2


def option_centres(image: np.ndarray) -> list[tuple[int, int]]:
    """Centres of the option boxes, left to right (empty when none are found).

    The light frame is isolated by brightness, closed into solid outlines and found as
    external contours; only box-sized rectangles count.
    """
    x1, y1, x2, y2 = SEARCH
    gray = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    _, frame = cv2.threshold(gray, 165, 255, cv2.THRESH_BINARY)
    frame = cv2.morphologyEx(frame, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    contours, _ = cv2.findContours(frame, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    centres = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if BOX_W[0] <= w <= BOX_W[1] and BOX_H[0] <= h <= BOX_H[1]:
            centres.append((x1 + x + w // 2, y1 + y + h // 2))
    centres.sort()
    # A selected box grows and overlaps its "确认选择" button; keep one centre per box.
    merged: list[tuple[int, int]] = []
    for c in centres:
        if merged and abs(c[0] - merged[-1][0]) < BOX_W[0] // 2:
            continue
        merged.append(c)
    return merged


def middle_option(image: np.ndarray) -> tuple[int, int]:
    boxes = option_centres(image)
    return boxes[1] if len(boxes) == 3 else Event.MIDDLE_OPTION
