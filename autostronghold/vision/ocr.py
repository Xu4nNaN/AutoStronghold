"""Text recognition with RapidOCR (Apache-2.0) on onnxruntime, CPU or DirectML GPU."""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Sequence

import cv2
import numpy as np

from ..geometry import Box


@dataclass(frozen=True)
class TextBox:
    """One recognised text line; ``x, y`` is the centre in full-screen coordinates."""

    x: float
    y: float
    text: str
    score: float = 1.0
    box: Box = (0, 0, 0, 0)

    @property
    def compact(self) -> str:
        return self.text.replace(" ", "")


def normalize_digits(text: str) -> str:
    """'①', full-width and other Unicode digits → ASCII; other characters unchanged."""
    out = []
    for ch in text:
        if ch.isdigit():
            try:
                out.append(str(unicodedata.digit(ch)))
                continue
            except (TypeError, ValueError):
                pass
        out.append(ch)
    return "".join(out)


# Letters the recogniser returns for digits in the game's number font ("0" → "O").
_DIGIT_LOOKALIKES = str.maketrans({"O": "0", "o": "0", "〇": "0", "D": "0", "l": "1", "I": "1", "|": "1"})


def number_text(text: str) -> str:
    """A field that holds only a number: map look-alike letters to digits."""
    t = normalize_digits(text.strip())
    return t.translate(_DIGIT_LOOKALIKES) if t and len(t) <= 3 else t


def digits_of(text: str) -> str:
    return "".join(ch for ch in normalize_digits(text) if ch.isdigit())


def parse_int(text: str) -> int | None:
    d = digits_of(text)
    return int(d) if d else None


class OcrEngine:
    """Thin wrapper that returns :class:`TextBox` lists in screen coordinates."""

    PAD = 32     # the detector misses text touching the crop border
    SMALL = 96   # crops shorter than this are enlarged to this height before detection

    def __init__(self, use_gpu: bool, threads: int | None = None) -> None:
        from rapidocr_onnxruntime import RapidOCR

        if threads is None:
            # The original tool let onnxruntime use every core; a few threads are enough
            # for small crops and keep the PC responsive.
            threads = max(2, min(4, (os.cpu_count() or 4) // 2))
        self.use_gpu = use_gpu
        # Never upscale for detection: RapidOCR's default ("min" side 736) blows a short
        # crop up to 736 px tall, which made reading a screen region slower than the whole
        # screen. "max 1280" leaves crops at their size and shrinks only full screens.
        self.engine = RapidOCR(use_cls=False, intra_op_num_threads=threads, inter_op_num_threads=1,
                               det_limit_type="max", det_limit_side_len=1280,
                               det_use_dml=use_gpu, rec_use_dml=use_gpu, cls_use_dml=False)

    def providers(self) -> list[str]:
        try:
            return list(self.engine.text_det.infer.session.get_providers())
        except AttributeError:
            return []

    def on_gpu(self) -> bool:
        return bool(self.providers()) and self.providers()[0] == "DmlExecutionProvider"

    def close(self) -> None:
        """Drop the ONNX Runtime sessions (and their GPU memory); the engine is not used afterwards."""
        self.engine = None

    def read(self, image: np.ndarray, box: Box | None = None) -> list[TextBox]:
        """Detect and recognise all text in ``image`` (optionally only inside ``box``)."""
        ox = oy = 0
        scale = 1.0
        if box is not None:
            x1, y1, x2, y2 = box
            crop = image[y1:y2, x1:x2]
            if crop.size == 0:
                return []
            if crop.shape[0] < self.SMALL:
                # Tiny crops (a single digit in a circle) are enlarged for the detector.
                scale = self.SMALL / crop.shape[0]
                crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            image = cv2.copyMakeBorder(crop, self.PAD, self.PAD, self.PAD, self.PAD, cv2.BORDER_REPLICATE)
            ox, oy = x1, y1
        result, _ = self.engine(image)
        out: list[TextBox] = []
        pad = self.PAD if box is not None else 0
        for quad, text, score in result or []:
            xs = [(p[0] - pad) / scale for p in quad]
            ys = [(p[1] - pad) / scale for p in quad]
            bx = (int(min(xs) + ox), int(min(ys) + oy), int(max(xs) + ox), int(max(ys) + oy))
            out.append(TextBox(sum(xs) / 4 + ox, sum(ys) / 4 + oy, str(text), float(score), bx))
        return out

    def read_line(self, image: np.ndarray, box: Box) -> tuple[str, float]:
        """Recognise a single, already located line (no detection step)."""
        x1, y1, x2, y2 = box
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            return "", 0.0
        try:
            result, _ = self.engine(crop, use_det=False, use_cls=False, use_rec=True)
        except Exception:
            return "", 0.0
        if not result:
            return "", 0.0
        return str(result[0][0]), float(result[0][1])

    def read_number(self, image: np.ndarray, box: Box, lo: int = 0, hi: int = 999) -> int | None:
        """A number at a fixed place; tries recognition only, then detection + recognition."""
        text, score = self.read_line(image, box)
        clean = number_text(text)
        # Only trust a recognition that is purely digits: "1#" for "11" must not become 1.
        if clean and clean.isdigit() and score >= 0.45 and lo <= int(clean) <= hi:
            return int(clean)
        best = ""
        for t in self.read(image, box):
            d = digits_of(t.text)
            if len(d) > len(best):
                best = d
        if best and lo <= int(best) <= hi:
            return int(best)
        return None


# --- helpers over TextBox lists ------------------------------------------------------
def joined(boxes: Iterable[TextBox]) -> str:
    return "".join(b.compact for b in boxes)


def find(boxes: Sequence[TextBox], *keywords: str, region: Box | None = None) -> TextBox | None:
    """First box whose text contains any keyword (optionally centred inside ``region``)."""
    for b in boxes:
        if region and not (region[0] <= b.x <= region[2] and region[1] <= b.y <= region[3]):
            continue
        if any(k in b.compact for k in keywords):
            return b
    return None


def has(boxes: Sequence[TextBox], *keywords: str, region: Box | None = None) -> bool:
    return find(boxes, *keywords, region=region) is not None


def in_region(boxes: Sequence[TextBox], region: Box) -> list[TextBox]:
    return [b for b in boxes if region[0] <= b.x <= region[2] and region[1] <= b.y <= region[3]]


_CJK = re.compile(r"[一-鿿]")


def has_cjk(text: str) -> bool:
    return bool(_CJK.search(text))
