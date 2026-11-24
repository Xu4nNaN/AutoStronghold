"""Which Stronghold Protocol screen is showing, judged from recognised text."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

import numpy as np

from ..geometry import Event, Prep
from ..vision.ocr import TextBox, find, has, joined


class Kind(str, Enum):
    LOBBY = "卫戍协议开始界面"
    LOBBY_JOINT = "开始界面（联合模拟页）"
    DIFFICULTY = "选择模拟难度"
    MATCH_INFO = "确认本局信息"
    STRATEGY = "选择策略"
    SQUAD = "确定自选编队"
    LOADING = "加载中"
    PREP = "休整期"
    CONFIRM_READY = "确认准备弹窗"
    FACING = "选择朝向"
    EVENT = "道具补给/战术决策"
    BATTLE = "战斗中"
    RESULT = "结算"
    UNKNOWN = "未知界面"


# Text that only appears inside Stronghold Protocol; used to tell "still in the event"
# from "left it". The event *name* (卫戍协议) is deliberately absent: the game's main
# menu shows it on the event banner.
GARRISON_MARKS = ("STRONGHOLD", "极速模拟", "独立模拟", "规程等级", "个人模拟", "确认准备", "剩余资金将在",
                  "联合模拟", "同盟模拟", "选择策略", "自选编队", "准备就绪", "取消准备", "返回主页",
                  "模拟完成", "模拟中断", "COUNTDOWN", "断线重连", "道具补给", "战术决策", "剩余可放置角色",
                  "请选择模拟难度", "确认本局信息")
MODE_MARKS = ("极速模拟", "规程等级")
# Words of the game's main screen; several of them together mean it is showing.
MAIN_MENU_WORDS = ("理智", "编队", "干员", "采购中心", "公开招募", "基建", "任务", "仓库", "档案", "好友")


class Outside(str, Enum):
    """Screens outside 卫戍协议 on the way back after the daily data update."""
    SYNC = "数据更新提示"
    SUPPLY = "今日配给"
    POPUP = "签到/公告弹窗"
    MAIN_MENU = "游戏主界面"
EVENT_TITLES = ("道具补给", "战术决策")


@dataclass
class Screen:
    kind: Kind
    image: np.ndarray
    boxes: list[TextBox] = field(default_factory=list)
    text: str = ""
    in_garrison: bool = False
    # details
    collapsed: bool = False          # PREP: card area hidden, "展开" shown
    ready_pressed: bool = False      # SQUAD: 准备就绪 already pressed (button now reads 取消准备)
    reconnect: bool = False          # LOBBY: 断线重连 is shown (a game is not finished)
    interrupted: bool = False        # LOBBY: … because the data update ended it (已终止), not left by the player
    event_title: str = ""
    win: bool = False                # RESULT
    mode_label: str = ""             # "极速模拟" / "规程等级N" shown on loading / HUD
    outside: Outside | None = None   # UNKNOWN: a screen of the way back after the data update

    def find(self, *keywords: str, region=None) -> TextBox | None:
        return find(self.boxes, *keywords, region=region)

    def has(self, *keywords: str, region=None) -> bool:
        return has(self.boxes, *keywords, region=region)


def _mode_label(boxes: Sequence[TextBox]) -> str:
    hit = find(boxes, *MODE_MARKS)
    return hit.compact if hit else ""


def _outside(text: str) -> Outside | None:
    if "即将进行同步" in text:
        return Outside.SYNC
    if "今日配给" in text:
        return Outside.SUPPLY
    if any(k in text for k in ("签到", "活动公告", "系统公告")):
        return Outside.POPUP
    if sum(w in text for w in MAIN_MENU_WORDS) >= 4:
        return Outside.MAIN_MENU
    return None


def classify(image: np.ndarray, boxes: list[TextBox]) -> Screen:
    text = joined(boxes)
    upper = text.upper()
    s = Screen(Kind.UNKNOWN, image, boxes, text)
    s.in_garrison = any(m in upper for m in GARRISON_MARKS)
    s.mode_label = _mode_label(boxes)

    def has_text(*keys: str) -> bool:
        return any(k in text for k in keys)

    if has_text("返回主页"):
        s.kind, s.win = Kind.RESULT, has_text("模拟完成")
    elif has_text("确认准备吗", "剩余资金将在", "确认准备就绪吗", "临时整备区", "自动销毁"):
        s.kind = Kind.CONFIRM_READY
    elif title := next((t for t in EVENT_TITLES if has(boxes, t, region=Event.TITLE)), ""):
        s.kind, s.event_title = Kind.EVENT, title
    elif has_text("点击取消"):
        s.kind = Kind.FACING
    elif has_text("准备就绪") and has_text("回合", "休息一下", "剩余可放置角色"):
        s.kind = Kind.PREP
        hit = find(boxes, "展开", region=Prep.EXPAND_BOX)
        s.collapsed = hit is not None and len(hit.compact) <= 4
    elif has_text("确定自选编队"):
        s.kind = Kind.SQUAD
        s.ready_pressed = has_text("取消准备", "已选择自选编队")
    elif has_text("选择策略"):
        s.kind = Kind.STRATEGY
    elif has_text("请选择模拟难度"):
        s.kind = Kind.DIFFICULTY
    elif has_text("确认本局信息"):
        s.kind = Kind.MATCH_INFO
    elif has_text("个人模拟") and has_text("联合模拟", "断线重连"):   # 联合模拟 is hard to read beside 断线重连
        s.reconnect = has_text("断线重连")
        s.interrupted = s.reconnect and has_text("已终止", "模拟中断") and not has_text("放弃模拟")
        joint = has_text("同盟模拟", "搜寻队友") and not has_text("极速模拟", "独立模拟")
        s.kind = Kind.LOBBY_JOINT if joint else Kind.LOBBY
    elif "OPERATION" in upper and s.mode_label:
        s.kind = Kind.LOADING
    elif s.mode_label and find(boxes, *MODE_MARKS, region=(0, 0, 520, 130)):
        # In-match HUD (top-left mode label) without the preparation controls.
        s.kind = Kind.BATTLE
    elif not s.in_garrison:
        s.outside = _outside(text)
    return s
