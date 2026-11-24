"""The polygon offset RapidOCR needs from ``pyclipper``, for the Android app.

pyclipper has no Android build. RapidOCR only grows each detected text box by a distance
with round joins (``PyclipperOffset`` + ``JT_ROUND`` + ``ET_CLOSEDPOLYGON``); Shapely's
round-join buffer gives the same outline, and RapidOCR then takes its minimum-area
rectangle, so the exact vertex count does not matter.
"""
from __future__ import annotations

import math

import numpy as np
from shapely.geometry import Polygon

JT_SQUARE, JT_ROUND, JT_MITER = 0, 1, 2
ET_CLOSEDPOLYGON = 0
_JOIN_STYLE = {JT_ROUND: 1, JT_MITER: 2, JT_SQUARE: 3}   # Shapely: round, mitre, bevel


class PyclipperOffset:
    def __init__(self, miter_limit: float = 2.0, arc_tolerance: float = 0.25) -> None:
        self.miter_limit = miter_limit
        self.arc_tolerance = arc_tolerance
        self._paths: list[tuple[np.ndarray, int]] = []

    def AddPath(self, path, join_type: int, end_type: int) -> None:
        # Clipper works on integer points; pyclipper truncates the coordinates it is given.
        self._paths.append((np.trunc(np.asarray(path, np.float64).reshape(-1, 2)), join_type))

    def Execute(self, delta: float) -> list[list[list[int]]]:
        out = []
        # As many segments per round corner as Clipper uses for this arc tolerance.
        tolerance = min(abs(delta), self.arc_tolerance)
        steps = math.pi / math.acos(1 - tolerance / abs(delta)) if delta else 4
        quarter = max(1, round(steps / 4))
        for path, join in self._paths:
            grown = Polygon(path).buffer(delta, quarter, join_style=_JOIN_STYLE.get(join, 1),
                                         mitre_limit=self.miter_limit)
            for poly in getattr(grown, "geoms", [grown]):
                if not poly.is_empty:
                    out.append(np.round(np.asarray(poly.exterior.coords)[:-1]).astype(int).tolist())
        return out
