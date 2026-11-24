"""SP3 operator catalog: who an operator read from a card really is. Shared by every SP3 strategy.

``resources/data/sp3_operators.json`` (generated from the simulator's SP3 data by
``private/sim/gen_table.mjs``) lists every shop operator by the name on its card: tier,
alliances / traits (盟约), melee or ranged, profession and block count. A player who does
not own an operator gets a stand-in (预备干员-术师, Sharp, Touch …): the card then shows the
stand-in's name, the stand-in fights with its own body (profession, range, block), and the
traits on the card stay those of the original operator.

:meth:`Catalog.identify` turns what OCR read (name, tier, trait lines) into an
:class:`Identity` with a confidence:

* 1.0  exact operator name;
* 0.8  the read text contains exactly one operator name (OCR noise such as 「水褐果」 → 褐果),
       or a stand-in whose candidates narrow down to one by tier and traits;
* 0.6  a stand-in with several candidates left: its body is known, its traits come from the card;
* 0.3  unknown name: tier and traits from the card, the body guessed (conservative fallback).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Sequence

from ...paths import resource

# The SP3 season these strategies were derived for; data or parameters for another one are refused.
DATA_VERSION = "act3autochess@V3_1"


class CatalogError(ValueError):
    """The operator table is missing, from another season, or was edited (content hash mismatch)."""


def content_hash(data: dict) -> str:
    """sha256 (16 hex) of what the strategies read; the same value private/sim/gen_table.mjs writes."""
    part = {k: data[k] for k in ("operators", "stand_ins", "bonds", "modes")}
    text = json.dumps(part, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Identity:
    name: str                       # what the card showed (the stand-in's name for a stand-in)
    operator: str                   # the operator it is (a stand-in's original when known, else "")
    tier: int
    bonds: tuple[str, ...]
    position: str                   # "MELEE" | "RANGED"
    profession: str                 # PIONEER, WARRIOR, TANK, SNIPER, CASTER, MEDIC, SUPPORT, SPECIAL, ""
    block: int
    confidence: float
    stand_in: bool = False
    candidates: tuple[str, ...] = field(default=())
    chess_id: str = ""              # SP3 data id of the operator (stable across OCR spellings), "" when unknown

    @property
    def melee(self) -> bool:
        return self.position == "MELEE"

    @property
    def medic(self) -> bool:
        return self.profession == "MEDIC"


class Catalog:
    def __init__(self, data: dict):
        self.version: str = data.get("version", "")
        if self.version != DATA_VERSION:
            raise CatalogError(f"干员表版本是 {self.version or '未知'}，打法需要 {DATA_VERSION}")
        try:
            digest = content_hash(data)
        except KeyError as exc:
            raise CatalogError(f"干员表缺少 {exc}") from exc
        if digest != data.get("content_hash"):
            raise CatalogError(f"干员表内容与记录的哈希不符（{digest} ≠ {data.get('content_hash')}），请重新生成")
        self.content_hash: str = digest
        self.operators: dict[str, dict] = data["operators"]
        self.stand_ins: dict[str, dict] = data.get("stand_ins", {})
        self.bonds: dict[str, dict] = data.get("bonds", {})
        self.modes: dict[str, dict] = data.get("modes", {})
        # longest names first, so 「纯烬艾雅法拉」 wins over 「艾雅法拉」 inside a noisy read
        self._names = sorted(self.operators, key=len, reverse=True)

    @classmethod
    def load(cls, path: Path | None = None) -> "Catalog":
        return _load(str(path or resource("data", "sp3_operators.json")))

    # --- bonds ------------------------------------------------------------------------
    def thresholds(self, bond: str) -> list[int]:
        return list(self.bonds.get(bond, {}).get("thresholds") or [2])

    def is_season(self, bond: str) -> bool:
        return self.bonds.get(bond, {}).get("kind") == "SEASON"

    def mode(self, name: str) -> dict:
        return self.modes.get(name, {})

    # --- identification ---------------------------------------------------------------
    def identify(self, name: str, tier: int = 0, labels: Sequence[str] = ()) -> Identity:
        labels = tuple(l for l in labels if l)
        rec = self.operators.get(name)
        if rec:
            return self._from_record(name, name, rec, 1.0)
        if name in self.stand_ins:
            return self._stand_in(name, tier, labels)
        found = [n for n in self._names if n and n in (name or "")]
        found = [n for n in found if not any(n != o and n in o for o in found)]   # drop names inside longer ones
        if tier:
            found = [n for n in found if self.operators[n]["tier"] == tier] or found
        if len(found) == 1:
            return self._from_record(name, found[0], self.operators[found[0]], 0.8)
        for s in self.stand_ins:
            if s and s in (name or ""):
                return self._stand_in(s, tier, labels)
        bonds = tuple(b for b in labels if b in self.bonds)
        return Identity(name, "", tier, bonds, "MELEE", "", 1, 0.3)

    def _from_record(self, shown: str, operator: str, rec: dict, confidence: float) -> Identity:
        return Identity(shown, operator, int(rec["tier"]), tuple(rec["bonds"]), rec["position"],
                        rec.get("profession", ""), int(rec.get("block", 0)), confidence, chess_id=rec.get("id", ""))

    def _stand_in(self, name: str, tier: int, labels: tuple[str, ...]) -> Identity:
        s = self.stand_ins[name]
        cands = [c for c in s.get("stands_in", []) if c in self.operators]
        if tier:
            cands = [c for c in cands if self.operators[c]["tier"] == tier] or cands
        bond_labels = {l for l in labels if l in self.bonds}
        if bond_labels:
            cands = [c for c in cands if bond_labels <= set(self.operators[c]["bonds"])] or cands
        operator = cands[0] if len(cands) == 1 else ""
        bonds = tuple(self.operators[operator]["bonds"]) if operator else tuple(sorted(bond_labels))
        tier = tier or (self.operators[operator]["tier"] if operator else 0)
        return Identity(name, operator, tier, bonds, s["position"], s.get("profession", ""),
                        int(s.get("block", 0)), 0.8 if operator else 0.6, stand_in=True, candidates=tuple(cands),
                        chess_id=self.operators[operator].get("id", "") if operator else "")


@lru_cache(maxsize=4)
def _load(path: str) -> Catalog:
    return Catalog(json.loads(Path(path).read_text(encoding="utf-8")))
