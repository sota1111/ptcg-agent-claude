#!/usr/bin/env python3
"""SOT-2282 diagnosis analyzer (reproduces the committed screen result).

Reads the single committed record file
``docs/opponent_pool/screen_sot2282.jsonl`` (15 cells x seeds {2282,4041,8080},
one row per (cell, seed)), pools each cell into a Wilson95 interval, and flags
true weak cells:
  * LOSING  — pooled Wilson95 upper bound < 0.5 (負け越し確定)
  * WEAK    — pooled winrate < 0.55 (系統的弱点)
Mirror self-play (``t_mcts``: champion vs its own config+deck) is labeled
MIRROR: ~0.50 there is the symmetry baseline, not a weakness.

Usage:  python3 eval/_sot2282_analyze.py [path-to-jsonl]
"""
import json
import sys
from math import sqrt

DEFAULT_PATH = "docs/opponent_pool/screen_sot2282.jsonl"
MIRROR_CELLS = {"t_mcts"}  # champion vs identical config+deck: ~0.50 by symmetry
ORDER = ["t_greedy", "t_rule", "t_tactical", "t_random", "t_mcts",
         "d_dragapult", "d_raging_bolt", "d_lillie_champ", "d_dragapult_naic",
         "dg_grimmsnarl", "dm_grimmsnarl", "dg_alakazam", "dm_alakazam",
         "dm_garchomp", "dm_raging_bolt"]


def wilson95(wins, n):
    if n == 0:
        return (None, None)
    z = 1.959963984540054
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def load(path):
    out = []
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except FileNotFoundError:
        pass
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH
    # One row per (cell, seed); last occurrence wins (defensive dedup).
    by_key = {(r["cell"], r["seed"]): r for r in load(path)}
    groups = {}
    for r in by_key.values():
        g = groups.setdefault(r["cell"], {
            "axis": r["axis"], "opp_agent": r["opp_agent"],
            "opp_deck": r["opp_deck"], "wins": 0, "opp": 0, "draws": 0,
            "faults": 0, "seeds": set(), "n": 0})
        g["wins"] += r["wins_champ"]
        g["opp"] += r["wins_opp"]
        g["draws"] += r["draws"]
        g["faults"] += r["faults_total"]
        g["seeds"].add(r["seed"])
        g["n"] += r["n"]

    cells = [c for c in ORDER if c in groups] + \
            [c for c in groups if c not in ORDER]

    print(f"{'cell':<16}{'axis':<8}{'opp':<16}{'N':>4}{'seeds':>6}"
          f"{'wr':>8}{'wilson95':>18}{'W-L-D':>10}{'flt':>4}  flag")
    weak = []
    for c in cells:
        g = groups[c]
        dec = g["wins"] + g["opp"]
        wr = g["wins"] / dec if dec else float("nan")
        lo, hi = wilson95(g["wins"], dec)
        flag = ""
        if c in MIRROR_CELLS:
            flag = "MIRROR(~0.50 expected)"
        elif hi is not None and hi < 0.5:
            flag = "LOSING (CI upper<0.5)"
            weak.append(c)
        elif wr < 0.55:
            flag = "WEAK (wr<0.55)"
            weak.append(c)
        ci = f"[{lo:.3f},{hi:.3f}]" if lo is not None else "n/a"
        print(f"{c:<16}{g['axis']:<8}{g['opp_agent']:<16}{g['n']:>4}"
              f"{len(g['seeds']):>6}{wr:>8.3f}{ci:>18} "
              f"{g['wins']}-{g['opp']}-{g['draws']:<4}{g['faults']:>4}  {flag}")

    faults_total = sum(g["faults"] for g in groups.values())
    print(f"\nfaults across all cells: {faults_total}")
    print(f"true weak cells (excl. mirror): {weak or 'NONE'}")

    print("\n=== policy-strength delta (same deck: greedy vs mcts opponent) ===")
    for stem in ["grimmsnarl", "alakazam"]:
        gcell, mcell = f"dg_{stem}", f"dm_{stem}"
        if gcell in groups and mcell in groups:
            gg, gm = groups[gcell], groups[mcell]
            gwr = gg["wins"] / (gg["wins"] + gg["opp"])
            mwr = gm["wins"] / (gm["wins"] + gm["opp"])
            print(f"  {stem:<12} greedy={gwr:.3f} (N={gg['n']})  "
                  f"mcts={mwr:.3f} (N={gm['n']})  delta={mwr - gwr:+.3f}")


if __name__ == "__main__":
    main()
