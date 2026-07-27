"""Parse the public PTCG-AI-Battle meta dashboard into normalized snapshots.

Source: https://ptcg-meta.vercel.app/ — a static site whose per-day pages
(``daily/<YYYY-MM-DD>.html``) render, as plain server-side HTML text, three
*separate* signals we care about:

* **LB Top10**  — archetype distribution among the leaderboard's top 10 teams
* **LB Top20**  — archetype distribution among the top 20 teams
* **Top100 全体** — archetype distribution across the full top-100 board
* **リーダーボード Top30** — the ranked team table (score + main archetype),
  from which we read the *leaderboard leaders* (high rank, possibly low share).

Keeping Top10/Top20/Top100 distinct is a hard requirement of SOT-2055: a deck
can be rare in the Top100 yet sit at #1 on the board (e.g. タケルライコex), so
usage share alone must not drive selection.

This module is **pure text parsing** — no network, no engine — so it is safe to
import in unit tests. Network fetching lives in :mod:`tools.meta_fetch`.
"""
from __future__ import annotations

import html
import re
from typing import Dict, List

SOURCE_BASE = "https://ptcg-meta.vercel.app"

# Section headers as they appear in the flattened page text.
_H_TOP10 = "LB Top10"
_H_TOP20 = "LB Top20"
_H_TOP100 = "主力カードランキング（Top100 全体）"
_H_LB_TABLE = "リーダーボード Top30"

_SHARE_RE = re.compile(r"^(\d+(?:\.\d+)?)%$")
_INT_RE = re.compile(r"^\d+$")
_FLOAT_RE = re.compile(r"^\d+(?:\.\d+)?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _text_lines(page_html: str) -> List[str]:
    """Flatten HTML to non-empty text lines (tags stripped, entities decoded)."""
    text = re.sub(r"<[^>]*>", "\n", page_html)
    text = html.unescape(text)
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _parse_band(lines: List[str], start: int) -> Dict[str, Dict[str, float]]:
    """Parse a ``name / teams / share%`` band starting after its header.

    Rows repeat as (archetype, teams:int, share:'NN%'). Parsing stops at the
    first line that does not continue the (name, int, pct) pattern.
    """
    out: Dict[str, Dict[str, float]] = {}
    i = start
    n = len(lines)
    # Skip the column labels ("主力", "チーム", "シェア").
    while i < n and lines[i] in ("主力", "チーム", "シェア", "主力カード"):
        i += 1
    while i + 2 < n:
        name, teams, share = lines[i], lines[i + 1], lines[i + 2]
        if not (_INT_RE.match(teams) and _SHARE_RE.match(share)):
            break
        out[name] = {"teams": int(teams), "share": float(share.rstrip("%"))}
        i += 3
    return out


def _parse_top100(lines: List[str], start: int) -> List[Dict[str, object]]:
    """Parse the ranked Top100 table: rows of (rank, name, teams, share)."""
    out: List[Dict[str, object]] = []
    i = start
    n = len(lines)
    while i < n and lines[i] in ("#", "主力カード", "チーム数", "シェア"):
        i += 1
    while i + 3 < n:
        rank, name, teams, share = lines[i:i + 4]
        if not (_INT_RE.match(rank) and _INT_RE.match(teams)
                and _SHARE_RE.match(share)):
            break
        out.append({
            "rank": int(rank),
            "archetype": name,
            "teams": int(teams),
            "share": float(share.rstrip("%")),
        })
        i += 4
    return out


def _parse_lb_leaders(lines: List[str], start: int,
                      limit: int = 10) -> List[Dict[str, object]]:
    """Parse the leaderboard table: rows of (rank, team, score, archetype, type).

    The 主要ポケモン / タイプ columns give the archetype of each top team, which
    is our high-rank / low-share signal. We keep the first ``limit`` rows.
    """
    out: List[Dict[str, object]] = []
    i = start
    n = len(lines)
    while i < n and lines[i] in ("順位", "チーム", "スコア", "主要ポケモン",
                                 "タイプ"):
        i += 1
    while i + 4 < n and len(out) < limit:
        rank, team, score, arch, typ = lines[i:i + 5]
        if not (_INT_RE.match(rank) and _FLOAT_RE.match(score)):
            break
        out.append({
            "rank": int(rank),
            "team": team,
            "score": float(score),
            "archetype": arch,
            "type": typ,
        })
        i += 5
    return out


def _find(lines: List[str], header: str, start: int = 0) -> int:
    for i in range(start, len(lines)):
        if lines[i] == header:
            return i
    return -1


def _find_prefix(lines: List[str], prefix: str, start: int = 0) -> int:
    for i in range(start, len(lines)):
        if lines[i].startswith(prefix):
            return i
    return -1


def parse_daily_html(page_html: str, date: str) -> Dict[str, object]:
    """Parse one ``daily/<date>.html`` page into a normalized snapshot dict.

    Returns a JSON-serializable snapshot with the three bands kept separate.
    Raises ``ValueError`` if the mandatory Top100 table is missing.
    """
    lines = _text_lines(page_html)

    lb_csv = ""
    for ln in lines:
        if ln.startswith("LBスナップショット:"):
            lb_csv = ln.split(":", 1)[1].strip()
            break

    i10 = _find(lines, _H_TOP10)
    i20 = _find(lines, _H_TOP20)
    i100 = _find(lines, _H_TOP100)
    itbl = _find_prefix(lines, _H_LB_TABLE)
    if i100 < 0:
        raise ValueError(f"Top100 table not found in daily page for {date}")

    top10 = _parse_band(lines, i10 + 1) if i10 >= 0 else {}
    top20 = _parse_band(lines, i20 + 1) if i20 >= 0 else {}
    top100 = _parse_top100(lines, i100 + 1)
    leaders = _parse_lb_leaders(lines, itbl + 1) if itbl >= 0 else []

    return {
        "date": date,
        "source_url": f"{SOURCE_BASE}/daily/{date}.html",
        "lb_csv": lb_csv,
        "bands": {
            "top10": top10,
            "top20": top20,
            "top100": top100,
        },
        "lb_leaders": leaders,
    }


def top100_share(snapshot: Dict[str, object], archetype: str) -> float:
    """Top100 share (%) for an archetype in a snapshot, 0.0 if absent."""
    for row in snapshot["bands"]["top100"]:  # type: ignore[index]
        if row["archetype"] == archetype:
            return float(row["share"])
    return 0.0


def top100_rank(snapshot: Dict[str, object], archetype: str) -> int:
    """Top100 rank for an archetype, or a large sentinel if absent."""
    for row in snapshot["bands"]["top100"]:  # type: ignore[index]
        if row["archetype"] == archetype:
            return int(row["rank"])
    return 999


def band_share(snapshot: Dict[str, object], band: str, archetype: str) -> float:
    """Share (%) for an archetype within the top10/top20 band, 0.0 if absent."""
    b = snapshot["bands"].get(band, {})  # type: ignore[union-attr]
    if isinstance(b, dict):
        return float(b.get(archetype, {}).get("share", 0.0))
    return 0.0


def all_archetypes(snapshot: Dict[str, object]) -> List[str]:
    """Every archetype named anywhere in a snapshot (Top100 ∪ bands ∪ LB)."""
    names = {row["archetype"] for row in snapshot["bands"]["top100"]}  # type: ignore[index]
    for band in ("top10", "top20"):
        names.update(snapshot["bands"].get(band, {}))  # type: ignore[union-attr]
    names.update(r["archetype"] for r in snapshot["lb_leaders"])  # type: ignore[index]
    return sorted(names)
