"""休整期 operations: the concrete taps and drags behind :class:`tactics.base.PrepActions`."""
from __future__ import annotations

from dataclasses import replace
from typing import Callable, Sequence

import cv2
import numpy as np

from .. import log
from ..geometry import Prep as P
from ..vision.hud import PrepState, ShopCard, read_level_box, read_prep, tier_in_box
from ..vision.bench import DRAG_BENCH_Y, PICK_Y, SLOT_X, bench_positions, bench_shift, drag_view_x
from ..vision.names import Names, clean
from ..vision.ocr import find, has_cjk
from .board import BoardState, Cell, Layout, Unit, is_green
from .context import GameContext
from .rules import BENCH_SIZE, MAX_SHOP_LEVEL, REFRESH_PRICE, SELL_PRICE, SHOP_SLOTS, merges
from .screens import Kind, Screen

OPERATOR_TABS = ("特质", "天赋", "特性")
MAX_SLOT_SEARCH = 3    # slots to the left tried when a recorded operator is not where expected
READ_TRIES = 2         # reads of a slot that cannot be picked up, per game (one per round)


def same_name(a: str, b: str) -> bool:
    """Two reads of an operator's name (each already matched to a known name when possible)."""
    return clean(a) == clean(b)


def not_operator(unit: Unit) -> bool:
    """A bench record that is never deployed, sold or surveyed."""
    return unit.equipment or unit.summon or unit.unknown


def drag_name(boxes) -> str:
    """Operator name in the info panel shown while an operator is held."""
    for b in boxes:
        text = b.compact
        if text and has_cjk(text) and "LV" not in text.upper():
            return text
    return ""


def new_bench_position(before: np.ndarray, after: np.ndarray, ignore: int | None = None,
                       fallback: bool = True) -> tuple[int, int] | None:
    """Where a newly arrived operator stands on the bench.

    ``ignore``: the slot an operator left in between (moved to the field); it counts as empty
    in ``before``, and only occupied slots are compared (the picture there changed anyway).
    ``fallback=False``: only an occupied-slot change counts, not a changed picture (a toast
    such as 整备区已满 drawn over the bench changes the picture too)."""
    old = [x for x, _ in bench_positions(before) if ignore is None or abs(x - ignore) > 30]
    now = bench_positions(after)
    for x, y in now:
        if all(abs(x - o) > 30 for o in old):
            return x, y
    if ignore is not None or not fallback:
        return None
    changed = new_object_at(before, after)
    if changed is None:
        return None
    x = min(SLOT_X, key=lambda s: abs(s - (changed[0] - bench_shift(after))))   # the slot the change is in
    if any(abs(x - o) <= 30 for o in old) and all(abs(x - n) > 30 for n, _ in now):
        return None   # an operator left that slot (copies merged into an elite): nothing arrived
    return x, PICK_Y


