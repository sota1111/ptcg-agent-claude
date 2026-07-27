"""Deck legality checks against the cabt card pool (SOT-2055).

Rules enforced (see decks/initial/README.md):
* exactly 60 cards,
* at most 4 copies of the same card by name, except Basic Energy,
* at most 1 ACE SPEC card total,
* every card id exists in the engine card pool (loadable / legal in-pool).

Card metadata is read from ``data/EN_Card_Data.csv`` (gitignored, license). When
the card data is unavailable (e.g. CI without the engine download) the loader
raises :class:`CardDataUnavailable`, which callers self-skip on — mirroring the
engine tests' self-skip convention.
"""
from __future__ import annotations

import csv
import os
from collections import Counter
from typing import Dict, List

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARD_DATA = os.path.join(REPO, "data", "EN_Card_Data.csv")


class CardDataUnavailable(RuntimeError):
    """Raised when the licensed card data csv is not present."""


_CACHE: Dict[str, Dict[int, Dict[str, str]]] = {}


def load_card_pool(path: str = CARD_DATA) -> Dict[int, Dict[str, str]]:
    """id -> {name, stage_type, rule}. Cached per path."""
    if path in _CACHE:
        return _CACHE[path]
    if not os.path.exists(path):
        raise CardDataUnavailable(f"card data not found: {path}")
    pool: Dict[int, Dict[str, str]] = {}
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                cid = int(row["Card ID"])
            except (KeyError, ValueError):
                continue
            pool[cid] = {
                "name": row.get("Card Name", "").strip(),
                "stage_type": row.get(
                    "Stage (Pokémon)/Type (Energy and Trainer)", "").strip(),
                "rule": row.get("Rule", "").strip(),
            }
    _CACHE[path] = pool
    return pool


def is_basic_energy(card: Dict[str, str]) -> bool:
    return card.get("stage_type", "") == "Basic Energy"


def is_ace_spec(card: Dict[str, str]) -> bool:
    return card.get("rule", "") == "ACE SPEC"


def check_deck(card_ids: List[int],
               pool: Dict[int, Dict[str, str]]) -> Dict[str, object]:
    """Return a legality report for a list of 60 card ids.

    ``legal`` is True iff count==60, no >4 non-basic-energy name, ≤1 ACE SPEC,
    and every id exists in the pool.
    """
    problems: List[str] = []
    n = len(card_ids)
    if n != 60:
        problems.append(f"card count is {n}, expected 60")

    unknown = [cid for cid in card_ids if cid not in pool]
    if unknown:
        problems.append(f"unknown card ids not in pool: {sorted(set(unknown))}")

    name_counts: Counter = Counter()
    ace_specs: List[str] = []
    for cid in card_ids:
        card = pool.get(cid)
        if card is None:
            continue
        if not is_basic_energy(card):
            name_counts[card["name"]] += 1
        if is_ace_spec(card):
            ace_specs.append(card["name"])

    over_four = {name: c for name, c in name_counts.items() if c > 4}
    if over_four:
        problems.append(f"more than 4 copies (non-basic-energy): {over_four}")

    # ACE SPEC limit counts distinct ACE SPEC cards (each is limited to 1 too).
    ace_count = len(ace_specs)
    if ace_count > 1:
        problems.append(f"more than 1 ACE SPEC: {sorted(set(ace_specs))}")

    return {
        "legal": not problems,
        "n_cards": n,
        "ace_spec_count": ace_count,
        "over_four": over_four,
        "unknown_ids": sorted(set(unknown)),
        "problems": problems,
    }


def load_deck_ids(path: str) -> List[int]:
    with open(path) as f:
        return [int(x) for x in f.read().split("\n") if x.strip()][:60]
