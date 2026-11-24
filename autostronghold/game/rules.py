"""Prep-phase rules of 卫戍协议·规程 序列Ⅰ, used to infer the HUD instead of reading it.

Each action has a known effect: a purchase costs the card's price and puts the operator in
the rightmost free bench slot, unless it is the third copy (the copies merge into an elite
and three free reward cards appear in the shop); a refresh costs 1 unless it is free; an
upgrade costs the shown price, raises the level, opens the level's extra (empty) slots and
resets the price to the next level's base; a sale gives 1. The session therefore reads the
HUD once at the start of the preparation phase and afterwards only what cannot be inferred.

Ported from Stronghold-Protocol (https://github.com/sganggs/Stronghold-Protocol,
GPL-3.0-or-later, Copyright (C) 2026 Stronghold-Protocol contributors):
``server/match/gamedata.js`` (``DEFAULTS``: benchSize, mergeCount, rewardOffer, shopSlots,
maxShopLevel), ``data/versions/act3autochess-v3_1/config.json`` (economy: chessSell 1 for
every tier, refreshPrice 1) and ``server/match/player/economy.js`` (``buy``, ``refresh``,
``levelUp``, ``sell``, ``_openLevelSlots``). The per-mode upgrade prices, card prices and
round income are in ``resources/data/sp3_operators.json`` (``modes``, ``economy``).
"""
from __future__ import annotations

BENCH_SIZE = 10            # 干员区 (summons included); a full bench refuses purchases
MERGE_COUNT = 3            # the third copy merges the copies into one elite
REWARD_CARDS = 3           # free cards of a higher tier offered after a merge; taking one ends the offer
SELL_PRICE = 1             # every tier, normal and elite (traits may add more; the HUD shows it at the ready check)
REFRESH_PRICE = 1
MAX_SHOP_LEVEL = 6
# Shop slots per level (operator cards + one equipment card). New slots open empty on the left.
SHOP_SLOTS = {1: 4, 2: 5, 3: 5, 4: 6, 5: 6, 6: 6}


def merges(copies_owned: int) -> bool:
    """Buying one more copy completes a merge (``copies_owned`` non-elite copies already owned)."""
    return copies_owned + 1 >= MERGE_COUNT
