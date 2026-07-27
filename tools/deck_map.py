"""Map claude's candidate deck library to public-meta archetypes (SOT-2055).

The meta dashboard names archetypes in Japanese (e.g. ``マリィのオーロンゲex``);
claude's candidate decks are named/annotated in English in
``decks/candidates/manifest.json`` (``Marnie's Grimmsnarl ex``). This module is
the *curated, auditable bridge* between them, plus each deck's **role** in the
pool. It is deliberately data (not logic): every mapping row is a reviewable
claim, and unmapped decks are treated as off-meta with no share.

claude's role (see README): the ``decks/candidates`` pool is the *deck-selection
and opponent field* — it must field the current upper-meta archetypes, keep
counters that answer them, carry board-leaders (high rank / low share) and a
handful of baseline / tournament anchors for diversity. So a deck's value is not
only its own meta share but whether it covers a top archetype or answers one.

Roles
-----
* ``upper_meta``     — represents an archetype currently high in the Top100
* ``counter``        — a tech/answer deck aimed at beating upper-meta decks
* ``emerging``       — an archetype whose share is trending up
* ``low_usage_top``  — high on the leaderboard yet low Top100 share (タケルライコex)
* ``baseline``       — diversity / tournament anchor kept for coverage
"""
from __future__ import annotations

import glob as _glob
import json
import os
from typing import Dict, List, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATE_DIR = os.path.join(REPO, "decks", "candidates")

# Japanese meta archetype -> canonical English label (documentation only).
META_KEY_EN = {
    "マリィのオーロンゲex": "Marnie's Grimmsnarl ex",
    "フーディン": "Alakazam",
    "イワパレス": "Crustle",
    "ドラパルトex": "Dragapult ex",
    "ロケット団のワナイダー": "Rocket's Spidops",
    "シロナのガブリアスex": "Cynthia's Garchomp ex",
    "タケルライコex": "Raging Bolt ex",
    "ノココッチ": "Dudunsparce",
    "バチンキー/カミッチュ/ペロッパフ": "Festival Lead (Katsuji)",
    "メガスターミーex": "Mega Starmie ex",
    "メガルカリオex": "Mega Lucario ex",
    "Nのゾロアークex": "N's Zoroark ex",
    "ブリジュラスex": "Archaludon ex",
    "ホップのオーロット": "Hop's Trevenant",
}

# deck NN (int) -> (meta_key or None, role). meta_key None => off-meta deck.
# Curated 2026-07-27 against decks/candidates/manifest.json + the meta snapshots.
# Deck 26 (stw_champion) is the shared champion list (root deck.csv) and is kept
# as a baseline anchor so the submission archetype always stays in the field.
DECK_META: Dict[int, Dict[str, Optional[str]]] = {
    1:  {"meta_key": "ドラパルトex", "role": "upper_meta"},
    2:  {"meta_key": "タケルライコex", "role": "low_usage_top"},
    3:  {"meta_key": "ドラパルトex", "role": "upper_meta"},
    4:  {"meta_key": "ドラパルトex", "role": "upper_meta"},
    5:  {"meta_key": "ドラパルトex", "role": "upper_meta"},   # Dragapult Dudunsparce (Dragapult primary)
    6:  {"meta_key": None, "role": "baseline"},              # Hydrapple — off-meta
    7:  {"meta_key": "Nのゾロアークex", "role": "baseline"},
    8:  {"meta_key": None, "role": "baseline"},              # Ogerpon Box — off-meta
    9:  {"meta_key": None, "role": "baseline"},              # Slowking — off-meta
    10: {"meta_key": "ホップのオーロット", "role": "baseline"},
    11: {"meta_key": None, "role": "baseline"},              # Lillie's Clefairy — off-meta
    12: {"meta_key": "フーディン", "role": "upper_meta"},
    13: {"meta_key": "バチンキー/カミッチュ/ペロッパフ", "role": "emerging"},
    14: {"meta_key": "メガルカリオex", "role": "counter"},
    15: {"meta_key": "マリィのオーロンゲex", "role": "upper_meta"},
    16: {"meta_key": "イワパレス", "role": "upper_meta"},
    17: {"meta_key": None, "role": "counter"},               # Rocket's Mewtwo — tech
    18: {"meta_key": None, "role": "counter"},               # Rocket's Honchkrow — tech
    19: {"meta_key": None, "role": "baseline"},              # Ethan's Typhlosion — off-meta
    20: {"meta_key": "シロナのガブリアスex", "role": "upper_meta"},
    21: {"meta_key": None, "role": "baseline"},              # Lillie's Clefairy ex — off-meta
    22: {"meta_key": "ドラパルトex", "role": "upper_meta"},
    23: {"meta_key": None, "role": "baseline"},              # Slowking NAIC — off-meta
    24: {"meta_key": "Nのゾロアークex", "role": "counter"},
    25: {"meta_key": None, "role": "counter"},               # Mega Lopunny — tech
    26: {"meta_key": None, "role": "baseline"},              # STW champion (root deck.csv anchor)
}


def load_manifest(name: str = "candidates") -> List[Dict[str, object]]:
    path = os.path.join(REPO, "decks", name, "manifest.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def deck_number(filename: str) -> Optional[int]:
    """Leading NN of an ``NN_*.csv`` deck filename, or None."""
    base = os.path.basename(filename)
    if len(base) >= 2 and base[:2].isdigit():
        return int(base[:2])
    return None


def library_rows() -> List[Dict[str, object]]:
    """Every legal candidate deck on disk with archetype/meta/role.

    Source: ``decks/candidates`` (claude's full deck library). ``group`` records
    where the CSV lives so the tool copies from the right place. Archetype text
    comes from the tournament manifest (keyed by filename) with a fallback to the
    26th champion deck; meta_key/role come from the curated ``DECK_META`` table.
    """
    manifest = {m["file"]: m for m in load_manifest("candidates")}
    rows: List[Dict[str, object]] = []
    paths = sorted(_glob.glob(os.path.join(CANDIDATE_DIR, "[0-9][0-9]_*.csv")))
    for path in paths:
        fname = os.path.basename(path)
        num = deck_number(fname)
        meta = DECK_META.get(num, {"meta_key": None, "role": "baseline"})
        m = manifest.get(fname, {})
        archetype = m.get("archetype")
        if not archetype:
            # 26_stw_champion has no manifest row (it is the shared champion).
            archetype = "STW champion (shared)" if num == 26 else fname
        rows.append({
            "file": fname,
            "group": "candidates",
            "number": num,
            "archetype": archetype,
            "meta_key": meta["meta_key"],
            "role": meta["role"],
        })
    return rows
