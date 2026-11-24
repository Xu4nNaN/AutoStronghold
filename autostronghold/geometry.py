"""Fixed UI coordinates on a 1920x1080 landscape screen.

All screenshots are normalised to 1920x1080 by the device layer, and all input
coordinates are given in this space, so every number about the game's layout lives
here. Values were measured on the CN client (MuMu 12, default theme) from the
screenshots. A box is ``(x1, y1, x2, y2)``; a point is ``(x, y)``.
"""
from __future__ import annotations

WIDTH, HEIGHT = 1920, 1080

Point = tuple[int, int]
Box = tuple[int, int, int, int]


class Lobby:
    """卫戍协议 start screen (个人模拟 / 联合模拟 tabs at the bottom right)."""

    PERSONAL_TAB: Point = (1495, 845)
    SPEED_BUTTON: Point = (1285, 985)        # 极速模拟
    INDEPENDENT_BUTTON: Point = (1675, 985)  # 独立模拟
    BACK: Point = (67, 60)                   # top-left "<" on sub screens


class Difficulty:
    """独立模拟 → 请选择模拟难度."""

    CURRENT_LABEL: Box = (0, 1000, 420, 1070)   # bottom-left "规程等级N"
    LIST: Box = (1300, 80, 1920, 880)          # level entries on the right, higher levels above
    START: Point = (1700, 990)                 # 开始模拟
    # The selected level sits at y≈500. Dragging the list by LEVEL_STEP selects the next
    # level (down = higher, up = lower); it stops at the highest unlocked level.
    SWIPE_X = 1650
    SWIPE_CENTRE_Y = 500
    LEVEL_STEP = 195
    MAX_LEVELS_PER_SWIPE = 4


class StrategyGrid:
    """2/3 选择策略. The card grid shifts left once any card has been tapped."""

    COLUMNS_UNSHIFTED = (1077, 1287, 1497, 1707)
    COLUMNS_SHIFTED = (680, 890, 1100, 1310)
    CARD_HALF_WIDTH = 92
    CARD_HEIGHT = 190
    VIEW_TOP, VIEW_BOTTOM = 150, 1062          # visible part of the scrolling list
    BADGE_FROM_RIGHT = 58                      # badge box: (right-58 .. right-6, top+4 .. top+54)
    BADGE_SIZE = (52, 50)
    PANEL: Box = (1440, 150, 1920, 800)        # right panel after tapping a card (shifted layout)
    CONFIRM: Point = (1680, 990)               # 确认选择
    EXIT: Point = (75, 65)                     # leave the simulation
    SCROLL_X = 1000
    SCROLL_FROM_Y = 1000
    SCROLL_TO_Y = 370                          # 630 px ≈ 3 rows, every row is fully visible once


class Squad:
    """3/3 确定自选编队: we never pick operators, only press 准备就绪."""

    READY: Point = (1686, 986)


class Prep:
    """休整期 (shop / preparation phase) in the normal (expanded) layout."""

    READY: Point = (1780, 170)                 # 准备就绪
    ROUND: Box = (728, 30, 780, 70)            # number next to 回合
    GOLD: Box = (1772, 770, 1840, 815)
    SLOTS_NORMAL: Box = (1855, 562, 1905, 612)    # number after 剩余可放置角色：
    SLOTS_COLLAPSED: Box = (1855, 676, 1905, 726)
    REFRESH: Point = (1786, 688)
    REFRESH_COST: Box = (1770, 628, 1816, 670)
    CARD_X = (304, 550, 790, 1034, 1274, 1520)  # shop slots, right aligned
    CARD_HALF_WIDTH = 115
    CARD_TOP, CARD_BOTTOM = 785, 1065
    CARD_TAP_Y = 920
    BUY_TAP_DY = 106                           # "购买" appears under the selected card
    CARD_COST_DY: tuple[int, int] = (-22, 22)  # cost circle: x±22, y 780..822
    CARD_COST_Y: tuple[int, int] = (780, 822)
    TIER_BOX_DX: tuple[int, int] = (-110, -64)
    TIER_BOX_Y: tuple[int, int] = (795, 832)
    LABEL_Y: tuple[int, int] = (930, 1000)     # alliance / trait lines on operator cards
    NAME_Y: tuple[int, int] = (1000, 1062)
    SHOP_TEXT: Box = (0, 770, 1700, 1068)
    HUD_TEXT: Box = (0, 550, 1920, 1078)       # read for the shop state: slots, refresh, level, cards
    DETAIL_PANEL: Box = (0, 250, 700, 620)     # operator info (特质/天赋/特性 tabs) on the left
    NOTICE_TOP: Box = (1380, 90, 1920, 290)    # 整备区已满 / 资金不足 notices
    NOTICE_BENCH: Box = (600, 700, 1320, 800)  # 干员已满 toast over the bench
    FACING_TEXT: Box = (300, 80, 1700, 820)    # 点击取消 shown while choosing a direction
    UPGRADE_TAP_Y = 920
    # x of the LEVEL card by the number of shop slots (rules.SHOP_SLOTS): it sits ~210 px left
    # of the leftmost card (measured: 4 slots 580, 6 slots 95; 5 slots derived)
    LEVEL_X = {4: 578, 5: 338, 6: 95}
    EXPAND_BOX: Box = (1640, 930, 1915, 1075)  # 收起 / 展开 toggle
    SELL: Point = (1760, 900)                  # drop target that sells a dragged operator
    BENCH: Box = (200, 560, 1500, 770)         # 备战席 (the plank) in the normal layout
    BENCH_SCAN = ((1390, 700), (1300, 700), (1210, 700), (1120, 700), (1030, 700), (940, 700),
                  (850, 700), (760, 700), (670, 700), (580, 700), (490, 700), (400, 700))
    # Releasing a held operator over the info panel (left, below the trait text) puts it
    # back into its own bench slot. Releasing on the drag view's bench would move it to the
    # slot under the finger, and that bench is wider than the normal view's (normal x 1384
    # is drag x ≈1560); releasing on the map deploys it.
    HOLD_CANCEL: Point = (300, 760)
    DRAG_INFO_NAME: Box = (0, 262, 330, 322)   # name shown on the left while dragging
    DRAG_INFO_TABS: Box = (0, 520, 700, 600)
    DRAG_INFO_TIER: Box = (16, 324, 64, 368)        # colour-coded tier frame of the held operator
    DRAG_INFO_TRAITS: Box = (290, 380, 700, 485)   # alliance / trait icons next to 攻击范围
    FACING_DRAG = 300                          # drag right this far to face right
    DIALOG_NO_REMIND: Point = (858, 604)       # 本局不再提示
    DIALOG_CONFIRM: Point = (1410, 728)        # 确认


class Event:
    """道具补给 / 战术决策: three option boxes in the middle of the screen."""

    TITLE: Box = (0, 0, 960, 200)
    MIDDLE_OPTION: Point = (988, 543)
    CONFIRM_FALLBACK: Point = (988, 728)       # 确认选择 under the selected box


class Result:
    HOME: Point = (1700, 990)                  # 返回主页


class Outside:
    """Screens outside 卫戍协议 met after the daily 4:00 data update."""

    SYNC_CONFIRM: Point = (960, 737)           # √ under 「数据已更新，即将进行同步」
    SUPPLY_CONFIRM: Point = (960, 960)         # √ at the bottom of 今日配给
    POPUP_CLOSE: Point = (1815, 104)           # × at the top right of sign-in / notice pop-ups
    BANNER: Box = (1500, 260, 1920, 440)       # 卫戍协议「规程」 entry on the main screen
    BANNER_TAP: Point = (1785, 355)