def new_object_at(before: np.ndarray, after: np.ndarray, box=P.BENCH, min_area: int = 1500) -> tuple[int, int] | None:
    """Centre of the largest region that changed inside ``box`` (e.g. a new bench operator)."""
    x1, y1, x2, y2 = box
    diff = cv2.cvtColor(cv2.absdiff(before[y1:y2, x1:x2], after[y1:y2, x1:x2]), cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(diff, 40, 255, cv2.THRESH_BINARY)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    n, _, stats, centres = cv2.connectedComponentsWithStats(mask)
    if n <= 1:
        return None
    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    if stats[k, cv2.CC_STAT_AREA] < min_area:
        return None
    return int(centres[k][0]) + x1, int(centres[k][1]) + y1


def moved(x0: int | None, x1: int | None) -> bool:
    """The LEVEL card moved to another slot (slots are ~240 px apart; reads jitter by a few px)."""
    return x0 is not None and x1 is not None and abs(x1 - x0) > 100


def upgraded(before: PrepState, after: PrepState) -> bool | None:
    """Did the shop level go up? None when the reads cannot tell (a value was not read).

    Evidence: 已满级 appeared, the gold went down, the next level's price changed, or the
    LEVEL card moved (it does when the shop gains a slot). A box that was not found in one
    of the two reads is no evidence: that is how false upgrades were counted before."""
    if after.maxed:
        return True
    if before.gold is not None and after.gold is not None:
        if after.gold < before.gold:
            return True
    if before.upgrade_cost is not None and after.upgrade_cost is not None and after.upgrade_cost != before.upgrade_cost:
        return True
    if moved(before.level_x, after.level_x):
        return True
    if before.gold is not None and after.gold == before.gold and after.level_x is not None:
        return False
    return None


class PrepSession:
    """One preparation phase. Implements :class:`tactics.base.PrepActions`.

    Speed: the HUD is read once and then inferred from the rules (see "reading" below),
    and the bench is kept as a record (slot → operator) that
    is updated by every buy, deploy, swap and sale, so known operators are never picked up
    again just to read their name. The field is a record too (cell → operator, kept for the
    whole game): a free cell is taken from it, not from the green glow on screen.
    """

    def __init__(self, ctx: GameContext, layout: Layout, board: BoardState):
        self.ctx = ctx
        self.layout = layout
        self.board = board
        self._st: PrepState | None = None   # the HUD as known (read once, then inferred)
        self.refusal = ""      # why the last purchase was refused
        self.deploy_failure = ""   # why the last deploy() failed: "no_room", "drop" or "missing"
        self.names = Names.load()
        self._finger: tuple[int, int] = P.HOLD_CANCEL   # where a held operator is now
        self._dx = 0   # the bench's horizontal offset on screen (the leader round's camera moves it)
        self._tried: set[int] = set()   # bench slots already read in this phase

    # --- reading -----------------------------------------------------------------
    # The HUD is read once at the start of the preparation phase. After that the state is
    # kept from the rules (game/rules.py): a purchase takes the card's price and empties its
    # slot, a sale adds 1, a deployment uses one of the remaining places, and so on. Only
    # what cannot be inferred is read again: the cards after a refresh or a merge (the free
    # reward cards) and the LEVEL box after an upgrade. An outcome that contradicts the
    # state (nothing arrived on the bench after a purchase …) makes the session read the
    # whole HUD again. Gold is checked against the screen once, before 准备就绪.
    def _read_hud(self, numbers: bool = True) -> PrepState:
        st = None
        for _ in range(3):
            image = self.ctx.device.screenshot()
            boxes = self.ctx.ocr.read(image, P.HUD_TEXT)
            st = read_prep(image, self.ctx.ocr, boxes, numbers=numbers)
            if st.collapsed:
                self.expand(boxes)
                continue
            break
        return st

    def state(self) -> PrepState:
        """The HUD as this session knows it (read once, then kept up to date; see above)."""
        if self._st is None:
            self._st = self._read_hud()
            self._st.level = self._st.level or self.board.shop_level
            self.board.shop_level = self._st.level
        return self._st

    def resync(self, why: str) -> PrepState:
        """The inferred state was contradicted: read the whole HUD again."""
        log.info("核对界面：%s", why)
        level = self._st.level if self._st else self.board.shop_level
        self._st = self._read_hud()
        self._st.level = self._st.level or level
        return self._st

    def _reread_shop(self) -> PrepState:
        """Cards, LEVEL box and prices again; round, gold and remaining places stay inferred."""
        st = self.state()
        fresh = self._read_hud(numbers=False)
        st.cards, st.level_x, st.maxed = fresh.cards, fresh.level_x, fresh.maxed
        st.upgrade_cost, st.refresh_cost = fresh.upgrade_cost, fresh.refresh_cost
        if fresh.level:
            st.level = fresh.level
        return st

    def _spend(self, amount: int | None) -> None:
        st = self.state()
        if st.gold is not None and amount:
            st.gold = max(0, st.gold + amount)

    def expand(self, boxes=None) -> None:
        """After 收起 the card area is hidden; tap 展开 to restore it."""
        hit = find(boxes or [], "展开", region=P.EXPAND_BOX)
        log.info("卡牌区被收起了，点「展开」还原")
        self.ctx.tap(*(hit.x, hit.y) if hit else (1777, 1010), wait=1.0)

    def _gold(self) -> int | None:
        return self.ctx.ocr.read_number(self.ctx.device.screenshot(), P.GOLD, 0, 99)

    # --- bench record -----------------------------------------------------------
    def _bench_unit(self, x: int) -> Unit | None:
        return next((u for u in self.board.bench if u.bench_xy and abs(u.bench_xy[0] - x) <= 30), None)

    def _record(self, unit: Unit, x: int) -> None:
        """``unit`` now waits in the bench slot at ``x``."""
        self.board.bench = [u for u in self.board.bench
                            if u is unit or not (u.bench_xy and abs(u.bench_xy[0] - x) <= 30)]
        unit.bench_xy = (x, PICK_Y)
        if unit not in self.board.bench:
            self.board.bench.append(unit)

    def _forget(self, unit: Unit) -> None:
        if unit in self.board.bench:
            self.board.bench.remove(unit)
        unit.bench_xy = None

    def _bench_positions(self) -> list[tuple[int, int]]:
        """Occupied slots on screen; drops records of slots that are now empty."""
        image = self.ctx.device.screenshot()
        self._dx = bench_shift(image)
        positions = bench_positions(image, self._dx)
        xs = [x for x, _ in positions]
        for u in list(self.board.bench):
            if not u.bench_xy or all(abs(u.bench_xy[0] - x) > 30 for x in xs):
                self._forget(u)
                self._vanished(u)
        return positions

    def _vanished(self, unit: Unit) -> None:
        """A recorded bench operator is gone though nobody sold it. When another copy is still
        owned, an operator that was given (a tactic, a gift on entering the phase …) completed
        three copies: they were promoted, and the copy that remains is the elite."""
        if not unit.name or unit.elite or unit.summon or unit.equipment:
            return
        rest = [u for u in self.board.units() + self.board.bench if u.name == unit.name and not u.elite]
        if rest:
            keep = next((u for u in rest if u in self.board.units()), rest[0])
            keep.elite = True
            log.info("整备区的 %s 不见了（没有出售），另有同名干员：判定为已晋升精锐", unit.describe())

    # --- shop --------------------------------------------------------------------
    def _level_box(self, st: PrepState) -> bool:
        """The 升级 box or its price was not read: read the strip again. When the box is still
        not found, its place follows from the shop level (the slots it has); the gold then
        tells whether a tap there upgraded. True when the place is such a guess."""
        for _ in range(2):
            image = self.ctx.device.screenshot()
            x, maxed, cost = read_level_box(image, self.ctx.ocr)
            if x is not None:
                st.level_x, st.maxed = x, maxed
                st.upgrade_cost = cost if cost is not None else st.upgrade_cost
                if maxed or cost is not None:
                    return False
            self.ctx.sleep(0.3)
        if st.level_x is not None:
            return False
        log.snapshot(image, "level_box_missing", limit=10)
        level = st.level or self.board.shop_level
        if not level:
            log.info("读不到「升级」框，商店等级也未知，本次不升级")
            return False
        st.level_x = P.LEVEL_X[SHOP_SLOTS[level]]
        log.info("读不到「升级」框，按商店 %d 级的位置（x=%d）点击", level, st.level_x)
        return True

    def _upgrade_result(self, before: PrepState) -> tuple[bool | None, PrepState]:
        after = replace(before, gold=None)
        ok = None
        for _ in range(3):   # an unread value proves nothing: read again before deciding
            image = self.ctx.device.screenshot()
            after.level_x, after.maxed, after.upgrade_cost = read_level_box(image, self.ctx.ocr)
            ok = upgraded(before, after)
            if ok is None:   # the box alone cannot tell: the gold can
                after.gold = self.ctx.ocr.read_number(image, P.GOLD, 0, 99)
                ok = upgraded(before, after)
            if ok is not None:
                break
            self.ctx.sleep(0.4)
        return ok, after

    def upgrade(self) -> bool:
        before = self.state()
        if before.maxed:
            return False
        guessed = False
        if before.level_x is None or before.upgrade_cost is None:
            guessed = self._level_box(before)
            if before.level_x is None or before.maxed:
                return False
            if guessed and before.gold is None:
                before.gold = self._gold()   # with a guessed place only the gold can tell
        if before.gold is not None and before.upgrade_cost is not None and before.gold < before.upgrade_cost:
            return False
        before = replace(before)
        # a guessed place is no evidence of the card moving: only gold, price and 已满级 count
        basis = replace(before, level_x=None) if guessed else before
        # One tap, then look. A second tap only when the first was certainly not taken: after
        # an upgrade that opens a slot the LEVEL card moves, and a blind second tap at the old
        # place hits whatever is there now.
        self.ctx.tap(before.level_x, P.UPGRADE_TAP_Y, wait=0.7)
        ok, after = self._upgrade_result(basis)
        if ok is False and not moved(basis.level_x, after.level_x):
            self.ctx.tap(before.level_x, P.UPGRADE_TAP_Y, wait=0.7)
            ok, after = self._upgrade_result(basis)
        st = self.state()
        if ok:
            st.gold = after.gold if after.gold is not None else (
                None if st.gold is None or before.upgrade_cost is None else st.gold - before.upgrade_cost)
            st.level = min(MAX_SHOP_LEVEL, st.level + 1) if st.level else None
            self.board.shop_level = st.level
            if st.gold is None:
                st.gold = self._gold()     # the price was not known: read what is left
            if guessed or moved(before.level_x, after.level_x):
                self._reread_shop()    # the shop gained a slot: the LEVEL card and the cards moved
            else:
                st.maxed, st.upgrade_cost = after.maxed, after.upgrade_cost
        log.info("升级商店：资金 %s → %s，%s%s", before.gold, st.gold,
                 "已满级" if st.maxed else f"下一级费用 {st.upgrade_cost}", "" if ok else "（没有升级）")
        return bool(ok)

    def refresh(self) -> bool:
        st = self.state()
        cost = st.refresh_cost if st.refresh_cost is not None else REFRESH_PRICE
        if st.gold is not None and cost > st.gold:
            return False
        gold0, cards0 = st.gold, [(c.name, c.cost) for c in st.cards]
        self.ctx.tap(*P.REFRESH, wait=0.7)
        st = self._reread_shop()
        changed = cards0 != [(c.name, c.cost) for c in st.cards]
        if changed:
            self._spend(-cost)
        log.info("刷新商店：资金 %s → %s%s", gold0, st.gold, "" if changed else "（没有变化）")
        return changed

    def _copies(self, name: str) -> int:
        """Non-elite copies of ``name`` owned (field and bench)."""
        return sum(1 for u in self.board.units() + self.board.bench if name and u.name == name and not u.elite)

    def buy(self, card: ShopCard) -> Unit | None:
        """Buy one card. Affordability and room are judged from the known state before any
        tap; on refusal ``self.refusal`` says why ("gold" or "bench_full")."""
        self.refusal = ""
        st = self.state()
        if st.gold is None:
            st.gold = self._gold()     # not inferable (e.g. an earlier price was unread): read it once
        if st.gold is None:
            log.info("读不出资金，不购买 %s", card.describe())
            self.refusal = "gold"
            return None
        if card.cost is not None and card.cost > st.gold:
            log.info("资金 %d，买不起 %s", st.gold, card.describe())
            self.refusal = "gold"
            return None
        before_img = self.ctx.device.screenshot()
        if self.board.bench_full or len(bench_positions(before_img)) >= BENCH_SIZE:
            log.info("整备区已满，不购买 %s", card.describe())
            self.refusal = "bench_full"
            return None
        expect_merge = merges(self._copies(card.name))
        gold0, what = st.gold, card.describe()
        self.ctx.tap(*card.tap_point, wait=0.6)
        self.ctx.tap(card.x, P.CARD_TAP_Y + P.BUY_TAP_DY, wait=0.8)
        slot = None
        for _ in range(2):   # the new operator walks onto the bench
            after_img = self.ctx.device.screenshot()
            slot = new_bench_position(before_img, after_img, fallback=False)
            if slot or expect_merge:
                break
            self.ctx.sleep(0.4)
        if slot is None and not expect_merge:
            # only the picture changed (an operator whose body misses the plank band, or a
            # toast such as 整备区已满 over the bench): the gold decides whether it was bought
            changed = new_bench_position(before_img, after_img)
            real = self._gold() if changed else None
            if real is not None and gold0 is not None and card.cost and real <= gold0 - card.cost:
                slot = changed
            elif changed:
                log.info("整备区画面有变化但资金未减少（%s → %s），%s 没有买下", gold0, real, card.describe())
                full = len(bench_positions(after_img)) >= BENCH_SIZE - 1 or self._bench_full_notice()
                self.refusal = "bench_full" if full else "gold"
                self.board.bench_full = full
                if real is not None:
                    self.state().gold = real
                return None
        unit = Unit(card.name, card.tier, tuple(card.labels), card.cost)
        if slot is not None:
            self._record(unit, slot[0])
            self._spend(-(card.cost or 0))
            if slot[0] == SLOT_X[0]:
                self.board.bench_full = True   # slots fill from the right: the leftmost was the last
            card.empty, card.operator = True, False
            if card.cost == 0:
                self._reread_shop()    # a free reward card: taking one ends the offer, the shop returns
        elif expect_merge:
            self._spend(-(card.cost or 0))
            self._merged(unit)
            self._reread_shop()        # the free reward cards replace the shop for one pick
        else:
            st = self.resync(f"买下 {card.describe()} 后整备区没有出现新干员")
            if gold0 is not None and st.gold is not None and st.gold < gold0:
                self._merged(unit)     # it was bought after all: the names of the copies were misread
            else:
                full = self._bench_full_notice()
                log.warn("购买 %s 没有生效%s", card.describe(), "（整备区已满）" if full else "")
                self.refusal = "bench_full" if full else "gold"
                self.board.bench_full = full
                return None
        log.info("购买 %s，资金 %s → %s%s", what, gold0, self.state().gold,
                 "" if slot else "（备战席上没有新干员，已合成精锐）")
        return unit

    def _merged(self, unit: Unit) -> None:
        """Three copies merge into one elite: forget the two copies that were used up.

        A copy on the field becomes the elite, so the used copies come from the bench."""
        field = [cid for cid, u in self.board.occupied.items() if u.name and u.name == unit.name]
        bench = [u for u in self.board.bench if u.name == unit.name]
        used = 2
        for cid in field[1:]:
            del self.board.occupied[cid]
            used -= 1
        for u in bench[:max(0, used)] if field else bench:
            self._forget(u)
        if field:
            kept = self.board.occupied[field[0]]
            kept.elite = True
            log.info("%s 合成精锐（%s）", kept.describe(), field[0])

    # --- holding an operator ------------------------------------------------------
    # A held operator is carried straight from its bench slot to where it goes (a cell,
    # the sell zone); it is never parked on the left first. To put it back it is released
    # over the info panel (P.HOLD_CANCEL), which returns it to its own slot. (Releasing on
    # the bench in the drag view would move it: that view's bench is wider than the normal
    # one, so a slot's normal x lands in another slot.)
    def _grab(self, xy: tuple[int, int], aim: tuple[int, int]) -> np.ndarray | None:
        """Press the bench item at ``xy`` and carry it to ``aim``, still held. Returns the
        drag-view screenshot, or None (nothing held any more) when nothing was picked up."""
        bx, by = xy[0] + self._dx, xy[1]
        dev = self.ctx.device
        dev.touch_down(bx, by)
        dev.move_path(bx, by, bx, by - 120, 5)
        self.ctx.sleep(0.35)   # the camera tilts into the drag view
        dev.move_path(bx, by - 120, *aim, 8)
        self._finger = aim
        for wait in (0.3, 0.5):
            self.ctx.sleep(wait)
            image = dev.screenshot()
            if find(self.ctx.ocr.read(image, P.DETAIL_PANEL), *OPERATOR_TABS):
                return image
        self._cancel_hold()
        return None

    def _cancel_hold(self) -> None:
        """Release the held operator over the info panel: it returns to its own bench slot."""
        dev = self.ctx.device
        dev.move_path(*self._finger, *P.HOLD_CANCEL, 8)
        self.ctx.sleep(0.2)
        dev.touch_up(*P.HOLD_CANCEL)
        self.ctx.sleep(0.5)

    def _held(self, image: np.ndarray) -> Unit:
        """Name, tier and alliance/trait labels of the held operator, from its info panel."""
        raw = drag_name(self.ctx.ocr.read(image, P.DRAG_INFO_NAME))
        labels = [b.compact for b in self.ctx.ocr.read(image, P.DRAG_INFO_TRAITS)
                  if has_cjk(b.compact) and "攻击范围" not in b.compact]
        tier = tier_in_box(image, P.DRAG_INFO_TIER)
        hit = self.names.operator(raw)
        unit = Unit(hit.name if hit.known else clean(raw), tier, tuple(self.names.labels(labels) or labels))
        unit.equipment = hit.kind == "equipment"
        # a summon (狼群, 爬行号·防护单元 …): no known name and no bond labels; it holds a bench
        # slot, cannot be sold and is not deployed (the run does not need it)
        unit.summon = not hit.known and not unit.equipment and not self.names.labels(labels)
        return unit

    def _grab_unit(self, unit: Unit, aim: tuple[int, int]) -> np.ndarray | None:
        """Pick up the recorded ``unit`` and carry it to ``aim``. When its slot holds something
        else (the record is off, e.g. an operator was given rather than bought), that slot's
        record is corrected and the occupied slots to its left are tried, then two to its right."""
        if not unit.bench_xy:
            return None
        x0 = unit.bench_xy[0]
        occupied = [x for x, _ in self._bench_positions()]
        left = sorted((x for x in occupied if x < x0 - 30), reverse=True)[:MAX_SLOT_SEARCH]
        right = sorted(x for x in occupied if x > x0 + 30)[:2]     # last resort, after the left side
        for x in [x0] + left + right:
            # once one slot proved wrong, the records next to it are not trusted either
            known = self._bench_unit(x)
            if x != x0 and known is not None and not_operator(known):
                continue   # a summon, equipment or an unreadable slot: picking it up tells nothing
            image = self._grab((x, PICK_Y), aim)
            if image is None:
                log.info("整备区 %d 处没有拿起干员", x)
                if x == x0:
                    self._forget(unit)
                continue
            held = self._held(image)
            if held.equipment:
                log.warn("整备区 %d 处拿起的是装备 %s，不是 %s", x, held.name, unit.name or "干员")
                self._cancel_hold()
                if x == x0:
                    self._forget(unit)
                self._record(held, x)     # remembered, so it is not picked up again
                continue
            # a recorded name that is no known name was a bad read of the card (「OOODRETIC」):
            # in its own slot the held panel decides who it is
            misread = x == x0 and held.name in self.names.operators and unit.name not in self.names.operators
            if not unit.name or not held.name or same_name(held.name, unit.name) or misread:
                if misread and not same_name(held.name, unit.name):
                    log.info("%s 实际是 %s", unit.describe(), held.name)
                    unit.name, unit.labels, unit.tier = held.name, held.labels or unit.labels, held.tier or unit.tier
                if x != x0:
                    log.info("%s 实际在整备区 %d 处（记录为 %d）", unit.describe(), x, x0)
                    if known is not None and known is not unit:
                        self._forget(known)
                    self._record(unit, x)
                if not unit.labels:
                    unit.labels = held.labels
                return image
            log.warn("整备区 %d 处是 %s 而不是 %s", x, held.name, unit.name)
            self._cancel_hold()
            self._record(held, x)
        return None

    # --- field -------------------------------------------------------------------
    def _free_cells(self, cells: Sequence[Cell]) -> list[Cell]:
        """Cells of ``cells`` that are empty according to this game's field record."""
        return [c for c in cells if c.id not in self.board.occupied]

    def _drop(self, cell: Cell) -> bool:
        dev = self.ctx.device
        if self._finger != cell.point:
            dev.move_path(*self._finger, *cell.point, 8)
        dev.touch_up(*cell.point)
        self.ctx.sleep(0.7)
        return self._face_right(cell)

    def _in_facing(self) -> bool:
        return find(self.ctx.read(P.FACING_TEXT), "点击取消") is not None

    def _face_right(self, cell: Cell) -> bool:
        if not self._in_facing():
            return False   # the drop did not start a deployment
        dev = self.ctx.device
        for k in range(3):
            distance = P.FACING_DRAG + 60 * k
            dev.touch_down(*cell.point)
            dev.move_path(*cell.point, cell.x + distance, cell.y, 8)
            self.ctx.sleep(0.2)
            dev.touch_up(cell.x + distance, cell.y)
            self.ctx.sleep(0.8)
            if not self._in_facing():
                return True
        log.snapshot(self.ctx.device.screenshot(), "facing_failed")
        log.warn("设置朝向失败（%s）", cell.id)
        return True   # deployed, but facing may be wrong; the match loop will retry

    def _drop_on(self, unit: Unit, cell: Cell, before: np.ndarray) -> tuple[int, int] | None | bool:
        """Drop the held ``unit`` on ``cell`` and update both records. Returns the bench slot
        of the operator pushed off the cell (None when the cell was empty), False on failure."""
        x = unit.bench_xy[0] if unit.bench_xy else None
        was_free = cell.id not in self.board.occupied
        if not self._drop(cell):
            return False
        self.board.occupied[cell.id] = unit
        self._forget(unit)
        st = self.state()
        if was_free and st.slots_left is not None:
            st.slots_left = max(0, st.slots_left - 1)   # one more operator on the field
        return new_bench_position(before, self.ctx.device.screenshot(), ignore=x)

    def _record_incomplete(self) -> bool:
        """The HUD counts more operators on the field than the record has, or the program was
        started in the middle of a game and the count could not be read."""
        left = self.state().slots_left
        if left is None:   # unread (a 0 often is): only a game joined midway is known to be incomplete
            return self.board.resumed and len(self.board.occupied) < self.layout.max_operators
        return self.layout.max_operators - left > len(self.board.occupied)

    def _fill_record(self, image: np.ndarray, free: list[Cell], aimed: Cell) -> list[Cell]:
        """Only when the record is incomplete: record-free cells that do not glow green while
        an operator is held are taken by someone unknown. This only adds to the record; the
        cell under the finger is left to the swap check (it is drawn differently)."""
        still = []
        for c in free:
            if c is aimed or is_green(image, c.point):
                still.append(c)
            else:
                self.board.occupied[c.id] = Unit("")
                log.debug("%s 上有记录外的干员", c.id)
        return still

    def deploy(self, unit: Unit, cells: Sequence[Cell]) -> Cell | None:
        if not unit.bench_xy or not cells:
            return None
        free = self._free_cells(cells)
        if not free:
            log.info("区域内没有空位（按本局记录），%s 留在整备区", unit.describe())
            self.deploy_failure = "no_room"
            return None
        cell = free[0]
        before = self.ctx.device.screenshot()
        image = self._grab_unit(unit, cell.point)
        if image is None:
            self.deploy_failure = "missing"
            return None
        if self._record_incomplete():
            free = self._fill_record(image, free, cell)
            if not free:
                log.info("区域内没有空位，%s 留在整备区", unit.describe())
                self._cancel_hold()
                self.deploy_failure = "no_room"
                return None
            cell = free[0]
        out = self._drop_on(unit, cell, before)
        if out is False:
            log.warn("部署 %s 到 %s 失败", unit.describe(), cell.id)
            self.deploy_failure = "drop"
            return None
        log.info("部署 %s → %s（第%d列第%d行，朝右）", unit.describe(), cell.id, cell.col, cell.row)
        if out is not None:
            # a summoner's summon joins the bench (伺夜 → 狼群), or someone the record missed stood
            # on the cell and was swapped back; either way the arrival is unknown until it is read
            log.info("部署后整备区 %d 处多了一个单位（召唤物，或原在 %s 上、记录中没有的干员）", out[0], cell.id)
        return cell

    def deploy_bench(self, choose: Callable[[Unit], Sequence[Cell]]) -> int:
        """Deploy whatever waits on the bench. Recorded operators are judged without being
        picked up; unknown slots (e.g. an operator that was given) are read first."""
        placed = 0
        for x, _ in self._bench_positions():
            unit = self._slot_unit(x)
            if unit is None or not_operator(unit):
                continue
            cells = choose(unit)
            if not cells:
                continue                       # kept on the bench (e.g. a copy for merging)
            if not self._free_cells(cells):
                break                          # the region is full
            if self.deploy(unit, cells) is not None:
                placed += 1
        return placed

    def bench_count(self) -> int:
        """Occupied bench slots (summons included). Full when the last arrival took the leftmost slot."""
        n = len(self._bench_positions())
        return BENCH_SIZE if self.board.bench_full else n

    def _bench_full_notice(self) -> bool:
        """「整备区已满，无法从调度中心购买」 (top right) or 「干员已满」 over the bench; read only after a refused purchase."""
        image = self.ctx.device.screenshot()
        return find(self.ctx.ocr.read(image, P.NOTICE_TOP) + self.ctx.ocr.read(image, P.NOTICE_BENCH),
                    "整备区已满", "干员已满") is not None

    def _slot_unit(self, x: int) -> Unit | None:
        """The unit in slot ``x``: the record, or the screen when there is none. A slot that
        could not be read is tried again once in a later phase, never twice in one."""
        unit = self._bench_unit(x)
        if unit is None or (unit.unknown and unit.misses < READ_TRIES and x not in self._tried):
            return self._read_slot(x)
        return unit

    def _read_slot(self, x: int) -> Unit | None:
        """Pick up the operator in slot ``x``, read it and put it back; it is then recorded.
        A slot that cannot be picked up is recorded as unknown, so it is not tried over and
        over; a summon or unknown unit in the leftmost slot is moved to a free slot on its right."""
        self._tried.add(x)
        image = self._grab((x, PICK_Y), P.HOLD_CANCEL)
        if image is None:
            unit = self._bench_unit(x)
            if unit is None or not unit.unknown:
                unit = Unit("", unknown=True)
            unit.misses += 1
            self._record(unit, x)
            log.info("整备区 %d 处的单位拿起后没有干员信息（召唤物或识别失败），第 %d 次，%s", x, unit.misses,
                     "之后不再读取" if unit.misses >= READ_TRIES else "下个休整期再读一次")
            self._leave_leftmost(unit, x)
            return None
        unit = self._held(image)
        self._cancel_hold()
        self._record(unit, x)
        if unit.equipment:
            log.warn("整备区 %d 处拿起的是装备 %s", x, unit.name)
            return None
        if unit.summon:
            log.info("整备区 %d 处是召唤物 %s，不出售、不部署", x, unit.name or "")
            self._leave_leftmost(unit, x)
        return unit

    def _leave_leftmost(self, unit: Unit, x: int) -> None:
        """A summon or unreadable unit in the leftmost slot is dragged to the rightmost free
        slot: arrivals fill the bench from the right, so the leftmost slot must stay the last
        one taken (an arrival there means the bench is full). Without a free slot it stays,
        and the slots to its right are handled as usual."""
        if abs(x - SLOT_X[0]) > 30:
            return
        image = self.ctx.device.screenshot()
        before = [p for p, _ in bench_positions(image, self._dx)]
        free = [s for s in SLOT_X[1:] if all(abs(s - p) > 30 for p in before)]
        if not free:
            log.info("整备区最左侧是%s，没有空位可移，跳过", "召唤物" if unit.summon else "无法读取的单位")
            return
        target = free[-1]
        bx, by = x + self._dx, PICK_Y
        dev = self.ctx.device
        dev.touch_down(bx, by)
        dev.move_path(bx, by, bx, by - 120, 5)
        self.ctx.sleep(0.35)   # the camera tilts into the drag view
        tx = drag_view_x(target)
        dev.move_path(bx, by - 120, tx, DRAG_BENCH_Y, 8)
        self.ctx.sleep(0.3)
        dev.touch_up(tx, DRAG_BENCH_Y)
        self.ctx.sleep(0.7)
        after = [p for p, _ in bench_positions(self.ctx.device.screenshot(), self._dx)]
        arrived = [p for p in after if all(abs(p - b) > 30 for b in before)]
        if arrived and all(abs(p - x) > 30 for p in after):
            self._record(unit, arrived[0])
            log.info("把整备区最左侧的%s移到 %d 处", "召唤物" if unit.summon else "单位", arrived[0])
        else:
            log.info("整备区最左侧的单位没有移动（目标 %d 处），跳过", target)

    def survey_bench(self) -> list[tuple[int, Unit]]:
        """(slot x, operator) for every occupied bench slot. Recorded operators come from the
        record; only unknown slots are picked up and read."""
        found, read = [], 0
        for x, _ in self._bench_positions():
            known = self._bench_unit(x)
            unit = self._slot_unit(x)
            if unit is None:
                continue
            read += unit is not known
            if not not_operator(unit):
                found.append((x, unit))
        log.info("整备区（%d 名，其中 %d 名重新读取）：%s", len(found), read,
                 "、".join(f"{u.name or '?'}{list(u.labels)}" for _, u in found) or "空")
        return found

    def sell_bench(self, slot_x: int, unit: Unit) -> bool:
        """Sell bench operator ``unit`` (recorded in slot ``slot_x``); its name is checked while held."""
        if unit.bench_xy is None or abs(unit.bench_xy[0] - slot_x) > 30:
            self._record(unit, slot_x)
        gold0 = self.state().gold
        if self._grab_unit(unit, P.SELL) is None:
            log.warn("整备区没有找到 %s，不出售", unit.describe())
            return False
        self.ctx.sleep(0.2)
        self.ctx.device.touch_up(*P.SELL)
        self.ctx.sleep(0.7)
        self._spend(SELL_PRICE)
        self._forget(unit)
        self.board.sold += 1
        self.board.bench_full = False
        log.info("出售整备区的 %s，资金 %s → %s", unit.describe(), gold0, self.state().gold)
        return True

    def replace(self, unit: Unit, cell: Cell) -> bool:
        old = self.board.occupied.get(cell.id)
        if not unit.bench_xy or old is None:
            return False
        before = self.ctx.device.screenshot()
        if self._grab_unit(unit, cell.point) is None:
            return False
        out = self._drop_on(unit, cell, before)
        if out is False:
            log.warn("替换 %s 失败", cell.id)
            return False
        log.info("用 %s 替换 %s（%s）", unit.describe(), old.describe(), cell.id)
        if out and self.sell(out):
            self.board.sold += 1
        elif out:
            self._record(old, out[0])
        return True

    def sell(self, xy: tuple[int, int]) -> bool:
        """Sell the bench operator at ``xy`` (one just pushed off the field). Proof: its slot is empty."""
        gold0 = self.state().gold
        dev = self.ctx.device
        x, y = xy[0] + self._dx, xy[1]
        dev.touch_down(x, y)
        dev.move_path(x, y, x, y - 120, 5)
        dev.move_path(x, y - 120, *P.SELL, 8)
        self.ctx.sleep(0.3)
        dev.touch_up(*P.SELL)
        self.ctx.sleep(0.7)
        ok = all(abs(x - xy[0]) > 30 for x, _ in bench_positions(self.ctx.device.screenshot()))
        if ok:
            self._spend(SELL_PRICE)
            self.board.bench_full = False
        log.info("卖出干员：资金 %s → %s%s", gold0, self.state().gold, "" if ok else "（整备区该位置仍有干员，未卖出）")
        return ok

    # --- end of round ------------------------------------------------------------
    def check_gold(self) -> int | None:
        """The one gold read after the start of the phase: compare it with the inferred amount."""
        real = self._gold()
        known = self._st.gold if self._st is not None else None
        if known is not None and real is not None and real != known:
            log.info("准备就绪前核对资金：界面 %d，推算 %d（以界面为准）", real, known)
        elif real is None:
            log.debug("准备就绪前核对资金：没有读出数字（推算 %s）", known)
        else:
            log.debug("准备就绪前核对资金：%s，与推算一致", real)
        if self._st is not None and real is not None:
            self._st.gold = real
        return real

    def press_ready(self) -> None:
        self.ctx.sleep(0.5)   # let "资金不足" style toasts fade so they do not cover the button
        self.check_gold()
        self.ctx.tap(*P.READY, wait=1.0)
        screen = self.ctx.look()
        if screen.kind is Kind.CONFIRM_READY:
            confirm_ready_dialog(self.ctx, screen)


def confirm_ready_dialog(ctx: GameContext, screen: Screen | None = None) -> None:
    """Confirm 准备就绪. Two dialogs: 「确认准备吗？剩余资金将在离开休整期时清空」 (tick 本局不再提示)
    and, when the bench or the equipment row overflowed, 「确认准备就绪吗？当前仍处于临时整备区的
    干员和装备，将在进入战斗后自动销毁」 (no tick box)."""
    boxes = screen.boxes if screen is not None else ctx.read((0, 280, 1920, 800))
    if find(boxes, "临时整备区", "自动销毁"):
        log.info("整备区或装备区溢出，确认准备就绪（溢出的干员和装备会被销毁）")
    else:
        ctx.tap(*P.DIALOG_NO_REMIND, wait=0.3)
    hit = find(boxes, "确认", region=(960, 660, 1920, 800))
    ctx.tap(*(hit.x, hit.y) if hit else P.DIALOG_CONFIRM, wait=1.2)
