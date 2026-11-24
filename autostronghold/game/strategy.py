"""2/3 选择策略: scan the whole list, apply the feature's goal, pick and confirm."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from .. import log
from ..features.goals import BadgeGoal, Decision, StrategyEntry
from ..geometry import StrategyGrid as G
from ..vision import grid
from ..vision.grid import Badge, Card
from ..vision.ocr import find, has_cjk, normalize_digits
from .context import GameContext

MAX_PAGES = 15
MAX_CORRECTIONS = 4


@dataclass
class Seen:
    entry: StrategyEntry
    signature: np.ndarray


@dataclass
class PanelInfo:
    opened: bool
    clears: int | None   # None: "通过" visible but the number could not be read
    name: str = ""


@dataclass
class Selection:
    decision: Decision
    strategy: str = ""                     # name shown on the panel of the picked card
    entries: list[StrategyEntry] = field(default_factory=list)


_CLEARS = re.compile(r"通过模?拟?(\d+)次")   # applied to text without spaces


def read_panel(boxes) -> PanelInfo:
    opened = find(boxes, "初始生命值", "初始生命") is not None
    texts = [b for b in boxes if b.y < 350]
    clears: int | None = 0
    for i, b in enumerate(texts):
        if "通过" not in b.compact:
            continue
        joined = normalize_digits(b.compact)
        if i + 1 < len(texts):  # the count is sometimes recognised as a separate line
            joined += normalize_digits(texts[i + 1].compact)
        m = _CLEARS.search(joined)
        clears = int(m.group(1)) if m else None
        break
    names = [b.compact for b in boxes if 540 <= b.y <= 620 and b.x > 1440 and has_cjk(b.compact)
             and "生命" not in b.compact]
    return PanelInfo(opened, clears, names[0] if names else "")


class StrategySelector:
    def __init__(self, ctx: GameContext, goal: BadgeGoal):
        self.ctx = ctx
        self.goal = goal
        self.overrides: list[tuple[np.ndarray, Badge]] = []   # grid misreads corrected by the panel

    # --- scanning ----------------------------------------------------------------
    def _badge(self, card: Card) -> Badge:
        for sig, badge in self.overrides:
            if grid.same_card(sig, card.signature):
                return badge
        return card.badge

    def _scroll(self, down: bool = True) -> None:
        x, y1, y2 = G.SCROLL_X, G.SCROLL_FROM_Y, G.SCROLL_TO_Y
        if down:
            self.ctx.device.swipe(x, y1, x, y2, duration=0.6, hold=0.4, wait=0.7)
        else:
            self.ctx.device.swipe(x, y2, x, y1, duration=0.6, hold=0.4, wait=0.7)

    def _scroll_and_look(self, image: np.ndarray) -> np.ndarray | None:
        """Scroll down; None when the list is at its end. A swipe is occasionally not
        taken by the game, so the end is only accepted after a second still swipe."""
        for _ in range(2):
            self._scroll(down=True)
            after = self.ctx.device.screenshot()
            if grid.list_moved(image, after):
                return after
        return None

    def _scroll_to_top(self) -> np.ndarray:
        image = self.ctx.device.screenshot()
        for _ in range(MAX_PAGES):
            self._scroll(down=False)
            after = self.ctx.device.screenshot()
            if not grid.list_moved(image, after):
                return after
            image = after
        return image

    def scan(self, stop=None) -> tuple[list[Seen], bool, np.ndarray]:
        """Read the list page by page; returns (seen cards, reached the end, last image).

        ``stop(entries)`` ends the scan as soon as the cards read so far decide (see
        :meth:`BadgeGoal.settled`); ``complete`` is then False, as it is when the page limit
        was hit before the end of the list.
        """
        image = self.ctx.device.screenshot()
        seen: list[Seen] = []
        complete = False
        for page in range(MAX_PAGES):
            new = 0
            for card in grid.visible_cards(image):
                if card.signature is None:
                    continue   # cut off at the bottom; fully visible on the next page
                if any(grid.same_card(s.signature, card.signature) for s in seen):
                    continue
                index = len(seen) + 1
                seen.append(Seen(StrategyEntry(index, self._badge(card), f"第 {index} 个策略"), card.signature))
                new += 1
            log.debug("策略列表第 %d 页：新增 %d 个", page + 1, new)
            if stop is not None and stop([s.entry for s in seen]):
                break
            after = self._scroll_and_look(image)
            if after is None:
                complete = True
                break
            image = after
        return seen, complete, image

    def _locate(self, target: Seen, image: np.ndarray) -> Card | None:
        for _ in range(MAX_PAGES):
            for card in grid.visible_cards(image):
                if grid.same_card(card.signature, target.signature):
                    return card
            self._scroll(down=False)
            after = self.ctx.device.screenshot()
            if not grid.list_moved(image, after):
                break
            image = after
        return None

    # --- the whole step ----------------------------------------------------------
    def run(self) -> Selection:
        for attempt in range(MAX_CORRECTIONS + 1):
            if attempt:
                self._scroll_to_top()
            seen, complete, image = self.scan(stop=self.goal.settled)
            entries = [s.entry for s in seen]
            if not entries:
                log.snapshot(image, "strategy_no_cards")
                raise_no_cards()
            decision = self.goal.decide(entries, complete)
            if complete:
                note = "（已扫描整个列表）"
            elif self.goal.settled(entries):
                note = "（足以判断，未扫描其余策略）"
            else:
                note = "（未能滑到列表末尾，已达翻页上限）"
            log.info("策略扫描：识别 %d 个策略，其中已有%s %d 个%s", decision.total, self.goal.wanted_label,
                     decision.badged, note)
            if decision.done or decision.pick is None:
                if not decision.done:  # scanned everything without an answer: treat as done
                    decision = self.goal.decide(entries, True)
                return Selection(decision, entries=entries)
            target = next(s for s in seen if s.entry is decision.pick)
            card = self._locate(target, image)
            if card is None:
                log.warn("找不到要选择的策略卡片，重新扫描")
                continue
            self.ctx.tap(*card.tap_point, wait=1.0)
            panel = self._read_panel()
            if panel.opened and panel.clears is not None and panel.clears >= self.goal.clears_needed:
                badge = Badge.COLOR if panel.clears >= 6 else Badge.GOLD
                log.info("%s 实际已通过 %d 次（角标识别遗漏），视为已有%s，继续查找",
                         panel.name or decision.pick.label, panel.clears, badge.label)
                self.overrides.append((target.signature, badge))
                continue
            name = panel.name or decision.pick.label
            log.info("选择策略：%s（已通过 %s 次）", name, panel.clears if panel.clears is not None else "?")
            self._confirm()
            return Selection(decision, name, entries)
        raise_no_cards("角标识别与策略面板多次不一致")

    def _read_panel(self) -> PanelInfo:
        info = PanelInfo(False, None)
        for _ in range(3):  # the panel slides in; read again if it is not there yet
            info = read_panel(self.ctx.read(G.PANEL))
            if info.opened and info.clears is not None:
                return info
            self.ctx.sleep(0.6)
        return info

    def _confirm(self) -> None:
        screen = self.ctx.look()
        hit = screen.find("确认选择")
        self.ctx.tap(*(hit.x, hit.y) if hit else G.CONFIRM, wait=2.0)


def raise_no_cards(detail: str = "没有识别到任何策略卡片") -> None:
    from ..errors import StopRun

    raise StopRun(f"选择策略失败：{detail}。截图已保存到 logs 文件夹。",
                  "确认游戏使用默认主题、分辨率为 1920x1080（16:9），然后重新运行。")
